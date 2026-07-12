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
        text = "#新增支出 100 測 @小美"
        mention = None

    assert extract_mention_user_ids(Msg()) == {}
