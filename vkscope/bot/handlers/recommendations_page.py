"""Загрузка и отправка страницы рекомендаций (карусель + кнопка «Ещё»)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from vkbottle import VKAPIError as BottleVKAPIError

from bot.keyboards.carousel_builder import (
    build_carousel,
    build_more_recommendations_keyboard,
)
from bot.utils.carousel_photos import attach_carousel_photos
from bot.utils.vk_api_client import VKAPIClient
from config import settings
from database import async_session_factory
from database import crud
from loguru import logger

CAROUSEL_PAGE_SIZE = 5
MORE_BUTTON_TEXTS = ["Ещё рекомендации →", "Ещё →"]

SendFn = Callable[..., Awaitable[None]]


async def send_recommendations_page(
    peer_id: int,
    session_id: int,
    offset: int,
    send_text: SendFn,
    *,
    title_prefix: str = "Рекомендации",
) -> int | None:
    """
    Отправляет карусель для offset. Возвращает next_offset для FSM или None, если страниц нет.
    """
    async with async_session_factory() as db_session:
        analysis = await crud.get_analysis_session(db_session, session_id)
        if analysis is None:
            await send_text("Сессия анализа не найдена. Запустите анализ снова.")
            return None

        page = await crud.get_recommendations_page(
            db_session,
            session_id,
            offset=offset,
            limit=CAROUSEL_PAGE_SIZE,
        )
        total = await crud.count_recommendations(db_session, session_id)

    if not page:
        await send_text("Больше рекомендаций нет.")
        return None

    photo_client = VKAPIClient(access_token=settings.vk_group_token)
    try:
        page = await attach_carousel_photos(page, photo_client, peer_id)
        carousel = build_carousel(page)
    finally:
        await photo_client.close()

    caption = f"{title_prefix} ({offset + 1}–{offset + len(page)} из {total}):"
    next_offset = offset + CAROUSEL_PAGE_SIZE

    if carousel:
        try:
            await send_text(caption, template=carousel)
        except BottleVKAPIError as exc:
            if exc.code in (911, 100) and (
                "photo_id" in str(exc).lower() or "different content" in str(exc).lower()
            ):
                for group in page:
                    group.photo_vk_id = ""
                carousel = build_carousel(page)
                await send_text(caption, template=carousel)
            else:
                raise
    else:
        await send_text(f"{caption}\n(карусель пуста)")

    if next_offset < total:
        await send_text(
            "Показать ещё 5 сообществ:",
            keyboard=build_more_recommendations_keyboard(),
        )
        return next_offset

    return next_offset
