"""Глобальная ссылка на экземпляр бота (для хендлеров в отдельных модулях)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vkbottle.bot import Bot

bot: Bot | None = None


def get_bot() -> Bot:
    if bot is None:
        raise RuntimeError("Бот ещё не инициализирован. Запустите main.py.")
    return bot
