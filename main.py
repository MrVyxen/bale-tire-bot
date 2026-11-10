import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
import time
from aiohttp import web
from config import BASE_DIR
from database import get_analytics_summary, get_all_active_snipers, init_db
from bale_api import BaleBotClient
from dashboard_html import DASHBOARD_HTML
from telemetry import redact_secrets, telemetry
from tire_api.sniper_engine import SniperEngine
from tire_api.utils import normalize_tire_size, persian_to_english_digits
from bot_handlers import BaleBotHandlers

LOG_FILE = BASE_DIR / "bot_monitor.log"
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(_fmt)

_file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
_file_handler.setFormatter(_fmt)

logging.basicConfig(level=logging.INFO, handlers=[_stream_handler, _file_handler])
# جلوگیری از شلوغ‌شدن لاگ توسط درخواست‌های رفرش داشبورد و مانیتور
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
logger = logging.getLogger("Main")

_sniper_engine_ref: SniperEngine | None = None
_db_cache: tuple[float, dict] = (0.0, {})


async def _get_cached_db_analytics() -> dict:
    global _db_cache
    now = time.monotonic()
    if now - _db_cache[0] >= 5.0:
        _db_cache = (now, await get_analytics_summary())
    return _db_cache[1]


async def health_check_handler(request):
    """اندپوینت بررسی سلامت سرور"""
    return web.Response(
        text="🚀 Bale Tire Sniper Bot is LIVE and running!",
        content_type="text/plain",
        charset="utf-8",
        status=200,
    )


async def status_handler(request):
    """اندپوینت JSON تله‌متری و آنالیز دقیق"""
    active_snipers = []
    if _sniper_engine_ref:
        active_snipers = [
            cid for cid, t in _sniper_engine_ref.running_tasks.items() if not t.done()
        ]
    db_analytics = await _get_cached_db_analytics()
    return web.json_response(telemetry.build_snapshot(active_snipers=active_snipers, db_analytics=db_analytics))


async def dashboard_handler(request):
    """داشبورد گرافیکی رصد و آنالیز لحظه‌ای ربات"""
    return web.Response(text=DASHBOARD_HTML, content_type="text/html", charset="utf-8")


async def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    app = web.Application()
    app.router.add_get("/", health_check_handler)
    app.router.add_get("/health", health_check_handler)
    app.router.add_get("/status", status_handler)
    app.router.add_get("/dashboard", dashboard_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Render Web & Analytics Server listening on 0.0.0.0:{port} (/dashboard, /status)")
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
    return f"text(len={len(raw_txt)})"


async def _dispatch_safely(chat_id: int, kind: str, coro_fn, payload):
    lock = _chat_locks.setdefault(chat_id, asyncio.Lock())
    label = _safe_event_label(kind, payload)
    telemetry.record_update_start(kind, chat_id)

    t0 = time.perf_counter()
    logger.info(f"[IN][{kind}] chat={chat_id} {label}")
    async with lock:
        ok = True
        err_msg = ""
        try:
            await coro_fn(payload)
        except Exception as e:
            ok = False
            err_msg = f"{type(e).__name__}: {e}"
            logger.exception(f"Unhandled error in update handler [{kind}] chat_id={chat_id} {label}")
        finally:
            lat = round((time.perf_counter() - t0) * 1000, 1)
            telemetry.record_update_finish(kind, chat_id, label, lat, ok=ok, error_msg=err_msg)
            logger.info(f"[OUT][{kind}] chat={chat_id} {label} status={'OK' if ok else 'ERR'} elapsed={lat}ms")


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
                if not updates.get("_recorded"):
                    telemetry.record_error("bale_polling", "BadResponse", str(updates))
                logger.warning(f"Bale getUpdates response: {updates}")
                await asyncio.sleep(3)
        except Exception as e:
            safe_err = redact_secrets(e)
            telemetry.record_error("bale_polling", type(e).__name__, safe_err)
            logger.error(f"Polling error: {type(e).__name__}: {safe_err}")
            await asyncio.sleep(3)
        await asyncio.sleep(0.1)


async def active_analytics_worker(bot_client: BaleBotClient, sniper_engine: SniperEngine):
    """
    پروب سبک و هوشمند هر ۱۸۰ ثانیه:
    - اندازه‌گیری پینگ زنده سرور بله (getMe)
    - رصد سلامت و موجودی کارخانه‌های تایر دولتی برای به‌روز نگه‌داشتن داشبورد آنالیز
    """
    await asyncio.sleep(2.0)
    while True:
        try:
            await bot_client.get_me()
        except Exception as e:
            telemetry.record_bale_health(False, 0.0)
            telemetry.record_error("active_probe", type(e).__name__, f"getMe: {redact_secrets(e)}")

        try:
            scan = await sniper_engine.scan_all_portals_live("all")
            online_cnt = sum(1 for p in scan["portals_status"] if p.get("ok"))
            stock_cnt = len(scan.get("all_in_stock_items", []))
            sizes = sorted(b["size"] for b in scan.get("available_sizes", {}).values())
            logger.info(
                f"[ACTIVE_PROBE] portals_online={online_cnt}/10 in_stock={stock_cnt} sizes={sizes}"
            )
        except Exception as e:
            telemetry.record_error("active_probe", type(e).__name__, f"portal_scan: {e}")
            logger.warning(f"Active portal probe error: {type(e).__name__}: {e}")

        await asyncio.sleep(180.0)


async def run_bot():
    global _sniper_engine_ref
    logger.info("Initializing Tire Sniper Bot for Bale...")

    # ۱. راه‌اندازی فوری وب‌سرور و داشبورد آنالیز (/dashboard و /status)
    web_runner = await start_web_server()

    # ۲. راه‌اندازی دیتابیس
    try:
        await init_db()
    except Exception as e:
        telemetry.record_error("database", type(e).__name__, str(e))
        logger.error(f"DB init warning: {e}")

    # ۳. اتصال به بله با قابلیت تلاش مجدد مداوم
    bot_client = BaleBotClient()
    for attempt in range(1, 10):
        try:
            me = await bot_client.get_me()
            if me.get("ok"):
                bot_info = me.get("result", {})
                uname = bot_info.get("username", "")
                logger.info(f"Bot connected successfully: @{uname} ({bot_info.get('first_name')})")
                break
            else:
                logger.warning(f"Connecting to Bale attempt {attempt}/10 failed: {me}")
        except Exception as e:
            logger.warning(f"Connection attempt {attempt}/10 error: {type(e).__name__}: {redact_secrets(e)}")
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

    # اجرای پیوسته Polling و پروب آنالیز زنده
    polling_task = asyncio.create_task(bot_polling_worker(bot_client, handlers))
    probe_task = asyncio.create_task(active_analytics_worker(bot_client, sniper_engine))

    try:
        while True:
            await asyncio.sleep(3600)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Shutting down bot...")
    finally:
        polling_task.cancel()
        probe_task.cancel()
        await sniper_engine.close_all()
        await bot_client.close()
        await web_runner.cleanup()
        logger.info("Bot and Web Server stopped.")


if __name__ == "__main__":
    asyncio.run(run_bot())
