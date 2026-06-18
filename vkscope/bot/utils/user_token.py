"""Сохранение user access_token для конкретного vk_user_id."""

from __future__ import annotations

from bot.app import get_bot
from bot.states.user_states import UserStates
from bot.utils.vk_api_client import VKAPIClient, VKAPIError, VKNetworkError
from database import async_session_factory
from database import crud

TOKEN_IP_BINDING_MSG = (
    "Токен привязан к другому IP (VPN или другая сеть).\n\n"
    "/logout → «Начать анализ» → «Вход (+ группы)» на том же ПК и с той же сетью, что и бот."
)


def is_token_ip_binding_error(exc: VKAPIError) -> bool:
    return exc.code == 5 and "another ip" in exc.message.lower()


async def validate_access_token(access_token: str) -> tuple[int, VKAPIError | VKNetworkError | None]:
    """Проверка токена через users.get; возвращает owner_id и ошибку, если есть."""
    client = VKAPIClient(access_token=access_token)
    try:
        return await client.get_token_owner_id(), None
    except (VKAPIError, VKNetworkError) as exc:
        return 0, exc
    finally:
        await client.close()


async def clear_user_token(vk_user_id: int, peer_id: int) -> None:
    async with async_session_factory() as session:
        await crud.clear_user_access_token(session, vk_user_id)
    await get_bot().state_dispenser.delete(peer_id)


async def persist_user_token(vk_user_id: int, peer_id: int, access_token: str) -> None:
    """PostgreSQL + FSM — отдельный токен на каждого пользователя бота."""
    async with async_session_factory() as session:
        await crud.get_or_create_user(session, vk_user_id=vk_user_id)
        await crud.save_user_access_token(session, vk_user_id, access_token)

    await get_bot().state_dispenser.set(
        peer_id,
        UserStates.READY_TO_ANALYZE,
        access_token=access_token,
    )
