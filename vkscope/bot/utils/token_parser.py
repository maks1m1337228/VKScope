"""Разбор access_token из текста или URL (пользователь может вставить всю строку браузера)."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse


def extract_access_token(raw: str) -> str | None:
    """
    Принимает:
    - голый токен vk1.a....
    - access_token=...&expires_in=...
    - полный URL https://oauth.vk.com/blank.html#access_token=...
    """
    text = (raw or "").strip()
    if not text:
        return None

    # URL с hash (#access_token=...)
    if "access_token=" in text and ("http://" in text or "https://" in text or text.startswith("oauth.vk.com")):
        if not text.startswith("http"):
            text = "https://" + text.lstrip("/")
        parsed = urlparse(text)
        fragment = parsed.fragment or parsed.query
        if fragment:
            params = parse_qs(fragment)
            token = params.get("access_token", [None])[0]
            if token:
                return token

    if text.lower().startswith("access_token="):
        text = text.split("=", 1)[1]

    if "&" in text:
        text = text.split("&", 1)[0]

    text = text.strip()

    # VK user token
    if re.fullmatch(r"vk1\.a\.[A-Za-z0-9_\-]+", text):
        return text

    if len(text) >= 50 and text.startswith("vk1."):
        return text

    return None
