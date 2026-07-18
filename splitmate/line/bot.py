"""LINE Webhook：在群組記帳，成功後附上 SplitMate 網頁連結。"""
from __future__ import annotations

import logging
import re
from decimal import Decimal
from typing import Optional

from flask import Blueprint, abort, current_app, request
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import (
    FlexSendMessage,
    MessageEvent,
    TextMessage,
    TextSendMessage,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from models import (
    SplitType,
    cleanup_old_duplicate_logs,
    generate_operation_hash,
    get_bill_by_id,
    get_db,
    get_or_create_member_by_line_id,
    is_duplicate_operation,
    list_group_members,
    log_operation,
)
from splitmate.config import Config
from splitmate.services import bill_service, settlement_service
from splitmate.services.group_service import (
    get_or_create_group_for_line,
    merge_member_to_line_id,
)
from splitmate.services.mentions import extract_mention_user_ids, parse_at_names

logger = logging.getLogger(__name__)

line_bp = Blueprint("line", __name__)

ADD_BILL_PATTERN = r"^#分帳\s+([\d\.]+)\s+(.+?)\s+((?:@\S+(?:\s+[\d\.]+)?\s*)+)$"
BILL_DETAILS_PATTERN = r"^#支出詳情\s+B-(\d+)$"
SETTLE_PAYMENT_PATTERN = r"^#結帳\s+B-(\d+)\s+((?:@\S+\s*)+)$"
HELP_PATTERN = r"^#幫助$"
FLEX_CREATE_BILL_PATTERN = r"^#建立帳單$"
FLEX_MENU_PATTERN = r"^#選單$"
GROUP_SETTLEMENT_PATTERN = r"^#群組結算$"
GROUP_DEBTS_OVERVIEW_PATTERN = r"^#群組欠款$"
GROUP_BILLS_OVERVIEW_PATTERN = r"^#群組帳單$"
COMPLETE_BILLS_PATTERN = r"^#完整帳單$"
WEB_LINK_PATTERN = r"^#網頁$"
MEMBERS_PATTERN = r"^#成員$"
MERGE_MEMBER_PATTERN = r"^#合併\s+(\S+)\s+@\S+"


def _api() -> LineBotApi:
    return current_app.extensions["line_bot_api"]


def _handler() -> WebhookHandler:
    return current_app.extensions["line_handler"]


def _web_url_for_line_group(db: Session, line_group_id: str) -> tuple[str, str]:
    group = get_or_create_group_for_line(db, line_group_id)
    return Config.group_web_url(group.public_token), group.edit_pin


def _short_footer(web_url: str) -> str:
    return f"\n\n📊 網頁查看結算：\n{web_url}"


@line_bp.route("/splitmate/webhook", methods=["POST"])
@line_bp.route("/webhook", methods=["POST"])
def callback():
    """LINE Webhook 入口（新專案請用 /splitmate/webhook）。"""
    if not Config.line_enabled():
        abort(503)
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        _handler().handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    except Exception:
        logger.exception("LINE callback error")
        abort(500)
    return "OK"


def register_line_handlers(handler: WebhookHandler):
    @handler.add(MessageEvent, message=TextMessage)
    def handle_text_message(event: MessageEvent):
        text = event.message.text.strip()
        reply_token = event.reply_token
        if not reply_token or reply_token == "<no-reply>":
            return

        source = event.source
        group_id: Optional[str] = None
        sender_id = source.user_id
        mention_ids = extract_mention_user_ids(event.message)

        if source.type == "group":
            group_id = source.group_id
        elif source.type == "room":
            group_id = source.room_id
        else:
            _api().reply_message(
                reply_token, TextSendMessage(text="SplitMate 僅限群組內使用。")
            )
            return

        if not group_id or not sender_id:
            return

        sender_name = ""
        try:
            profile = _api().get_group_member_profile(group_id, sender_id)
            sender_name = profile.display_name
        except LineBotApiError:
            logger.warning("無法取得群組成員 profile")

        try:
            with get_db() as db:
                if hash(text) % 100 == 0:
                    cleanup_old_duplicate_logs(db)
                    db.commit()

                # 只要有人在群裡發言指令，就綁定其 LINE ID
                if sender_name:
                    get_or_create_member_by_line_id(
                        db,
                        line_user_id=sender_id,
                        group_id=group_id,
                        display_name=sender_name,
                    )
                    db.commit()

                web_url, edit_pin = _web_url_for_line_group(db, group_id)

                if m := re.match(ADD_BILL_PATTERN, text):
                    if not sender_name:
                        _api().reply_message(
                            reply_token,
                            TextSendMessage(text="無法獲取您的群組名稱，請稍後再試。"),
                        )
                        return
                    _handle_add_bill(
                        reply_token,
                        m,
                        group_id,
                        sender_id,
                        sender_name,
                        db,
                        web_url,
                        mention_ids,
                    )
                elif m := re.match(BILL_DETAILS_PATTERN, text):
                    bill_id = int(m.group(1))
                    _handle_bill_details(reply_token, bill_id, group_id, db, web_url)
                elif m := re.match(SETTLE_PAYMENT_PATTERN, text):
                    _handle_settle(
                        reply_token,
                        int(m.group(1)),
                        m.group(2),
                        group_id,
                        sender_id,
                        db,
                        web_url,
                        mention_ids,
                    )
                elif re.match(MEMBERS_PATTERN, text):
                    _handle_members(reply_token, group_id, db, web_url)
                elif m := re.match(MERGE_MEMBER_PATTERN, text):
                    _handle_merge_member(
                        reply_token,
                        group_id,
                        m.group(1),
                        mention_ids,
                        db,
                        web_url,
                    )
                elif re.match(HELP_PATTERN, text):
                    _send_help(reply_token, web_url)
                elif re.match(FLEX_MENU_PATTERN, text):
                    _send_menu(reply_token, web_url)
                elif re.match(FLEX_CREATE_BILL_PATTERN, text):
                    _send_create_guide(reply_token)
                elif re.match(WEB_LINK_PATTERN, text):
                    _api().reply_message(
                        reply_token,
                        TextSendMessage(
                            text=(
                                "📊 本群組網頁儀表板\n"
                                f"{web_url}\n\n"
                                f"🔐 編輯 PIN：{edit_pin}\n"
                                "用途：在網頁標記已付／刪除帳單／批次結算時輸入。\n"
                                "LINE 內用 #結帳 則不需要 PIN。\n"
                                "請妥善保管，勿任意公開轉貼。"
                            )
                        ),
                    )
                elif re.match(GROUP_SETTLEMENT_PATTERN, text):
                    _handle_settlement_short(reply_token, group_id, db, web_url)
                elif re.match(GROUP_DEBTS_OVERVIEW_PATTERN, text):
                    _handle_debts_short(reply_token, group_id, db, web_url)
                elif re.match(GROUP_BILLS_OVERVIEW_PATTERN, text) or re.match(
                    COMPLETE_BILLS_PATTERN, text
                ):
                    _handle_bills_short(reply_token, group_id, db, web_url)
                else:
                    logger.info("Unmatched command: %s", text)
        except SQLAlchemyError:
            logger.exception("DB error")
            _api().reply_message(
                reply_token, TextSendMessage(text="資料庫操作錯誤，請稍後再試。")
            )
        except Exception:
            logger.exception("Unexpected LINE handler error")
            _api().reply_message(
                reply_token, TextSendMessage(text="發生未預期錯誤，請稍後再試。")
            )


def _handle_add_bill(
    reply_token, match, group_id, payer_id, payer_name, db, web_url, mention_ids
):
    bill, status, payer_share, err = bill_service.create_bill_from_command(
        db,
        group_id=group_id,
        payer_line_user_id=payer_id,
        payer_name=payer_name,
        total_amount_str=match.group(1),
        description=match.group(2).strip(),
        participants_input_str=match.group(3).strip(),
        mention_user_ids=mention_ids,
    )
    if status == "duplicate_op":
        _api().reply_message(reply_token, TextSendMessage(text=f"⚠️ {err}"))
        return
    if status == "error":
        _api().reply_message(reply_token, TextSendMessage(text=f"❌ {err}"))
        return
    if status == "duplicate" and bill:
        msg = (
            f"⚠️ 相同內容帳單已存在 B-{bill.id}\n"
            f"{bill.description}｜${bill.total_bill_amount}"
            + _short_footer(web_url)
        )
        _api().reply_message(reply_token, TextSendMessage(text=msg))
        return
    if not bill:
        _api().reply_message(reply_token, TextSendMessage(text="新增失敗，請稍後再試。"))
        return

    others = sum((p.amount_owed for p in bill.participants), Decimal(0))
    bound = sum(1 for p in bill.participants if p.debtor_member_profile.line_user_id)
    lines = [
        f"✅ 已記帳 B-{bill.id}",
        f"{bill.description}｜${bill.total_bill_amount}",
        f"類型：{'均攤' if bill.split_type == SplitType.EQUAL else '分別計算'}",
    ]
    if payer_share and payer_share > 0:
        lines.append(f"您的分攤：${payer_share}｜應收回：${others}")
    for p in bill.participants[:6]:
        tag = "🔗" if p.debtor_member_profile.line_user_id else "❓"
        lines.append(f"・{tag} @{p.debtor_member_profile.name} ${p.amount_owed}")
    if len(bill.participants) > 6:
        lines.append(f"・…共 {len(bill.participants)} 人")
    lines.append(f"成員綁定：{bound}/{len(bill.participants)} 人已有 LINE ID")
    if bound < len(bill.participants):
        lines.append("提示：請用鍵盤「@點選成員」，不要手動打字 @名字")
    lines.append(_short_footer(web_url).strip())
    _api().reply_message(reply_token, TextSendMessage(text="\n".join(lines)))


def _handle_bill_details(reply_token, bill_id, group_id, db, web_url):
    bill = get_bill_by_id(db, bill_id, group_id)
    if not bill:
        _api().reply_message(reply_token, TextSendMessage(text=f"找不到帳單 B-{bill_id}。"))
        return
    unpaid = [p for p in bill.participants if not p.is_paid]
    lines = [
        f"💳 B-{bill.id} {bill.description}",
        f"付款人 @{bill.payer_member_profile.name}｜總額 ${bill.total_bill_amount}",
        f"未結清 {len(unpaid)}/{len(bill.participants)} 人",
    ]
    for p in unpaid[:8]:
        tag = "🔗" if p.debtor_member_profile.line_user_id else "❓"
        lines.append(f"・{tag} @{p.debtor_member_profile.name} ${p.amount_owed}")
    lines.append(_short_footer(web_url).strip())
    _api().reply_message(reply_token, TextSendMessage(text="\n".join(lines)))


def _handle_settle(
    reply_token, bill_id, mentions, group_id, sender_id, db, web_url, mention_ids
):
    op = generate_operation_hash(sender_id, "settle_payment", f"settle:{bill_id}:{mentions}")
    if is_duplicate_operation(db, op, group_id, sender_id, 2):
        _api().reply_message(reply_token, TextSendMessage(text="⚠️ 偵測到重複結帳，請稍候。"))
        return
    log_operation(db, op, group_id, sender_id, "settle_payment")

    names = parse_at_names(mentions)
    ok, msg, meta = bill_service.settle_participants(
        db,
        group_id=group_id,
        bill_id=bill_id,
        debtor_names=names,
        actor_line_user_id=sender_id,
        require_payer=True,
        mention_user_ids=mention_ids,
    )
    if not ok:
        _api().reply_message(reply_token, TextSendMessage(text=f"❌ {msg}"))
        return

    settled = ", ".join(f"@{n}" for n in meta["settled"])
    extra = "（帳單已封存）" if meta.get("archived") else f"（尚餘 {meta['remaining_unpaid']} 人未付）"
    text = (
        f"✅ 已標記付款 B-{bill_id}\n"
        f"{settled}｜${meta['settled_amount']}\n"
        f"{extra}"
        + _short_footer(web_url)
    )
    _api().reply_message(reply_token, TextSendMessage(text=text))


def _handle_members(reply_token, group_id, db, web_url):
    members = list_group_members(db, group_id)
    if not members:
        _api().reply_message(
            reply_token,
            TextSendMessage(
                text=(
                    "尚無成員紀錄。請由付款人用 #分帳 並 @點選成員。"
                    + _short_footer(web_url)
                )
            ),
        )
        return
    lines = ["👥 本群組已記錄的成員"]
    for m in members[:30]:
        if m.line_user_id:
            lines.append(f"🔗 @{m.name}（已綁定 ID）")
        else:
            lines.append(f"❓ @{m.name}（僅有名字，尚未綁定 ID）")
    lines.append("")
    lines.append("🔗 = 已綁定 LINE ID")
    lines.append("❓ = 僅名字；之後可：#合併 顯示名 @點選本人")
    lines.append(_short_footer(web_url).strip())
    _api().reply_message(reply_token, TextSendMessage(text="\n".join(lines)))


def _handle_merge_member(reply_token, group_id, old_name, mention_ids, db, web_url):
    if not mention_ids:
        _api().reply_message(
            reply_token,
            TextSendMessage(
                text=(
                    "合併失敗：請用鍵盤「@點選」目標成員（不要手打 @名字）。\n"
                    f"範例：#合併 {old_name} @點選本人"
                )
            ),
        )
        return
    # 取第一個被點選的 mention
    display_name, line_user_id = next(iter(mention_ids.items()))
    ok, msg = merge_member_to_line_id(
        db,
        group_id=group_id,
        old_name=old_name,
        line_user_id=line_user_id,
        display_name=display_name,
    )
    prefix = "✅ " if ok else "❌ "
    _api().reply_message(
        reply_token, TextSendMessage(text=prefix + msg + _short_footer(web_url))
    )


def _handle_settlement_short(reply_token, group_id, db, web_url):
    data = settlement_service.group_settlement(db, group_id)
    if data["cleared"] and not data["edges"]:
        msg = "🎉 群組淨欠款已結清！" + _short_footer(web_url)
        _api().reply_message(reply_token, TextSendMessage(text=msg))
        return
    lines = ["💱 淨欠款摘要（抵消後）"]
    for e in data["edges"][:8]:
        lines.append(f"・@{e['from']} → @{e['to']} ${e['amount']}")
    if len(data["edges"]) > 8:
        lines.append(f"・…共 {len(data['edges'])} 筆")
    lines.append(f"未結清明細共 {data['unpaid_count']} 筆")
    lines.append(_short_footer(web_url).strip())
    _api().reply_message(reply_token, TextSendMessage(text="\n".join(lines)))


def _handle_debts_short(reply_token, group_id, db, web_url):
    data = settlement_service.group_settlement(db, group_id)
    if not data["raw_debts"]:
        _api().reply_message(
            reply_token, TextSendMessage(text="目前沒有未結清欠款。" + _short_footer(web_url))
        )
        return
    lines = [f"💰 原始欠款（前 8 筆／共 {len(data['raw_debts'])}）"]
    for d in data["raw_debts"][:8]:
        lines.append(f"・@{d['from']} → @{d['to']} ${d['amount']}（B-{d['bill_id']}）")
    lines.append(_short_footer(web_url).strip())
    _api().reply_message(reply_token, TextSendMessage(text="\n".join(lines)))


def _handle_bills_short(reply_token, group_id, db, web_url):
    bills = bill_service.list_bills(db, group_id, include_archived=False)
    if not bills:
        _api().reply_message(
            reply_token, TextSendMessage(text="目前沒有帳單。" + _short_footer(web_url))
        )
        return
    lines = [f"📋 近期帳單（{min(8, len(bills))}/{len(bills)}）"]
    for b in bills[:8]:
        unpaid = sum(1 for p in b.participants if not p.is_paid)
        lines.append(
            f"・B-{b.id} {b.description} ${b.total_bill_amount}（未付 {unpaid}）"
        )
    lines.append(_short_footer(web_url).strip())
    _api().reply_message(reply_token, TextSendMessage(text="\n".join(lines)))


def _send_help(reply_token, web_url):
    text = (
        "💸 SplitMate 指令一覽\n"
        "────────────\n"
        "【記帳｜必須由付款人發送】\n"
        "⚠️ 誰先墊錢，就由「付款人」本人打 #分帳。\n"
        "　系統會把「發言者」記成付款人。\n"
        "#分帳 300 午餐 @小美 @小王\n"
        "　→ 三人均攤（含付款人）\n"
        "#分帳 1000 聚餐 @小美 400 @小王 350\n"
        "　→ 分別金額；餘額算付款人自己\n"
        "\n"
        "【查帳／結算】\n"
        "#群組結算 → 全部未付帳正負相抵，誰付給誰\n"
        "#群組欠款 → 未付欠款摘要\n"
        "#群組帳單（或 #完整帳單）→ 近期帳單列表\n"
        "#支出詳情 B-1 → 單筆明細\n"
        "#結帳 B-1 @小美 → 標記已付\n"
        "　※ LINE 內只有「該筆付款人」能 #結帳\n"
        "　※ 其他人請開網頁＋PIN 標記已付\n"
        "\n"
        "【成員／補綁 ID】\n"
        "#成員 → 🔗已綁定／❓僅名字\n"
        "#合併 小美 @點選小美\n"
        "　（整句一次送出；@ 必須鍵盤點選）\n"
        "　1) 當初沒綁到 ID → #成員 出現 ❓小美\n"
        "　2) 進群後：#合併 小美 + @點選本人\n"
        "　3) 舊帳轉到她的 LINE ID → 變 🔗\n"
        "　※「小美」要和 ❓ 後面名字完全相同\n"
        "\n"
        "【網頁與 PIN】\n"
        "#網頁 → 專屬連結 ＋ 編輯 PIN\n"
        "　網頁可：全部結算、勾選多筆相抵、\n"
        "　單人／批次標記已付、刪除帳單\n"
        "　（以上需 PIN；LINE #結帳 不需）\n"
        f"　{web_url}\n"
        "\n"
        "#選單 → 快捷按鈕\n"
        "#建立帳單 → 記帳範例\n"
        "────────────\n"
        "⚠️ @成員請用鍵盤點選，才能綁定 LINE ID。"
    )
    _api().reply_message(reply_token, TextSendMessage(text=text))


def _send_menu(reply_token, web_url):
    bubble = {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "SplitMate",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#0F766E",
                },
                {
                    "type": "text",
                    "text": "LINE 記帳 · 網頁結算",
                    "size": "sm",
                    "color": "#64748B",
                },
            ],
            "backgroundColor": "#ECFDF5",
            "paddingAll": "16px",
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#0F766E",
                    "action": {"type": "uri", "label": "開啟網頁儀表板", "uri": web_url},
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {
                        "type": "message",
                        "label": "建立帳單說明",
                        "text": "#建立帳單",
                    },
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {
                        "type": "message",
                        "label": "查看成員綁定",
                        "text": "#成員",
                    },
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {"type": "message", "label": "幫助", "text": "#幫助"},
                },
            ],
        },
    }
    _api().reply_message(
        reply_token, FlexSendMessage(alt_text="SplitMate 選單", contents=bubble)
    )


def _send_create_guide(reply_token):
    text = (
        "📝 建立帳單（必須由付款人發送）\n"
        "請用鍵盤「@」點選成員（不要手動打字）\n\n"
        "均攤：\n#分帳 300 午餐 @小美 @小王\n\n"
        "分別：\n#分帳 1000 聚餐 @小美 400 @小王 350\n\n"
        "代墊：\n#分帳 500 代付 @小美 300 @小王 200\n\n"
        "網頁／PIN／刪除帳單：打 #網頁"
    )
    _api().reply_message(reply_token, TextSendMessage(text=text))
