from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from models import Bill, BillParticipant, ExpenseGroup, GroupMember, new_edit_pin, new_public_token


def get_group_by_token(db: Session, token: str) -> ExpenseGroup | None:
    return db.query(ExpenseGroup).filter(ExpenseGroup.public_token == token).first()


def get_group_by_line_id(db: Session, line_group_id: str) -> ExpenseGroup | None:
    return db.query(ExpenseGroup).filter(ExpenseGroup.line_group_id == line_group_id).first()


def get_or_create_group_for_line(
    db: Session, line_group_id: str, name: str | None = None
) -> ExpenseGroup:
    group = get_group_by_line_id(db, line_group_id)
    if group:
        if name and group.name != name and group.name in ("未命名群組", line_group_id):
            group.name = name
        return group

    group = ExpenseGroup(
        line_group_id=line_group_id,
        name=name or "LINE 群組",
        public_token=new_public_token(),
        edit_pin=new_edit_pin(),
        is_demo=False,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def verify_edit_pin(group: ExpenseGroup, pin: str | None) -> bool:
    if not pin:
        return False
    return str(pin).strip() == str(group.edit_pin).strip()


def merge_member_to_line_id(
    db: Session,
    *,
    group_id: str,
    old_name: str,
    line_user_id: str,
    display_name: str,
) -> tuple[bool, str]:
    """把「僅名字」的舊紀錄，合併／轉移到真實 LINE userId。"""
    old_name = old_name.strip().lstrip("@")
    display_name = display_name.strip() or old_name
    if not old_name:
        return False, "請指定要合併的舊名字，例如：#合併 小美 @小美"
    if not line_user_id:
        return False, "請用鍵盤「@點選」目標成員，才能取得 LINE ID。"

    old = (
        db.query(GroupMember)
        .filter(GroupMember.group_id == group_id, GroupMember.name == old_name)
        .first()
    )
    if not old:
        return False, f"找不到名為 @{old_name} 的紀錄。可先 #登記 {old_name} 或查看 #成員。"

    target = (
        db.query(GroupMember)
        .filter(
            GroupMember.group_id == group_id,
            GroupMember.line_user_id == line_user_id,
        )
        .first()
    )

    if target and target.id == old.id:
        if display_name and target.name != display_name:
            # 名稱可能被唯一鍵擋住，失敗就只保留 ID
            conflict = (
                db.query(GroupMember)
                .filter(
                    GroupMember.group_id == group_id,
                    GroupMember.name == display_name,
                    GroupMember.id != target.id,
                )
                .first()
            )
            if not conflict:
                target.name = display_name
        db.commit()
        return True, f"@{old_name} 本來就是此 LINE ID，無需合併。"

    if old.line_user_id and old.line_user_id != line_user_id:
        return False, f"@{old_name} 已綁定其他 LINE ID，無法覆蓋。請用 #成員 檢查。"

    if not target:
        # 舊紀錄直接綁上 ID（必要時更新顯示名）
        conflict = (
            db.query(GroupMember)
            .filter(
                GroupMember.group_id == group_id,
                GroupMember.name == display_name,
                GroupMember.id != old.id,
            )
            .first()
        )
        old.line_user_id = line_user_id
        if not conflict and display_name:
            old.name = display_name
        db.commit()
        return True, f"已將 @{old_name} 綁定到 LINE ID（顯示名：@{old.name}）。"

    # 兩筆不同成員：把 old 的帳單／欠款轉到 target，再刪 old
    db.query(Bill).filter(Bill.payer_member_id == old.id).update(
        {Bill.payer_member_id: target.id}, synchronize_session=False
    )
    old_parts = (
        db.query(BillParticipant).filter(BillParticipant.debtor_member_id == old.id).all()
    )
    for bp in old_parts:
        conflict_bp = (
            db.query(BillParticipant)
            .filter(
                BillParticipant.bill_id == bp.bill_id,
                BillParticipant.debtor_member_id == target.id,
            )
            .first()
        )
        if conflict_bp:
            conflict_bp.amount_owed = Decimal(conflict_bp.amount_owed) + Decimal(
                bp.amount_owed
            )
            conflict_bp.is_paid = bool(conflict_bp.is_paid and bp.is_paid)
            if conflict_bp.is_paid and not conflict_bp.paid_at and bp.paid_at:
                conflict_bp.paid_at = bp.paid_at
            db.delete(bp)
        else:
            bp.debtor_member_id = target.id

    if display_name and target.name != display_name:
        name_taken = (
            db.query(GroupMember)
            .filter(
                GroupMember.group_id == group_id,
                GroupMember.name == display_name,
                GroupMember.id != target.id,
            )
            .first()
        )
        if not name_taken:
            target.name = display_name

    db.delete(old)
    db.commit()
    return True, f"已將 @{old_name} 的帳務合併到 @{target.name}（已綁定 LINE ID）。"
