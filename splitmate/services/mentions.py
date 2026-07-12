"""從 LINE 訊息解析 @提及，盡量取得真實 userId。"""
from __future__ import annotations

import logging
import re
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def extract_mention_user_ids(event_message) -> Dict[str, str]:
    """
    回傳 {顯示名稱: LINE userId}。

    只有使用者用 LINE 的「點選 @某人」提及時，Webhook 才會帶 userId。
    若只是手動打字 @小美，通常拿不到 ID。
    """
    mapping: Dict[str, str] = {}
    text = getattr(event_message, "text", "") or ""
    mention = getattr(event_message, "mention", None)
    if not mention:
        return mapping

    mentionees = getattr(mention, "mentionees", None) or []
    for item in mentionees:
        user_id = getattr(item, "user_id", None)
        if not user_id:
            continue
        index = getattr(item, "index", None)
        length = getattr(item, "length", None)
        if index is None or length is None:
            continue
        try:
            raw = text[int(index) : int(index) + int(length)]
        except Exception:
            continue
        name = raw.lstrip("@").strip()
        if name:
            mapping[name] = user_id
            logger.info("Mention bound: @%s -> %s", name, user_id)
    return mapping


def parse_at_names(text_fragment: str) -> list[str]:
    return [n.strip() for n in re.findall(r"@(\S+)", text_fragment) if n.strip()]


def resolve_member_key(
    display_name: str, mention_ids: Optional[Dict[str, str]]
) -> tuple[str, Optional[str]]:
    """回傳 (顯示名稱, line_user_id or None)。"""
    mention_ids = mention_ids or {}
    return display_name, mention_ids.get(display_name)
