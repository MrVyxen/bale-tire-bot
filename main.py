import asyncio
import logging
import os
import signal
from aiohttp import web
from config import BOT_TOKEN
from database import init_db, get_all_active_snipers
from bale_api import BaleBotClient
from tire_api.sniper_engine import SniperEngine
from bot_handlers import BaleBotHandlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("Main")

async def health_check_handler(request):
    """
    اندپوینت بررسی سلامت سرور برای Render
    این اندپوینت باعث می‌شود رندر سرویس را فعال و آنلاین (Healthy) شناسایی کند.
    """
    return web.Response(
        text="🚀 Bale Tire Sniper Bot is LIVE and running on Render!",
        content_type="text/plain; charset=utf-8"
    )

async def start_web_server():
    port = int(os.environ.get("PORT", 8080))
    app = web.Application()
    app.router.add_get("/", health_check_handler)
    app.router.add_get("/health", health_check_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Render Web Health Server started on port {port}")
    return runner

async def run_bot():
    logger.info("Initializing Tire Sniper Bot for Bale...")
    await init_db()

    # راه‌اندازی وب‌سرور جهت سازگاری با رندر (Render Port Binding)
    web_runner = await start_web_server()

    bot_client = BaleBotClient()
    me = await bot_client.get_me()
    if not me.get("ok"):
        logger.error(f"Failed to connect to Bale with provided token: {me}")
        return

    bot_info = me.get("result", {})
    logger.info(f"Bot connected successfully: @{bot_info.get('username')} ({bot_info.get('first_name')})")

    sniper_engine = SniperEngine(bot_client)
    handlers = BaleBotHandlers(bot_client, sniper_engine)

    # بازگردانی اسنایپرهای فعال از پایگاه داده
    active_users = await get_all_active_snipers()
    if active_users:
        logger.info(f"Restoring {len(active_users)} active snipers...")
        for u in active_users:
            await sniper_engine.start_sniper_for_user(u["chat_id"])

    offset = 0
    logger.info("Polling loop started. Listening for updates...")

    try:
        while True:
            updates = await bot_client.get_updates(offset=offset, timeout=20)
            if updates.get("ok"):
                for update in updates.get("result", []):
                    offset = update["update_id"] + 1

                    if "message" in update:
                        msg = update["message"]
                        if "text" in msg:
                            asyncio.create_task(handlers.handle_text_message(msg))

                    elif "callback_query" in update:
                        cq = update["callback_query"]
                        asyncio.create_task(handlers.handle_callback_query(cq))

            await asyncio.sleep(0.1)

    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Shutting down bot...")
    finally:
        await bot_client.close()
        await web_runner.cleanup()
        logger.info("Bot and Web Server stopped.")

if __name__ == "__main__":
    asyncio.run(run_bot())
