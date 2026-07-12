import os
from dotenv import load_dotenv

load_dotenv()


def _normalize_db_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


class Config:
    DATABASE_URL = _normalize_db_url(
        os.environ.get("DATABASE_URL") or "sqlite:///./splitmate.db"
    )
    LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
    # 公開的 Web 根網址，例如 https://your-app.railway.app（不要結尾斜線）
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:7777").rstrip("/")
    DEMO_MODE = os.environ.get("DEMO_MODE", "1").lower() in ("1", "true", "yes")
    DEMO_TOKEN = os.environ.get("DEMO_TOKEN", "demo")
    DEMO_EDIT_PIN = os.environ.get("DEMO_EDIT_PIN", "1234")
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-splitmate-change-me")

    @classmethod
    def line_enabled(cls) -> bool:
        return bool(cls.LINE_CHANNEL_ACCESS_TOKEN and cls.LINE_CHANNEL_SECRET)

    @classmethod
    def group_web_url(cls, public_token: str) -> str:
        return f"{cls.PUBLIC_BASE_URL}/g/{public_token}"
