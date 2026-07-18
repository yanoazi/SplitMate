from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session, joinedload

from models import (
    Bill,
    BillParticipant,
    SplitType,
    atomic_create_bill,
    generate_content_hash,
    generate_operation_hash,
    get_bill_by_id,
    get_or_create_member_by_line_id,
    get_or_create_member_by_name,
    is_duplicate_operation,
    log_operation,
)
from splitmate.services.split_engine import parse_participant_input


def create_bill_from_command(
    db: Session,
    *,
    group_id: str,
    payer_line_user_id: str,
    payer_name: str,
    total_amount_str: str,
    description: str,
    participants_input_str: str,
    mention_user_ids: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[Bill], str, Optional[Decimal], Optional[str]]:
    """
    回傳 (bill, status, payer_share, error_message)
    status: success | duplicate | error | duplicate_op

    mention_user_ids: 從 LINE 真實 @提及解析出的 {顯示名稱: userId}
    """
    mention_user_ids = mention_user_ids or {}
    operation_content = f"add_bill:{total_amount_str}:{description}:{participants_input_str}"
    operation_hash = generate_operation_hash(payer_line_user_id, "add_bill", operation_content)
    if is_duplicate_operation(db, operation_hash, group_id, payer_line_user_id, 0.5):
        return None, "duplicate_op", None, "偵測到重複操作，請稍候再試。"
    log_operation(db, operation_hash, group_id, payer_line_user_id, "add_bill")

    if not description.strip():
        return None, "error", None, "請提供支出說明。"

    try:
        total = Decimal(total_amount_str)
        if total <= 0:
            raise ValueError("總支出金額必須大於 0。")
    except Exception as e:
        return None, "error", None, f"總支出金額無效: {e}"

    payer = get_or_create_member_by_line_id(
        db, line_user_id=payer_line_user_id, group_id=group_id, display_name=payer_name
    )
    charged, split_type, err, payer_share = parse_participant_input(
        participants_input_str, total, payer_name
    )
    if err:
        return None, "error", None, err

    content_hash = generate_content_hash(
        payer_id=payer.id,
        description=description,
        amount=total_amount_str,
        participants_str=participants_input_str,
        group_id=group_id,
    )
    existing = (
        db.query(Bill)
        .filter(Bill.group_id == group_id, Bill.content_hash == content_hash)
        .first()
    )
    if existing:
        return get_bill_by_id(db, existing.id, group_id), "duplicate", payer_share, None

    bill_data = {
        "group_id": group_id,
        "description": description.strip(),
        "total_bill_amount": total,
        "payer_member_id": payer.id,
        "split_type": split_type,
        "content_hash": content_hash,
    }
    participants_data = []
    for name, amount in charged or []:
        line_id = mention_user_ids.get(name)
        debtor = get_or_create_member_by_name(
            db, name=name, group_id=group_id, line_user_id=line_id
        )
        participants_data.append(
            {"debtor_member_id": debtor.id, "amount_owed": amount, "is_paid": False}
        )

    bill, status = atomic_create_bill(db, bill_data, participants_data)
    if status == "success":
        return bill, "success", payer_share, None
    if status in ("duplicate_found", "duplicate_constraint"):
        return bill, "duplicate", payer_share, None
    return None, "error", None, "新增支出失敗，請稍後再試。"


def list_bills(db: Session, group_id: str, include_archived: bool = False) -> List[Bill]:
    q = (
        db.query(Bill)
        .options(
            joinedload(Bill.payer_member_profile),
            joinedload(Bill.participants).joinedload(BillParticipant.debtor_member_profile),
        )
        .filter(Bill.group_id == group_id)
    )
    if not include_archived:
        q = q.filter(Bill.is_archived == False)  # noqa: E712
    return q.order_by(Bill.created_at.desc()).all()


