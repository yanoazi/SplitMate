from __future__ import annotations

import logging
from pathlib import Path

from flask import Flask, jsonify

from models import get_db, init_db, init_engine
from splitmate.api.v1 import api_bp
from splitmate.config import Config
from splitmate.services.seed import ensure_demo_group
from splitmate.web.routes import web_bp

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
APP_VERSION = "0.1.0"


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    app.config["SECRET_KEY"] = Config.SECRET_KEY

    init_engine(Config.DATABASE_URL)
    init_db()

    if Config.DEMO_MODE:
        try:
            with get_db() as db:
                ensure_demo_group(db)
        except Exception:
            logger.exception("Demo seed failed")

    app.register_blueprint(api_bp)
    app.register_blueprint(web_bp)

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
