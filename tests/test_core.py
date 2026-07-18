import os
import sys
from decimal import Decimal

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DEMO_MODE", "0")


def test_equal_split_sums_to_total():
    from splitmate.services.split_engine import parse_participant_input

    charged, split_type, err, payer_share = parse_participant_input(
        "@小美 @小王", Decimal("300"), "我"
    )
    assert err is None
    assert split_type.value == "equal"
    assert sum(a for _, a in charged) + payer_share == Decimal("300")


def test_unequal_payer_remainder():
    from splitmate.services.split_engine import parse_participant_input

    charged, split_type, err, payer_share = parse_participant_input(
        "@小美 400 @小王 350", Decimal("1000"), "我"
    )
    assert err is None
    assert payer_share == Decimal("250")


def test_net_edges_offset():
    from splitmate.services.split_engine import compute_net_edges

    matrix = {
        "A": {"B": Decimal("100")},
        "B": {"A": Decimal("40")},
    }
    edges = compute_net_edges(matrix)
    assert edges[0]["amount"] == Decimal("60")


def test_create_app_health():
    from splitmate.app_factory import create_app

    app = create_app()
    client = app.test_client()
    res = client.get("/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["service"] == "splitmate"
    assert data["version"] == "0.1.0"


def test_mention_extract_empty():
    from splitmate.services.mentions import extract_mention_user_ids

    class Msg:
        text = "#分帳 100 測 @小美"
        mention = None

    assert extract_mention_user_ids(Msg()) == {}


def test_merge_member_binds_line_id():
    from models import GroupMember, get_db, init_db, init_engine
    from splitmate.services.group_service import merge_member_to_line_id

    init_engine("sqlite:///:memory:")
    init_db()
    with get_db() as db:
        db.add(GroupMember(name="訪客小美", group_id="g1", line_user_id=None))
        db.commit()

        ok, merge_msg = merge_member_to_line_id(
            db,
            group_id="g1",
            old_name="訪客小美",
            line_user_id="U_real_1",
            display_name="小美",
        )
        assert ok
        bound = (
            db.query(GroupMember)
            .filter(GroupMember.group_id == "g1", GroupMember.line_user_id == "U_real_1")
            .first()
        )
        assert bound is not None
        assert "綁定" in merge_msg or "合併" in merge_msg


def test_batch_settlement_filters_bills():
    from models import (
        Bill,
        BillParticipant,
        GroupMember,
        SplitType,
        get_db,
        init_db,
        init_engine,
    )
    from splitmate.services.settlement_service import group_settlement

    init_engine("sqlite:///:memory:")
    init_db()
    with get_db() as db:
        payer = GroupMember(name="甲", group_id="g1", line_user_id="Ua")
        b_member = GroupMember(name="乙", group_id="g1", line_user_id="Ub")
        c_member = GroupMember(name="丙", group_id="g1", line_user_id="Uc")
        db.add_all([payer, b_member, c_member])
        db.flush()

        bill1 = Bill(
            group_id="g1",
            description="午餐",
            total_bill_amount=Decimal("100"),
            payer_member_id=payer.id,
            split_type=SplitType.EQUAL,
            content_hash="h1",
        )
        bill2 = Bill(
            group_id="g1",
            description="晚餐",
            total_bill_amount=Decimal("200"),
            payer_member_id=b_member.id,
            split_type=SplitType.EQUAL,
            content_hash="h2",
        )
        db.add_all([bill1, bill2])
        db.flush()
        db.add_all(
            [
                BillParticipant(
                    bill_id=bill1.id, debtor_member_id=b_member.id, amount_owed=Decimal("50")
                ),
                BillParticipant(
                    bill_id=bill2.id, debtor_member_id=payer.id, amount_owed=Decimal("80")
                ),
                BillParticipant(
                    bill_id=bill2.id, debtor_member_id=c_member.id, amount_owed=Decimal("80")
                ),
            ]
        )
        db.commit()

        only_first = group_settlement(db, "g1", bill_ids=[bill1.id])
        assert only_first["matched_bill_ids"] == [bill1.id]
        assert len(only_first["edges"]) == 1
        assert only_first["edges"][0]["from"] == "乙"
        assert only_first["edges"][0]["to"] == "甲"
