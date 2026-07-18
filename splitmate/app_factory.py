from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from flask import Flask, jsonify, request

from models import get_db, init_db, init_engine
from splitmate.api.v1 import api_bp
from splitmate.config import Config
from splitmate.services.seed import ensure_demo_group
from splitmate.web.routes import web_bp

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
APP_VERSION = "0.1.0"

_db_lock = threading.Lock()
_db_ready = False


def _sqlite_fallback_url() -> str:
    if os.name == "nt":
        return "sqlite:///./splitmate.db"
    return "sqlite:////tmp/splitmate.db"


def _init_database() -> None:
    """初始化資料庫；失敗時退回 SQLite，避免整個服務起不來。"""
    primary = Config.DATABASE_URL
    try:
        logger.info("Connecting database…")
        init_engine(primary)
        init_db()
        return
    except Exception:
        logger.exception("資料庫初始化失敗（%s），改用 SQLite fallback", primary)

    fallback = _sqlite_fallback_url()
    init_engine(fallback)
    init_db()


def _ensure_database() -> None:
    global _db_ready
    if _db_ready:
        return
    with _db_lock:
        if _db_ready:
            return
        _init_database()
        if Config.DEMO_MODE:
            try:
                with get_db() as db:
                    ensure_demo_group(db)
            except Exception:
                logger.exception("Demo seed failed")
        _db_ready = True


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    app.config["SECRET_KEY"] = Config.SECRET_KEY

    # /health 不依賴 DB，讓 Railway healthcheck 能立刻通過
    @app.get("/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "service": "splitmate",
                "version": APP_VERSION,
                "line_enabled": Config.line_enabled(),
                "demo_mode": Config.DEMO_MODE,
            }
        )

    @app.before_request
    def _bootstrap_db():
        if request.path == "/health":
            return None
        _ensure_database()
        return None

    app.register_blueprint(api_bp)
    app.register_blueprint(web_bp)

    if Config.line_enabled():
        from linebot import LineBotApi, WebhookHandler

        from splitmate.line.bot import line_bp, register_line_handlers

        line_bot_api = LineBotApi(Config.LINE_CHANNEL_ACCESS_TOKEN)
        handler = WebhookHandler(Config.LINE_CHANNEL_SECRET)
        app.extensions["line_bot_api"] = line_bot_api
        app.extensions["line_handler"] = handler
        register_line_handlers(handler)
        app.register_blueprint(line_bp)
        logger.info("LINE Bot enabled")
    else:
        logger.warning("未設定 LINE Token — 目前為 Web/API only 模式")

    return app
