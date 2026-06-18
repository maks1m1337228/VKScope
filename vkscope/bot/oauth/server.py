"""Локальный OAuth-сервер: пользователь не копирует токен вручную."""

from __future__ import annotations

import urllib.parse

import httpx
from aiohttp import web
from loguru import logger

from bot.oauth import store as auth_store
from bot.utils.user_token import persist_user_token
from config import settings

SUCCESS_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>VKScope — вход выполнен</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 480px; margin: 40px auto; padding: 0 16px; }
    .ok { color: #2a7; font-size: 1.2em; }
  </style>
</head>
<body>
  <p class="ok">✅ Вход через VK выполнен.</p>
  <p>Вернитесь в VK — бот уже отправил сообщение.</p>
  <p>Окно можно закрыть.</p>
</body>
</html>"""

ERROR_HTML = """<!DOCTYPE html>
<html lang="ru"><body>
  <p>❌ Ошибка авторизации: {error}</p>
  <p>Закройте окно и попробуйте снова из бота.</p>
</body></html>"""


def _authorize_url(state: str, scope: str | None = "friends") -> str:
    """scope=friends по умолчанию; scope='' — без параметра scope."""
    params: dict[str, str] = {
        "client_id": str(settings.vk_oauth_legacy_app_id),
        "display": "page",
        "redirect_uri": settings.oauth_redirect_uri,
        "response_type": "code",
        "state": state,
        "v": settings.vk_api_version,
    }
    effective = settings.vk_oauth_scope if scope is None else scope
    if effective:
        params["scope"] = effective.replace(" ", ",").strip()
    return "https://oauth.vk.com/authorize?" + urllib.parse.urlencode(params)


async def _exchange_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0, trust_env=settings.vk_http_trust_env) as client:
        response = await client.get(
            "https://oauth.vk.com/access_token",
            params={
                "client_id": settings.vk_oauth_legacy_app_id,
                "client_secret": settings.vk_client_secret,
                "redirect_uri": settings.oauth_redirect_uri,
                "code": code,
            },
        )
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise RuntimeError(data.get("error_description", data["error"]))
        return data


async def login_handler(request: web.Request) -> web.Response:
    """Старт OAuth: редирект на страницу разрешений VK."""
    try:
        vk_user_id = int(request.query.get("user_id", 0))
        peer_id = int(request.query.get("peer_id", vk_user_id))
    except ValueError:
        return web.Response(text="Некорректные параметры", status=400)

    if vk_user_id <= 0:
        return web.Response(text="user_id обязателен", status=400)

    # scope: friends (default) | minimal (пусто) | full (из .env)
    scope_param = request.query.get("scope", "friends")
    if scope_param == "minimal":
        scope_param = ""
    elif scope_param == "full":
        scope_param = None
    state = auth_store.create_session(vk_user_id, peer_id)
    raise web.HTTPFound(_authorize_url(state, scope=scope_param))


async def callback_handler(request: web.Request) -> web.Response:
    """VK возвращает code — меняем на access_token и сохраняем."""
    error = request.query.get("error_description") or request.query.get("error")
    if error:
        logger.warning("OAuth error from VK: {}", error)
        return web.Response(
            text=ERROR_HTML.format(error=error),
            content_type="text/html",
            charset="utf-8",
        )

    code = request.query.get("code")
    state = request.query.get("state")
    if not code or not state:
        return web.Response(text=ERROR_HTML.format(error="нет code или state"), status=400)

    session = auth_store.get_session(state)
    if session is None:
        return web.Response(text=ERROR_HTML.format(error="сессия устарела, начните снова из бота"), status=400)

    try:
        token_data = await _exchange_code(code)
        access_token = str(token_data["access_token"])
        auth_store.complete(state, access_token)
        await persist_user_token(session.vk_user_id, session.peer_id, access_token)

        try:
            from bot.app import get_bot
            from bot.keyboards.carousel_builder import build_run_analysis_keyboard

            bot = get_bot()
            await bot.api.messages.send(
                peer_id=session.peer_id,
                message="Вход выполнен. Нажмите «Запустить анализ».",
                keyboard=build_run_analysis_keyboard(),
                random_id=0,
            )
        except Exception as notify_exc:
            logger.warning("Не удалось уведомить в VK: {}", notify_exc)

        logger.info("OAuth OK для vk_user_id={}", session.vk_user_id)
        return web.Response(text=SUCCESS_HTML, content_type="text/html", charset="utf-8")
    except Exception as exc:
        logger.exception("OAuth token exchange failed: {}", exc)
        return web.Response(text=ERROR_HTML.format(error=str(exc)), status=500)


def create_oauth_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/oauth/login", login_handler)
    app.router.add_get("/oauth/callback", callback_handler)
    return app


async def start_oauth_server() -> web.AppRunner:
    """Запуск HTTP-сервера для callback (порт из .env)."""
    app = create_oauth_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.oauth_port)
    await site.start()
    logger.info(
        "OAuth-сервер: {} (redirect: {})",
        settings.oauth_public_url,
        settings.oauth_redirect_uri,
    )
    return runner
