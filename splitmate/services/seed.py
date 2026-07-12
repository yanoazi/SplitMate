"""Demo 群組假資料，方便公開試用 Web（無需 LINE）。"""
from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy.orm import Session

from models import (
    Bill,
    BillParticipant,
    ExpenseGroup,
    GroupMember,
    SplitType,
    generate_content_hash,
)
from splitmate.config import Config

logger = logging.getLogger(__name__)

DEMO_LINE_GROUP_ID = "demo-public-group"


def ensure_demo_group(db: Session) -> ExpenseGroup:
    group = (
        db.query(ExpenseGroup)
        .filter(ExpenseGroup.public_token == Config.DEMO_TOKEN)
        .first()
    )
    if group:
        return group

    group = ExpenseGroup(
        line_group_id=DEMO_LINE_GROUP_ID,
        name="Demo 聚餐群組",
        public_token=Config.DEMO_TOKEN,
        edit_pin=Config.DEMO_EDIT_PIN,
        is_demo=True,
    )
    db.add(group)
    db.flush()

    existing = db.query(Bill).filter(Bill.group_id == DEMO_LINE_GROUP_ID).count()
    if existing:
        db.commit()
        return group

    def member(name: str, line_id: str | None = None) -> GroupMember:
        m = GroupMember(name=name, group_id=DEMO_LINE_GROUP_ID, line_user_id=line_id)
        db.add(m)
        db.flush()
        return m

    alice = member("小美", "demo-alice")
    bob = member("小王", "demo-bob")
    carol = member("阿明", "demo-carol")

    def add_bill(payer, desc, total, split_type, debts: list[tuple[GroupMember, Decimal]]):
        participants_str = " ".join(f"@{m.name} {amt}" for m, amt in debts)
        content_hash = generate_content_hash(
            payer_id=payer.id,
            description=desc,
            amount=str(total),
            participants_str=participants_str,
            group_id=DEMO_LINE_GROUP_ID,
        )
        bill = Bill(
            group_id=DEMO_LINE_GROUP_ID,
            description=desc,
            total_bill_amount=total,
            payer_member_id=payer.id,
            split_type=split_type,
            content_hash=content_hash,
            is_archived=False,
        )
        db.add(bill)
        db.flush()
        for m, amt in debts:
            db.add(
                BillParticipant(
                    bill_id=bill.id,
                    debtor_member_id=m.id,
                    amount_owed=amt,
                    is_paid=False,
                )
            )

    add_bill(
        alice,
        "週末火鍋",
        Decimal("900"),
        SplitType.EQUAL,
        [(bob, Decimal("300")), (carol, Decimal("300"))],
    )
    add_bill(
        bob,
        "計程車",
        Decimal("450"),
        SplitType.UNEQUAL,
        [(alice, Decimal("150")), (carol, Decimal("150"))],
    )
    add_bill(
        carol,
        "代買飲料",
        Decimal("200"),
        SplitType.UNEQUAL,
        [(alice, Decimal("100")), (bob, Decimal("100"))],
    )

    db.commit()
    logger.info("Demo 群組已建立 token=%s pin=%s", Config.DEMO_TOKEN, Config.DEMO_EDIT_PIN)
    return group
