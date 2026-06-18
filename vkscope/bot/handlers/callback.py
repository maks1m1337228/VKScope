"""Пагинация рекомендаций и прочие callback-кнопки."""

from vkbottle import GroupEventType
from vkbottle.bot import BotLabeler, MessageEvent

from bot.app import get_bot
from bot.handlers.recommendations_page import CAROUSEL_PAGE_SIZE, send_recommendations_page
from bot.keyboards.carousel_builder import group_public_url, payload_to_dict
from bot.states.user_states import UserStates
from loguru import logger

labeler = BotLabeler()


@labeler.raw_event(GroupEventType.MESSAGE_EVENT, MessageEvent)
async def carousel_callback_handler(event: MessageEvent) -> None:
    payload = payload_to_dict(event.payload)
    action = payload.get("action")

    if action == "open_group":
        group_id = int(payload.get("group_id", 0))
        if group_id:
            await event.show_snackbar("Открываю…")
            await event.send_message(f"🔗 {group_public_url(group_id)}")
        return

    if action != "more_recommendations":
        return

    await event.show_snackbar("Загружаю…")

    session_id = int(payload.get("session_id", 0))
    offset = int(payload.get("offset", 0))
    if not session_id:
        await event.show_snackbar("Сессия не найдена")
        return

    try:
        next_offset = await send_recommendations_page(
            event.peer_id,
            session_id,
            offset,
            event.send_message,
        )
        if next_offset is not None:
            state = await get_bot().state_dispenser.get(event.peer_id)
            fsm_payload = state.payload if state else {}
            await get_bot().state_dispenser.set(
                event.peer_id,
                UserStates.READY_TO_ANALYZE,
                access_token=fsm_payload.get("access_token"),
                last_session_id=session_id,
                carousel_offset=next_offset,
            )
        await event.show_snackbar("Готово")
    except Exception as exc:
        logger.exception("Ошибка callback пагинации: {}", exc)
        await event.show_snackbar("Ошибка загрузки")
