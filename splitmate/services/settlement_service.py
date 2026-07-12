from __future__ import annotations

from decimal import Decimal
from typing import List

from sqlalchemy.orm import Session, joinedload

from models import Bill, BillParticipant
from splitmate.services.split_engine import compute_net_edges


def unpaid_participations(db: Session, group_id: str) -> List[BillParticipant]:
    return (
        db.query(BillParticipant)
        .options(
            joinedload(BillParticipant.debtor_member_profile),
            joinedload(BillParticipant.bill).joinedload(Bill.payer_member_profile),
        )
        .join(Bill)
        .filter(
            Bill.group_id == group_id,
            Bill.is_archived == False,  # noqa: E712
            BillParticipant.is_paid == False,  # noqa: E712
        )
        .all()
    )


def build_debt_matrix(participations: List[BillParticipant]) -> dict:
    matrix: dict = {}
    for p in participations:
        debtor = p.debtor_member_profile.name
        creditor = p.bill.payer_member_profile.name
        matrix.setdefault(debtor, {})
        matrix[debtor][creditor] = matrix[debtor].get(creditor, Decimal(0)) + p.amount_owed
    return matrix


def group_settlement(db: Session, group_id: str) -> dict:
    rows = unpaid_participations(db, group_id)
    if not rows:
        return {
            "cleared": True,
            "edges": [],
            "raw_debts": [],
            "total_outstanding": "0",
            "unpaid_count": 0,
        }

    matrix = build_debt_matrix(rows)
    edges = compute_net_edges(matrix)
    raw = []
    for p in rows:
        raw.append(
            {
                "from": p.debtor_member_profile.name,
                "to": p.bill.payer_member_profile.name,
                "amount": str(p.amount_owed),
                "bill_id": p.bill_id,
                "description": p.bill.description,
            }
        )
    total = sum((p.amount_owed for p in rows), Decimal(0))
    return {
        "cleared": len(edges) == 0,
        "edges": [{"from": e["from"], "to": e["to"], "amount": str(e["amount"])} for e in edges],
        "raw_debts": raw,
        "total_outstanding": str(total),
        "unpaid_count": len(rows),
    }


def group_summary(db: Session, group_id: str) -> dict:
    bills = (
        db.query(Bill)
        .options(joinedload(Bill.participants))
        .filter(Bill.group_id == group_id)
        .all()
    )
    active = [b for b in bills if not b.is_archived]
    unpaid_n = 0
    unpaid_amt = Decimal(0)
    for b in active:
        for p in b.participants:
            if not p.is_paid:
                unpaid_n += 1
                unpaid_amt += p.amount_owed
    total_spend = sum((b.total_bill_amount for b in bills), Decimal(0))
    return {
        "bill_count": len(bills),
        "active_bill_count": len(active),
        "unpaid_participant_count": unpaid_n,
        "unpaid_amount": str(unpaid_amt),
        "total_spend": str(total_spend),
    }