def settle_participants(
    db: Session,
    *,
    group_id: str,
    bill_id: int,
    debtor_names: List[str],
    actor_line_user_id: Optional[str] = None,
    require_payer: bool = True,
    mention_user_ids: Optional[Dict[str, str]] = None,
) -> Tuple[bool, str, dict]:
    """Soft settle：標記 is_paid=True。可用名稱或 mention 對應的 userId 找人。"""
    mention_user_ids = mention_user_ids or {}
    bill = get_bill_by_id(db, bill_id, group_id)
    if not bill:
        return False, f"找不到帳單 B-{bill_id}。", {}

    if require_payer:
        if (
            not bill.payer_member_profile.line_user_id
            or bill.payer_member_profile.line_user_id != actor_line_user_id
        ):
            return (
                False,
                f"只有付款人 @{bill.payer_member_profile.name} 才能執行結帳。",
                {},
            )

    name_set = {n.strip() for n in debtor_names if n.strip()}
    if not name_set:
        return False, "請指定要結算的參與人。", {}

    # 也收集對應的 userId，方便對到已綁定成員
    target_user_ids = {mention_user_ids[n] for n in name_set if n in mention_user_ids}

    settled = []
    settled_amount = Decimal(0)
    for bp in bill.participants:
        m = bp.debtor_member_profile
        matched = m.name in name_set or (
            m.line_user_id and m.line_user_id in target_user_ids
        )
        if matched and not bp.is_paid:
            bp.is_paid = True
            bp.paid_at = datetime.now(timezone.utc)
            settled.append(m.name)
            settled_amount += bp.amount_owed

    found = set(settled) | {
        bp.debtor_member_profile.name
        for bp in bill.participants
        if bp.is_paid
        and (
            bp.debtor_member_profile.name in name_set
            or (
                bp.debtor_member_profile.line_user_id
                and bp.debtor_member_profile.line_user_id in target_user_ids
            )
        )
    }
    not_found = list(name_set - found)
    if not settled and not_found:
        return False, f"找不到參與人: {', '.join('@' + n for n in not_found)}", {}
    if not settled:
        return False, "指定的參與人皆已結清或不存在。", {}

    unpaid_left = [bp for bp in bill.participants if not bp.is_paid]
    if not unpaid_left:
        bill.is_archived = True

    db.commit()
    return (
        True,
        "ok",
        {
            "settled": settled,
            "settled_amount": settled_amount,
            "remaining_unpaid": len(unpaid_left),
            "archived": bill.is_archived,
            "bill_id": bill.id,
            "description": bill.description,
        },
    )


def delete_bill(db: Session, group_id: str, bill_id: int) -> Tuple[bool, str]:
    bill = get_bill_by_id(db, bill_id, group_id)
    if not bill:
        return False, f"找不到帳單 B-{bill_id}。"
    db.delete(bill)
    db.commit()
    return True, f"已刪除 B-{bill_id} {bill.description}"


def settle_bills_fully(
    db: Session, group_id: str, bill_ids: List[int]
) -> Tuple[bool, str, dict]:
    """將指定帳單的所有未付參與者標記已付（並可封存）。"""
    if not bill_ids:
        return False, "請至少勾選一筆帳單。", {}
    settled_bills = []
    total = Decimal(0)
    for bill_id in bill_ids:
        bill = get_bill_by_id(db, bill_id, group_id)
        if not bill or bill.is_archived:
            continue
        changed = False
        for bp in bill.participants:
            if not bp.is_paid:
                bp.is_paid = True
                bp.paid_at = datetime.now(timezone.utc)
                total += bp.amount_owed
                changed = True
        if changed:
            bill.is_archived = True
            settled_bills.append(bill.id)
    if not settled_bills:
        return False, "勾選的帳單沒有可結清的未付項目。", {}
    db.commit()
    return (
        True,
        "ok",
        {"settled_bill_ids": settled_bills, "settled_amount": total},
    )


def bill_to_dict(bill: Bill) -> dict:
    unpaid = [p for p in bill.participants if not p.is_paid]
    paid = [p for p in bill.participants if p.is_paid]
    return {
        "id": bill.id,
        "description": bill.description,
        "total_amount": str(bill.total_bill_amount),
        "split_type": bill.split_type.value if bill.split_type else None,
        "split_type_label": "均攤" if bill.split_type == SplitType.EQUAL else "分別計算",
        "payer": bill.payer_member_profile.name if bill.payer_member_profile else None,
        "payer_line_user_id": (
            bill.payer_member_profile.line_user_id if bill.payer_member_profile else None
        ),
        "is_archived": bill.is_archived,
        "created_at": bill.created_at.isoformat() if bill.created_at else None,
        "participants": [
            {
                "name": p.debtor_member_profile.name,
                "line_user_id": p.debtor_member_profile.line_user_id,
                "amount": str(p.amount_owed),
                "is_paid": p.is_paid,
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            }
            for p in bill.participants
        ],
        "unpaid_count": len(unpaid),
        "paid_count": len(paid),
        "unpaid_total": str(sum((p.amount_owed for p in unpaid), Decimal(0))),
    }
