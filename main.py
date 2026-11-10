import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import time
from collections import deque
from aiohttp import web
from config import BASE_DIR, BOT_TOKEN
from database import init_db, get_all_active_snipers
from bale_api import BaleBotClient
from tire_api.sniper_engine import SniperEngine
from tire_api.utils import get_tehran_now, normalize_tire_size, persian_to_english_digits
from bot_handlers import BaleBotHandlers

LOG_FILE = BASE_DIR / "bot_monitor.log"
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(_fmt)

_file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
_file_handler.setFormatter(_fmt)

logging.basicConfig(level=logging.INFO, handlers=[_stream_handler, _file_handler])
# جلوگیری از شلوغ‌شدن لاگ توسط درخواست‌های هر چند ثانیه /status و /health
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
logger = logging.getLogger("Main")

BOT_METRICS = {
    "started_monotonic": time.monotonic(),
    "started_tehran": get_tehran_now()["full_fa"],
    "bot_username": "",
    "connected": False,
    "total_updates": 0,
    "total_messages": 0,
    "total_callbacks": 0,
    "total_errors": 0,
    "last_event_at": None,
    "last_error": None,
    "recent_events": deque(maxlen=40),
}
_sniper_engine_ref: SniperEngine | None = None


async def health_check_handler(request):
    """اندپوینت بررسی سلامت سرور"""
    return web.Response(
        text="🚀 Bale Tire Sniper Bot is LIVE and running!",
        content_type="text/plain",
        charset="utf-8",
        status=200,
    )


async def status_handler(request):
    """اندپوینت مانیتورینگ لحظه‌ای JSON برای پایش مداوم ربات"""
    active_snipers = []
    if _sniper_engine_ref:
        active_snipers = [
            cid for cid, t in _sniper_engine_ref.running_tasks.items() if not t.done()
        ]
    uptime_sec = round(time.monotonic() - BOT_METRICS["started_monotonic"], 1)
    payload = {
        "status": "ok" if BOT_METRICS["connected"] else "connecting",
        "tehran_now": get_tehran_now()["full_fa"],
        "started_tehran": BOT_METRICS["started_tehran"],
        "uptime_sec": uptime_sec,
        "bot_username": BOT_METRICS["bot_username"],
        "connected": BOT_METRICS["connected"],
        "total_updates": BOT_METRICS["total_updates"],
        "total_messages": BOT_METRICS["total_messages"],
        "total_callbacks": BOT_METRICS["total_callbacks"],
        "total_errors": BOT_METRICS["total_errors"],
        "active_snipers_count": len(active_snipers),
        "active_snipers": active_snipers,
        "last_event_at": BOT_METRICS["last_event_at"],
        "last_error": BOT_METRICS["last_error"],
        "recent_events": list(BOT_METRICS["recent_events"]),
    }
    return web.json_response(payload)


