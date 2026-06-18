"""Проверка готовности к запуску VKScope (без вывода секретов)."""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import settings  # noqa: E402


def check_env() -> list[str]:
    issues: list[str] = []
    if not settings.vk_group_token or "your_group" in settings.vk_group_token:
        issues.append("VK_GROUP_TOKEN не задан или остался шаблон")
    elif len(settings.vk_group_token) < 50:
        issues.append(
            "VK_GROUP_TOKEN слишком короткий — оберните токен в кавычки в .env: "
            'VK_GROUP_TOKEN="vk1.a...."'
        )
    if settings.vk_app_id <= 0:
        issues.append("VK_APP_ID должен быть числом (ID приложения VK)")
    if settings.vk_client_secret.strip() and not settings.oauth_https:
        issues.append(
            "OAUTH_PUBLIC_URL должен начинаться с https:// (ngrok: ngrok http 8765)"
        )
    return issues


async def check_redis() -> str | None:
    import redis.asyncio as aioredis

    client = aioredis.from_url(settings.redis_dsn, decode_responses=True)
    try:
        await client.ping()
        return None
    except Exception as exc:
        return f"Redis недоступен ({settings.redis_dsn}): {exc}"
    finally:
        await client.aclose()


async def check_postgres() -> str | None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(settings.postgres_dsn)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return None
    except Exception as exc:
        return f"PostgreSQL недоступен: {exc}"
    finally:
        await engine.dispose()


async def main() -> None:
    print("=== Проверка VKScope ===\n")
    env_issues = check_env()
    if env_issues:
        print("Конфиг (.env):")
        for item in env_issues:
            print(f"  [X] {item}")
    else:
        print("Конфиг (.env): OK")
        print(f"  VK_APP_ID = {settings.vk_app_id}")
        print(f"  Длина VK_GROUP_TOKEN = {len(settings.vk_group_token)} символов")

    redis_err = None
    if settings.use_redis_fsm:
        redis_err = await check_redis()
        print(f"\nRedis: {'OK' if not redis_err else '[X] ' + redis_err}")
    else:
        print("\nRedis: пропущен (USE_REDIS_FSM=false, состояния в памяти)")

    pg_err = await check_postgres()
    print(f"PostgreSQL: {'OK' if not pg_err else '[X] ' + pg_err}")

    if env_issues or redis_err or pg_err:
        print("\nИтог: пока НЕ готов к запуску — исправьте пункты выше.")
        sys.exit(1)
    print("\nИтог: можно запускать → python main.py")


if __name__ == "__main__":
    asyncio.run(main())
