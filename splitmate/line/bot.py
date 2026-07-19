"""LINE Webhook：在群組記帳，成功後附上 SplitMate 網頁連結。"""
from __future__ import annotations

import logging
import re
from decimal import Decimal
from typing import Optional

from flask import Blueprint, abort, current_app, request
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from models import (
    SplitType,
    cleanup_old_duplicate_logs,
    get_db,
    get_or_create_member_by_line_id,
    list_group_members,
)
from splitmate.config import Config
from splitmate.services import bill_service, settlement_service
from splitmate.services.group_service import (
    get_or_create_group_for_line,
    merge_member_to_line_id,
)
from splitmate.services.mentions import extract_mention_user_ids

logger = logging.getLogger(__name__)

line_bp = Blueprint("line", __name__)

ADD_BILL_PATTERN = r"^#分帳\s+([\d\.]+)\s+(.+?)\s+((?:@\S+(?:\s+[\d\.]+)?\s*)+)$"
HELP_PATTERN = r"^#幫助$"
SETTLEMENT_PATTERN = r"^#結算$"
DEBTS_PATTERN = r"^#欠款$"
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
    return f"\n\n📊 網頁：\n{web_url}"


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
                elif re.match(WEB_LINK_PATTERN, text):
                    _api().reply_message(
                        reply_token,
                        TextSendMessage(
                            text=(
                                "📊 本群專屬網頁\n"
                                f"{web_url}\n\n"
                                f"🔐 編輯 PIN：{edit_pin}\n"
                                "在網頁標記已付／批次結清／刪除帳單時使用。\n"
                                "請妥善保管，勿任意公開轉貼。"
                            )
                        ),
                    )
                elif re.match(SETTLEMENT_PATTERN, text):
                    _handle_settlement_short(reply_token, group_id, db, web_url)
                elif re.match(DEBTS_PATTERN, text):
                    _handle_debts_short(reply_token, group_id, db, web_url)
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
    elif payer_share == 0:
        lines.append(f"代墊｜應收回：${others}")
    for p in bill.participants[:6]:
        tag = "🔗" if p.debtor_member_profile.line_user_id else "❓"
        lines.append(f"・{tag} @{p.debtor_member_profile.name} ${p.amount_owed}")
    if len(bill.participants) > 6:
        lines.append(f"・…共 {len(bill.participants)} 人")
    lines.append(f"成員綁定：{bound}/{len(bill.participants)} 人已有 LINE ID")
    lines.append(_short_footer(web_url).strip())
    _api().reply_message(reply_token, TextSendMessage(text="\n".join(lines)))


def _handle_members(reply_token, group_id, db, web_url):
    members = list_group_members(db, group_id)
    if not members:
        _api().reply_message(
            reply_token,
            TextSendMessage(
                text=(
                    "尚無成員紀錄。請由付款人用 #分帳，並 @後點選成員。"
                    + _short_footer(web_url)
                )
            ),
        )
        return
    lines = ["👥 參與分帳成員"]
    for m in members[:30]:
        if m.line_user_id:
            lines.append(f"🔗 @{m.name}")
        else:
            lines.append(f"❓ @{m.name}")
    lines.append("")
    lines.append("🔗 已綁 ID｜❓ 僅顯示名字")
    lines.append("補綁：#合併 舊名 @後點選本人")
    lines.append(_short_footer(web_url).strip())
    _api().reply_message(reply_token, TextSendMessage(text="\n".join(lines)))


def _handle_merge_member(reply_token, group_id, old_name, mention_ids, db, web_url):
    if not mention_ids:
        _api().reply_message(
            reply_token,
            TextSendMessage(
                text=(
                    "合併失敗：請用鍵盤「@後點選」目標成員（不要手打名字）。\n"
                    f"範例：#合併 {old_name} @後點選本人"
                )
            ),
        )
        return
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
        msg = "🎉 全部未付帳已結清！" + _short_footer(web_url)
        _api().reply_message(reply_token, TextSendMessage(text=msg))
        return
    lines = [f"💱 結算（最少 {data.get('transfer_count', len(data['edges']))} 筆轉帳）"]
    for e in data["edges"][:10]:
        lines.append(f"・@{e['from']} → @{e['to']} ${e['amount']}")
    if len(data["edges"]) > 10:
        lines.append(f"・…共 {len(data['edges'])} 筆")
    lines.append(_short_footer(web_url).strip())
    _api().reply_message(reply_token, TextSendMessage(text="\n".join(lines)))


def _handle_debts_short(reply_token, group_id, db, web_url):
    data = settlement_service.group_settlement(db, group_id)
    if not data["raw_debts"]:
        _api().reply_message(
            reply_token, TextSendMessage(text="目前沒有未結清欠款。" + _short_footer(web_url))
        )
        return
    lines = [f"💰 未付欠款摘要（前 8／共 {len(data['raw_debts'])}）"]
    for d in data["raw_debts"][:8]:
        lines.append(f"・@{d['from']} → @{d['to']} ${d['amount']}（B-{d['bill_id']}）")
    lines.append(_short_footer(web_url).strip())
    _api().reply_message(reply_token, TextSendMessage(text="\n".join(lines)))


def _send_help(reply_token, web_url):
    text = (
        "SplitMate 指令一覽\n"
        "────────────\n"
        "【 分帳｜必須由付款人發送 】\n"
        "⚠️ 由付款人本人傳送 #分帳\n"
        "⚠️ 傳送 #分帳 時\n"
        "➜ @後點選標註成員即可自動綁定ID\n"
        "➜ @後直接輸入名字，即不會綁定ID\n"
        "\n"
        "#分帳 300 午餐 @小美 @小王\n"
        "　➜ 含付款人 共三人均攤\n"
        "　➜ 訊息需包含空格\n"
        "#分帳 1000 聚餐 @小美 400 @小王 350\n"
        "　➜ 分別分攤，餘額算付款人\n"
        "　➜ 餘款可為零（代墊）\n"
        "　➜ 訊息需包含空格\n"
        "\n"
        "【 查帳｜結算 】\n"
        "#結算 ➜ 全部未付帳結算，看誰付給誰\n"
        "#欠款 ➜ 未付欠款摘要\n"
        "\n"
        "【 成員｜補綁 ID 】\n"
        "#成員 ➜ 查看參與分帳成員\n"
        "   ➜ 🔗 已綁ID｜❓ 僅顯示名字\n"
        "#合併 小美 @後點選小美\n"
        "　1) 原沒綁 ID（ 名單出現 ❓小美）\n"
        "　2) 輸入：#合併 小美 @後點選小美\n"
        "　3) 舊名綁定 LINE ID → 變 🔗 小美\n"
        "　➜「小美」要和❓後面名字相同\n"
        "\n"
        "【 網頁與 PIN 】\n"
        "#網頁 ➜  專屬網頁連結 ＋ 查看 PIN\n"
        "　網頁功能：\n"
        "　➜ 全部結算\n"
        "　➜ 勾選多筆相抵\n"
        "　➜ 單人/批次標記已付\n"
        "　➜ 刪除帳單\n"
        " （需在網頁輸入 PIN才可操作）\n"
        "────────────\n"
        " .ᐟ.ᐟ 本群專屬網頁 .ᐟ.ᐟ\n"
        f"{web_url}"
    )
    _api().reply_message(reply_token, TextSendMessage(text=text))
