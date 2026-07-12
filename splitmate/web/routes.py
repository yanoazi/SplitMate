from flask import Blueprint, render_template, redirect, url_for

from models import get_db
from splitmate.config import Config
from splitmate.services.group_service import get_group_by_token
from splitmate.services.seed import ensure_demo_group

web_bp = Blueprint("web", __name__)


@web_bp.get("/")
def index():
    return render_template(
        "index.html",
        demo_url=Config.group_web_url(Config.DEMO_TOKEN),
        line_enabled=Config.line_enabled(),
    )


@web_bp.get("/demo")
def demo_redirect():
    with get_db() as db:
        ensure_demo_group(db)
    return redirect(url_for("web.dashboard", token=Config.DEMO_TOKEN))


@web_bp.get("/g/<token>")
def dashboard(token: str):
    with get_db() as db:
        if token == Config.DEMO_TOKEN:
            ensure_demo_group(db)
        group = get_group_by_token(db, token)
        if not group:
            return render_template("not_found.html", token=token), 404
        return render_template(
            "dashboard.html",
            group_name=group.name,
            token=group.public_token,
            is_demo=group.is_demo,
            public_base_url=Config.PUBLIC_BASE_URL,
        )
