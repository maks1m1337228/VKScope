"""Получение user access_token: память FSM → PostgreSQL → демо-токен из .env."""

from __future__ import annotations

from vkbottle.bot import Message

from bot.app import get_bot
from config import settings
from database import async_session_factory
from database import crud


async def get_access_token(message: Message) -> str | None:
    """Токен из FSM, затем из БД (отдельно для каждого vk_user_id)."""
    state_peer = await get_bot().state_dispenser.get(message.peer_id)
    if state_peer and state_peer.payload.get("access_token"):
        return str(state_peer.payload["access_token"])

    async with async_session_factory() as session:
        return await crud.get_user_access_token(session, message.from_id)


def get_demo_token() -> str | None:
    token = (settings.demo_user_token or "").strip()
    return token or None
