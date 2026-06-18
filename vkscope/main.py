"""
VKScope — точка входа.
Анализируем подписки — находим единомышленников.
"""

import asyncio
import sys
from pathlib import Path

from loguru import logger
from vkbottle.bot import Bot

# Корень проекта в PYTHONPATH при запуске из PyCharm / python main.py
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot import app as bot_app
from bot.handlers import labelers
from vkbottle import BuiltinStateDispenser

from aiohttp import web

from bot.oauth.server import start_oauth_server
from bot.states import RedisStateDispenser
from config import settings
from database.session import init_db

oauth_runner: web.AppRunner | None = None


def setup_logging() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | {message}",
        level="INFO",
    )
    logger.add(
        ROOT / "logs" / "vkscope.log",
        rotation="10 MB",
        retention="14 days",
        encoding="utf-8",
        level="DEBUG",
    )


async def on_startup() -> None:
    global oauth_runner
    (ROOT / "logs").mkdir(exist_ok=True)
    logger.info("Инициализация PostgreSQL…")
    await init_db()
    if settings.oauth_ready:
        oauth_runner = await start_oauth_server()
    elif settings.vk_client_secret.strip() and not settings.oauth_https:
        logger.warning(
            "OAuth: VK ID требует HTTPS в OAUTH_PUBLIC_URL. "
            "Запустите ngrok http {} и укажите https://....ngrok-free.app",
            settings.oauth_port,
        )
    else:
        logger.warning(
            "OAuth-сервер выключен: VK_CLIENT_SECRET + OAUTH_PUBLIC_URL (https://...)"
        )
    logger.info("VKScope готов к работе")


async def enable_bot_long_poll_events(bot: Bot) -> None:
    """Включает message_event для callback-кнопок (если понадобятся)."""
    if settings.vk_group_id <= 0:
        return
    try:
        await bot.api.groups.set_long_poll_settings(
            group_id=settings.vk_group_id,
            message_new=True,
            message_reply=True,
            message_event=True,
        )
        logger.info("Long Poll: message_event включён для группы {}", settings.vk_group_id)
    except Exception as exc:
        logger.warning("Не удалось обновить Long Poll (message_event): {}", exc)


def create_state_dispenser():
    if settings.use_redis_fsm:
        logger.info("FSM: Redis ({})", settings.redis_dsn)
        return RedisStateDispenser(settings.redis_dsn)
    logger.info("FSM: в памяти (USE_REDIS_FSM=false)")
    return BuiltinStateDispenser()


def create_bot() -> Bot:
    bot = Bot(
        token=settings.vk_group_token,
        state_dispenser=create_state_dispenser(),
    )

    for labeler in labelers:
        bot.labeler.load(labeler)

    bot_app.bot = bot
    return bot


def main() -> None:
    setup_logging()
    bot = create_bot()

    async def _startup() -> None:
        await on_startup()
        await enable_bot_long_poll_events(bot)

    async def _shutdown() -> None:
        global oauth_runner
        if oauth_runner is not None:
            await oauth_runner.cleanup()
            oauth_runner = None
        if isinstance(bot.state_dispenser, RedisStateDispenser):
            await bot.state_dispenser.close()
        logger.info("VKScope остановлен")

    bot.on_startup.append(_startup())
    bot.on_shutdown.append(_shutdown())

    logger.info("Запуск Long Poll (VKScope)…")
    bot.run_forever()


if __name__ == "__main__":
    # Запускаем бота в отдельном потоке, чтобы не мешать веб-серверу
    from threading import Thread
    Thread(target=main).start()
    # Запускаем веб-сервер
    import asyncio
    import web_server
    asyncio.run(web_server.start_web_server())
