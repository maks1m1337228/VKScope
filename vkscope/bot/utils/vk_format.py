"""Форматирование текста для сообщений VK."""

from __future__ import annotations

from bot.utils.vk_api_client import VKUserInfo


def format_friend_mentions(users: list[VKUserInfo]) -> str:
    """Имена друзей как кликабельные ссылки [id123|Иван Иванов]."""
    parts: list[str] = []
    for user in users:
        name = f"{user.first_name} {user.last_name}".strip()
        if not name:
            name = f"id{user.vk_user_id}"
        parts.append(f"[id{user.vk_user_id}|{name}]")
    return ", ".join(parts)
