import json
import sqlite3
import time
import urllib.request
from pathlib import Path
from tire_api.utils import get_tehran_now

BASE_DIR = Path(__file__).resolve().parent
BOT_LOG_FILE = BASE_DIR / "bot_monitor.log"
DB_PATH = BASE_DIR / "tire_bot.db"
STATUS_URL = "http://127.0.0.1:10000/status"
POLL_INTERVAL_SEC = 4.0
HEARTBEAT_LOG_EVERY_SEC = 60.0


def fetch_bot_status() -> tuple[bool, dict, float]:
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(STATUS_URL, method="GET")
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            lat = round((time.perf_counter() - t0) * 1000, 1)
            data = json.loads(resp.read().decode("utf-8"))
            return True, data, lat
    except Exception as e:
        lat = round((time.perf_counter() - t0) * 1000, 1)
        return False, {"error": str(e)}, lat


def read_db_summary() -> dict:
    try:
        con = sqlite3.connect(DB_PATH, timeout=3.0)
        users_cnt = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        snipers_cnt = con.execute("SELECT COUNT(*) FROM users WHERE sniper_enabled = 1").fetchone()[0]
        logs_cnt = con.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
        con.close()
        return {"users": users_cnt, "snipers": snipers_cnt, "logs": logs_cnt}
    except Exception as e:
        return {"error": str(e)}


def main():
    print(f"📡 [MONITOR STARTED] {get_tehran_now()['full_fa']}", flush=True)
    print(f"   Target Status: {STATUS_URL} | Log File: {BOT_LOG_FILE}", flush=True)

    last_file_pos = 0
    if BOT_LOG_FILE.exists():
        # شروع دنبال‌کردن از انتهای فایل موجود پس از چاپ ۱۰ خط آخر آن
        lines = BOT_LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
        for tail_ln in lines[-10:]:
            print(f"   [PREV_LOG] {tail_ln}", flush=True)
        last_file_pos = BOT_LOG_FILE.stat().st_size

    last_heartbeat = 0.0
    last_error_count = 0
    last_updates_count = -1
    was_down = False

    while True:
        now_str = get_tehran_now()["time_hms"]

        # ۱. خواندن خط‌به‌خط رویدادهای جدید از فایل لاگ ربات (Real-Time Tail)
        if BOT_LOG_FILE.exists():
            size_now = BOT_LOG_FILE.stat().st_size
            if size_now < last_file_pos:
                last_file_pos = 0  # چرخش فایل لاگ (Rotation)
            if size_now > last_file_pos:
                with BOT_LOG_FILE.open("r", encoding="utf-8", errors="ignore") as f:
                    f.seek(last_file_pos)
                    new_chunk = f.read()
                    last_file_pos = f.tell()
                for line in new_chunk.splitlines():
                    if not line.strip():
                        continue
                    is_err = ("[ERROR]" in line or "[WARNING]" in line or "Traceback" in line)
                    prefix = "🚨 [LIVE-ALERT]" if is_err else "⚡ [LIVE-EVENT]"
                    print(f"{prefix} {line}", flush=True)

        # ۲. پایش سلامت و متریک از اندپوینت /status
        ok, st_data, probe_ms = fetch_bot_status()
        if not ok:
            if not was_down:
                print(f"🚨 [{now_str}] BOT UNREACHABLE on {STATUS_URL} ({probe_ms}ms): {st_data.get('error')}", flush=True)
                was_down = True
        else:
            if was_down:
                print(f"✅ [{now_str}] BOT RECOVERED! @{st_data.get('bot_username')} ({probe_ms}ms)", flush=True)
                was_down = False

            cur_errs = int(st_data.get("total_errors", 0))
            cur_upds = int(st_data.get("total_updates", 0))

            if cur_errs > last_error_count:
                print(
                    f"🚨 [{now_str}] ERROR COUNT INCREASED ({last_error_count} -> {cur_errs}) | "
                    f"Last Error: {st_data.get('last_error')}",
                    flush=True,
                )
                last_error_count = cur_errs

            if cur_upds != last_updates_count and last_updates_count != -1:
                recent = (st_data.get("recent_events") or [])[:1]
                r_txt = f" | {recent[0]}" if recent else ""
                print(f"🔔 [{now_str}] ACTIVITY updates={cur_upds} probe={probe_ms}ms{r_txt}", flush=True)
            last_updates_count = cur_upds

            # ۳. گزارش نبض هر ۶۰ ثانیه
            if time.monotonic() - last_heartbeat >= HEARTBEAT_LOG_EVERY_SEC:
                db_sum = read_db_summary()
                print(
                    f"💚 [{now_str}] HEARTBEAT | @{st_data.get('bot_username')} connected={st_data.get('connected')} | "
                    f"uptime={st_data.get('uptime_sec')}s | probe={probe_ms}ms | updates={cur_upds} "
                    f"(msg={st_data.get('total_messages')} cb={st_data.get('total_callbacks')}) | "
                    f"errors={cur_errs} | snipers={st_data.get('active_snipers_count')} | db={db_sum}",
                    flush=True,
                )
                last_heartbeat = time.monotonic()

        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
