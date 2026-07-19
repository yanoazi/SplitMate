from decimal import Decimal, ROUND_UP, InvalidOperation
from typing import Dict, List, Optional, Tuple

from models import SplitType


def parse_participant_input(
    participants_str: str,
    total_bill_amount: Decimal,
    payer_mention_name: str,
) -> Tuple[Optional[List[Tuple[str, Decimal]]], Optional[SplitType], Optional[str], Decimal]:
    """解析 @提及，回傳 (欠款人清單, 分攤類型, 錯誤, 付款人自己應負擔金額)。"""
    import re

    participants_to_charge: List[Tuple[str, Decimal]] = []
    raw_mentions = re.findall(r"@(\S+)(?:\s+([\d\.]+))?", participants_str)
    if not raw_mentions:
        return None, None, "請至少 @提及一位參與的成員。", Decimal(0)

    has_any_amount = any(amount_str for _, amount_str in raw_mentions)
    seen = set()
    other_participants = []

    for name, amount_str in raw_mentions:
        name = name.strip()
        if name in seen:
            return None, None, f"參與人 @{name} 被重複提及。", Decimal(0)
        seen.add(name)
        if name == payer_mention_name:
            continue
        other_participants.append((name, amount_str))

    if not other_participants:
        return None, None, "請 @提及其他需要分攤的成員（付款人會自動參與分攤計算）。", Decimal(0)

    if has_any_amount:
        split_type = SplitType.UNEQUAL
        others_total = Decimal(0)
        for name, amount_str in other_participants:
            if not amount_str:
                return (
                    None,
                    None,
                    f"分別計算模式下，@{name} 未指定金額。",
                    Decimal(0),
                )
            try:
                amount = Decimal(amount_str)
                if amount <= 0:
                    return None, None, f"@{name} 的金額必須大於 0。", Decimal(0)
                others_total += amount
                participants_to_charge.append((name, amount))
            except InvalidOperation:
                return None, None, f"@{name} 的金額格式無效。", Decimal(0)
        payer_share = total_bill_amount - others_total
        if payer_share < 0:
            return (
                None,
                None,
                f"其他人的金額總和 ({others_total}) 超過總金額 ({total_bill_amount})。",
                Decimal(0),
            )
    else:
        split_type = SplitType.EQUAL
        n = len(other_participants) + 1
        share = (total_bill_amount / Decimal(n)).quantize(Decimal("1"), rounding=ROUND_UP)
        others_total = share * Decimal(len(other_participants))
        payer_share = total_bill_amount - others_total
        for name, _ in other_participants:
            participants_to_charge.append((name, share))

    return participants_to_charge, split_type, None, payer_share


def compute_net_balances(debt_matrix: Dict[str, Dict[str, Decimal]]) -> Dict[str, Decimal]:
    """每人淨額：正＝應收款，負＝應付款。"""
    balances: Dict[str, Decimal] = {}
    for debtor, creditors in debt_matrix.items():
        for creditor, amount in creditors.items():
            if amount == 0:
                continue
            balances[debtor] = balances.get(debtor, Decimal(0)) - amount
            balances[creditor] = balances.get(creditor, Decimal(0)) + amount
    return balances


def compute_net_edges(debt_matrix: Dict[str, Dict[str, Decimal]]) -> List[dict]:
    """雙向抵消後的 pairwise 淨欠款邊（非最少轉帳）。"""
    members = set()
    for debtor, creditors in debt_matrix.items():
        members.add(debtor)
        members.update(creditors.keys())

    edges = []
    ordered = sorted(members)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1 :]:
            a_to_b = debt_matrix.get(a, {}).get(b, Decimal(0))
            b_to_a = debt_matrix.get(b, {}).get(a, Decimal(0))
            net = a_to_b - b_to_a
            if net > 0:
                edges.append({"from": a, "to": b, "amount": net})
            elif net < 0:
                edges.append({"from": b, "to": a, "amount": -net})
    edges.sort(key=lambda e: e["amount"], reverse=True)
    return edges


def compute_min_transfers(debt_matrix: Dict[str, Dict[str, Decimal]]) -> List[dict]:
    """最少轉帳次數：由淨額貪婪配對「該付的人 → 該收的人」。

    在金額可任意分割的前提下，轉帳筆數上限為 max(債務人數, 債權人數)，
    且為結清淨額所需的最少筆數之一。
    """
    balances = compute_net_balances(debt_matrix)
    # 使用 list 以便就地更新剩餘額
    debtors = [[n, -b] for n, b in balances.items() if b < 0]
    creditors = [[n, b] for n, b in balances.items() if b > 0]
    debtors.sort(key=lambda x: x[1], reverse=True)
    creditors.sort(key=lambda x: x[1], reverse=True)

    transfers: List[dict] = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        d_name, d_amt = debtors[i]
        c_name, c_amt = creditors[j]
        pay = min(d_amt, c_amt)
        if pay > 0:
            transfers.append({"from": d_name, "to": c_name, "amount": pay})
        d_amt -= pay
        c_amt -= pay
        debtors[i][1] = d_amt
        creditors[j][1] = c_amt
        if d_amt == 0:
            i += 1
        if c_amt == 0:
            j += 1

    transfers.sort(key=lambda e: e["amount"], reverse=True)
    return transfers
