from __future__ import annotations

from flask import Blueprint, jsonify, request

from models import get_bill_by_id, get_db
from splitmate.config import Config
from splitmate.services import bill_service, group_service, settlement_service
from splitmate.services.seed import ensure_demo_group

api_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")


def _group_or_404(db, token: str):
    group = group_service.get_group_by_token(db, token)
    if not group:
        return None, (jsonify({"error": "找不到此群組連結"}), 404)
    return group, None


@api_bp.get("/health")
def api_health():
    return jsonify({"status": "ok", "service": "splitmate", "version": "0.1.0"})


@api_bp.get("/demo")
def api_demo():
    with get_db() as db:
        group = ensure_demo_group(db)
        return jsonify(
            {
                "token": group.public_token,
                "name": group.name,
                "web_url": Config.group_web_url(group.public_token),
                "edit_pin_hint": "見 DEMO_EDIT_PIN（預設 1234）" if group.is_demo else None,
            }
        )


@api_bp.get("/groups/<token>/summary")
def api_summary(token: str):
    with get_db() as db:
        group, err = _group_or_404(db, token)
        if err:
            return err
        summary = settlement_service.group_summary(db, group.line_group_id)
        return jsonify(
            {
                "group": {
                    "name": group.name,
                    "token": group.public_token,
                    "is_demo": group.is_demo,
                    "web_url": Config.group_web_url(group.public_token),
                },
                "summary": summary,
            }
        )


@api_bp.get("/groups/<token>/bills")
def api_bills(token: str):
    include_archived = request.args.get("include_archived", "1") == "1"
    with get_db() as db:
        group, err = _group_or_404(db, token)
        if err:
            return err
        bills = bill_service.list_bills(
            db, group.line_group_id, include_archived=include_archived
        )
        return jsonify({"bills": [bill_service.bill_to_dict(b) for b in bills]})


@api_bp.get("/groups/<token>/bills/<int:bill_id>")
def api_bill_detail(token: str, bill_id: int):
    with get_db() as db:
        group, err = _group_or_404(db, token)
        if err:
            return err
        bill = get_bill_by_id(db, bill_id, group.line_group_id)
        if not bill:
            return jsonify({"error": "找不到帳單"}), 404
        return jsonify({"bill": bill_service.bill_to_dict(bill)})


@api_bp.get("/groups/<token>/settlement")
def api_settlement(token: str):
    with get_db() as db:
        group, err = _group_or_404(db, token)
        if err:
            return err
        data = settlement_service.group_settlement(db, group.line_group_id)
        return jsonify(data)


@api_bp.get("/groups/<token>/members")
def api_members(token: str):
    with get_db() as db:
        group, err = _group_or_404(db, token)
        if err:
            return err
        from models import list_group_members

        members = list_group_members(db, group.line_group_id)
        return jsonify(
            {
                "members": [
                    {
                        "name": m.name,
                        "line_user_id": m.line_user_id,
                        "bound": bool(m.line_user_id),
                    }
                    for m in members
                ]
            }
        )


@api_bp.post("/groups/<token>/bills/<int:bill_id>/settle")
def api_settle(token: str, bill_id: int):
    body = request.get_json(silent=True) or {}
    pin = body.get("edit_pin") or request.headers.get("X-Edit-Pin")
    names = body.get("debtor_names") or []
    if isinstance(names, str):
        names = [names]

    with get_db() as db:
        group, err = _group_or_404(db, token)
        if err:
            return err
        if not group_service.verify_edit_pin(group, pin):
            return jsonify({"error": "編輯 PIN 錯誤"}), 403
        ok, msg, meta = bill_service.settle_participants(
            db,
            group_id=group.line_group_id,
            bill_id=bill_id,
            debtor_names=names,
            require_payer=False,
        )
        if not ok:
            return jsonify({"error": msg}), 400
        out = dict(meta)
        if "settled_amount" in out:
            out["settled_amount"] = str(out["settled_amount"])
        return jsonify({"ok": True, "message": msg, "result": out})