async def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    app = web.Application()
    app.router.add_get("/", health_check_handler)
    app.router.add_get("/health", health_check_handler)
    app.router.add_get("/status", status_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Render Web Health Server listening on 0.0.0.0:{port}")
    return runner


_chat_locks: dict[int, asyncio.Lock] = {}


def _safe_event_label(kind: str, payload: dict) -> str:
    if kind == "CB":
        return f"cb={payload.get('data', '')}"
    raw_txt = persian_to_english_digits((payload.get("text") or "").strip())
    if raw_txt.startswith("/"):
        return f"cmd={raw_txt.split()[0]}"
    sz = normalize_tire_size(raw_txt)
    if sz:
        return f"size={sz}"
    # محافظت از افشای اطلاعات حساس کاربر (کد ملی، موبایل، پلاک، کد تایید) در فایل لاگ
    return f"text(len={len(raw_txt)})"


async def _dispatch_safely(chat_id: int, kind: str, coro_fn, payload):
    lock = _chat_locks.setdefault(chat_id, asyncio.Lock())
    label = _safe_event_label(kind, payload)
    BOT_METRICS["total_updates"] += 1
    if kind == "CB":
        BOT_METRICS["total_callbacks"] += 1
    else:
        BOT_METRICS["total_messages"] += 1

    t0 = time.perf_counter()
    logger.info(f"[IN][{kind}] chat={chat_id} {label}")
    async with lock:
        status = "OK"
        err_msg = ""
        try:
            await coro_fn(payload)
        except Exception as e:
            status = "ERR"
            err_msg = str(e)
            BOT_METRICS["total_errors"] += 1
            BOT_METRICS["last_error"] = f"{get_tehran_now()['time_hms']} {kind} chat={chat_id}: {e}"
            logger.exception(f"Unhandled error in update handler [{kind}] chat_id={chat_id} {label}")
        finally:
            lat = round((time.perf_counter() - t0) * 1000, 1)
            now_hms = get_tehran_now()["time_hms"]
            BOT_METRICS["last_event_at"] = now_hms
            BOT_METRICS["recent_events"].appendleft({
                "time": now_hms,
                "chat_id": chat_id,
                "kind": kind,
                "label": label,
                "status": status,
                "latency_ms": lat,
                **({"error": err_msg} if err_msg else {}),
            })
            logger.info(f"[OUT][{kind}] chat={chat_id} {label} status={status} elapsed={lat}ms")


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
                            asyncio.create_task(_dispatch_safely(cid, "MSG", handlers.handle_text_message, msg))

                    elif "callback_query" in update:
                        cq = update["callback_query"]
                        cid = cq.get("message", {}).get("chat", {}).get("id", 0)
                        asyncio.create_task(_dispatch_safely(cid, "CB", handlers.handle_callback_query, cq))
            else:
                BOT_METRICS["total_errors"] += 1
                BOT_METRICS["last_error"] = f"{get_tehran_now()['time_hms']} getUpdates: {updates}"
                logger.warning(f"Bale getUpdates response: {updates}")
                await asyncio.sleep(3)
        except Exception as e:
            BOT_METRICS["total_errors"] += 1
            BOT_METRICS["last_error"] = f"{get_tehran_now()['time_hms']} polling: {e}"
            logger.error(f"Polling error: {e}")
            await asyncio.sleep(3)
        await asyncio.sleep(0.1)


async def run_bot():
    global _sniper_engine_ref
    logger.info("Initializing Tire Sniper Bot for Bale...")

    # ۱. راه‌اندازی فوری وب‌سرور و اندپوینت مانیتورینگ /status
    web_runner = await start_web_server()

    # ۲. راه‌اندازی دیتابیس
    try:
        await init_db()
    except Exception as e:
        logger.error(f"DB init warning: {e}")

    # ۳. اتصال به بله با قابلیت تلاش مجدد مداوم
    bot_client = BaleBotClient()
    for attempt in range(1, 10):
        try:
            me = await bot_client.get_me()
            if me.get("ok"):
                bot_info = me.get("result", {})
                uname = bot_info.get("username", "")
                BOT_METRICS["connected"] = True
                BOT_METRICS["bot_username"] = uname
                logger.info(f"Bot connected successfully: @{uname} ({bot_info.get('first_name')})")
                break
            else:
                logger.warning(f"Connecting to Bale attempt {attempt}/10 failed: {me}")
        except Exception as e:
            logger.warning(f"Connection attempt {attempt}/10 error: {e}")
        await asyncio.sleep(3)

    sniper_engine = SniperEngine(bot_client)
    _sniper_engine_ref = sniper_engine
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
        while True:
            await asyncio.sleep(3600)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Shutting down bot...")
    finally:
        polling_task.cancel()
        await sniper_engine.close_all()
        await bot_client.close()
        await web_runner.cleanup()
        logger.info("Bot and Web Server stopped.")


if __name__ == "__main__":
    asyncio.run(run_bot())
