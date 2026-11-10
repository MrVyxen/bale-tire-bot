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
        text="🚀 Bale Tire Sniper Bot is LIVE and running!",
        content_type="text/plain",
        charset="utf-8",
        status=200
    )

async def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    app = web.Application()
    app.router.add_get("/", health_check_handler)
    app.router.add_get("/health", health_check_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Render Web Health Server listening on 0.0.0.0:{port}")
    return runner

_chat_locks: dict[int, asyncio.Lock] = {}


async def _dispatch_safely(chat_id: int, coro_fn, payload):
    lock = _chat_locks.setdefault(chat_id, asyncio.Lock())
    async with lock:
        try:
            await coro_fn(payload)
        except Exception:
            logger.exception(f"Unhandled error in update handler for chat_id={chat_id}")


async def bot_polling_worker(bot_client: BaleBotClient, handlers: BaleBotHandlers):
    offset = 0
    logger.info("Polling loop started. Listening for updates...")
    while True:
        try:
            updates = await bot_client.get_updates(offset=offset, timeout=20)
            if updates.get("ok"):
                for update in updates.get("result", []):
                    offset = update["update_id"] + 1

                    if "message" in update:
                        msg = update["message"]
                        if "text" in msg:
                            cid = msg.get("chat", {}).get("id", 0)
                            asyncio.create_task(_dispatch_safely(cid, handlers.handle_text_message, msg))

                    elif "callback_query" in update:
                        cq = update["callback_query"]
                        cid = cq.get("message", {}).get("chat", {}).get("id", 0)
                        asyncio.create_task(_dispatch_safely(cid, handlers.handle_callback_query, cq))
            else:
                logger.warning(f"Bale getUpdates response: {updates}")
                await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            await asyncio.sleep(3)
        await asyncio.sleep(0.1)

async def run_bot():
    logger.info("Initializing Tire Sniper Bot for Bale...")
    
    # ۱. راه‌اندازی فوری وب‌سرور جهت عبور بدون وقفه از Health Check رندر
    web_runner = await start_web_server()

    # ۲. راه‌اندازی دیتابیس
    try:
        await init_db()
    except Exception as e:
        logger.error(f"DB init warning: {e}")

    # ۳. اتصال به بله با قابلیت تلاش مجدد مداوم
    bot_client = BaleBotClient()
    connected = False
    for attempt in range(1, 10):
        try:
            me = await bot_client.get_me()
            if me.get("ok"):
                bot_info = me.get("result", {})
                logger.info(f"Bot connected successfully: @{bot_info.get('username')} ({bot_info.get('first_name')})")
                connected = True
                break
            else:
                logger.warning(f"Connecting to Bale attempt {attempt}/10 failed: {me}")
        except Exception as e:
            logger.warning(f"Connection attempt {attempt}/10 error: {e}")
        await asyncio.sleep(3)

    sniper_engine = SniperEngine(bot_client)
    handlers = BaleBotHandlers(bot_client, sniper_engine)

    # بازگردانی اسنایپرهای فعال
    try:
        active_users = await get_all_active_snipers()
        if active_users:
            logger.info(f"Restoring {len(active_users)} active snipers...")
            for u in active_users:
                await sniper_engine.start_sniper_for_user(u["chat_id"])
    except Exception as e:
        logger.error(f"Sniper restore error: {e}")

    # اجرای پیوسته Polling
    polling_task = asyncio.create_task(bot_polling_worker(bot_client, handlers))

    try:
        # نگه‌داشتن ابدی پروسه تا وب‌سرور زنده بماند
        while True:
            await asyncio.sleep(3600)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Shutting down bot...")
    finally:
        polling_task.cancel()
        await bot_client.close()
        await web_runner.cleanup()
        logger.info("Bot and Web Server stopped.")

if __name__ == "__main__":
    asyncio.run(run_bot())
