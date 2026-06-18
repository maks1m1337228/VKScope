"""Авторизация VKScope — прямой вход (надёжный) + автовход через ngrok."""

from vkbottle import VKAPIError
from vkbottle.bot import BotLabeler, Message

from bot.app import get_bot
from bot.keyboards.carousel_builder import (
    build_login_keyboard,
    build_run_analysis_keyboard,
    build_start_keyboard,
)
from bot.oauth import get_token as get_oauth_pending_token
from bot.oauth import pop_token as pop_oauth_pending_token
from bot.states.user_states import UserStates
from bot.utils.auth import get_access_token, get_demo_token
from bot.utils.token_parser import extract_access_token
from bot.utils.user_token import (
    TOKEN_IP_BINDING_MSG,
    is_token_ip_binding_error,
    persist_user_token,
    validate_access_token,
)
from bot.utils.vk_api_client import VKAPIClient, VKNetworkError
from config import settings
from database import async_session_factory
from database import crud
from loguru import logger

labeler = BotLabeler()

WELCOME_TEXT = (
    "Добро пожаловать в VKScope!\n"
    "«Анализируем подписки — находим единомышленников»\n\n"
    "Нажмите «Начать анализ»."
)

AUTH_TEXT = (
    "Для анализа нужен доступ к подпискам и друзьям.\n\n"
    "1. Нажмите «Вход (+ группы)» → Разрешить\n"
    "2. Скопируйте адресную строку браузера (там access_token=...)\n"
    "3. Вставьте ссылку сюда одним сообщением\n"
    "4. Нажмите «Запустить анализ»"
)


async def _already_authorized(message: Message) -> bool:
    token = await get_access_token(message)
    if not token:
        return False
    await get_bot().state_dispenser.set(
        message.peer_id,
        UserStates.READY_TO_ANALYZE,
        access_token=token,
    )
    try:
        await message.answer(
            "Вы уже авторизованы.\nНажмите «Запустить анализ».",
            keyboard=build_run_analysis_keyboard(),
        )
    except Exception as exc:
        logger.warning("Не удалось отправить ответ «уже авторизованы»: {}", exc)
    return True


@labeler.message(text=["/start", "Start", "start", "начать"])
async def start_handler(message: Message) -> None:
    vk_user_id = message.from_id
    bot = get_bot()

    async with async_session_factory() as db_session:
        vk_client = VKAPIClient(access_token=settings.vk_group_token)
        try:
            user_info = await vk_client.get_user_info(vk_user_id)
        except Exception:
            user_info = None
        finally:
            await vk_client.close()

        await crud.get_or_create_user(
            db_session,
            vk_user_id=vk_user_id,
            first_name=user_info.first_name if user_info else "",
            last_name=user_info.last_name if user_info else "",
        )

    await bot.state_dispenser.set(message.peer_id, UserStates.IDLE)
    try:
        await message.answer(WELCOME_TEXT, keyboard=build_start_keyboard())
    except VKAPIError[912]:
        await message.answer(
            "Включите «Возможности ботов» в настройках сообщества, затем /start",
        )


@labeler.message(text=["/status", "/статус"])
async def status_handler(message: Message) -> None:
    await message.answer(
        f"VK ID приложение: {settings.vk_app_id}\n"
        f"OAuth для API (legacy): {settings.vk_oauth_legacy_app_id}\n"
        f"Scope: {settings.vk_oauth_scope}\n"
        f"Автовход ngrok: {'да' if settings.oauth_ready else 'нет'}\n\n"
        f"Ссылка входа:\n{settings.build_implicit_auth_url('friends,groups')}",
    )


@labeler.message(text=["Начать анализ →", "Начать анализ", "начать анализ"])
async def begin_analysis_flow(message: Message) -> None:
    if settings.vk_app_id <= 0:
        await message.answer("Укажите VK_APP_ID в .env")
        return

    if await _already_authorized(message):
        return

    await get_bot().state_dispenser.set(message.peer_id, UserStates.WAITING_ACCESS_TOKEN)

    login_url = settings.build_implicit_auth_url("friends,groups")
    await message.answer(AUTH_TEXT, keyboard=build_login_keyboard(login_url))


@labeler.message(
    text=["Готово", "готово"],
    state=UserStates.WAITING_ACCESS_TOKEN,
)
async def auth_done_handler(message: Message) -> None:
    token = pop_oauth_pending_token(message.from_id) or get_oauth_pending_token(message.from_id)
    if not token:
        await message.answer("Вставьте ссылку из браузера после «Вход (+ группы)».")
        return
    await persist_user_token(message.from_id, message.peer_id, token)
    await message.answer("Готово! «Запустить анализ».", keyboard=build_run_analysis_keyboard())


@labeler.message(state=UserStates.WAITING_ACCESS_TOKEN)
async def receive_access_token(message: Message) -> None:
    if (message.text or "").strip().lower() == "готово":
        return

    token = extract_access_token(message.text or "")
    if not token:
        await message.answer("Скопируйте адресную строку после «Разрешить» и вставьте сюда.")
        return

    token_user_id, token_error = await validate_access_token(token)
    if token_error is not None:
        if isinstance(token_error, VKNetworkError):
            await message.answer(
                "Не удалось проверить токен (сеть). Попробуйте «Вход (+ группы)» ещё раз.",
            )
        elif is_token_ip_binding_error(token_error):
            await message.answer(TOKEN_IP_BINDING_MSG)
        else:
            await message.answer(f"Токен не принят: {token_error.message}")
        return

    if token_user_id and token_user_id != message.from_id:
        await message.answer(f"Токен от id {token_user_id}, а вы — {message.from_id}. Войдите под своим VK.")
        return

    await persist_user_token(message.from_id, message.peer_id, token)
    await message.answer("Токен сохранён. «Запустить анализ».", keyboard=build_run_analysis_keyboard())


@labeler.message(text=["/demo", "/демо"])
async def demo_auth_handler(message: Message) -> None:
    demo = get_demo_token()
    if not demo:
        await message.answer("Задайте DEMO_USER_TOKEN в .env для демо на защите.")
        return
    await persist_user_token(message.from_id, message.peer_id, demo)
    await message.answer("Демо-режим. «Запустить анализ».", keyboard=build_run_analysis_keyboard())


@labeler.message(text=["/logout", "/выйти", "Выйти", "выйти"])
async def logout_handler(message: Message) -> None:
    async with async_session_factory() as session:
        await crud.clear_user_access_token(session, message.from_id)
    pop_oauth_pending_token(message.from_id)
    await get_bot().state_dispenser.delete(message.peer_id)
    await message.answer("Вы вышли. /start → Начать анализ")
