from aiohttp import web
import asyncio
import threading
import os

async def health_check(request):
    return web.Response(text="VKScope Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    # Render даёт порт через переменную окружения PORT
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Web server started on port {port}")
    # Бесконечно держим сервер
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(start_web_server())