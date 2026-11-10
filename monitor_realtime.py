import json
import sqlite3
import time
import urllib.request
from pathlib import Path
from tire_api.utils import get_tehran_now

BASE_DIR = Path(__file__).resolve().parent
BOT_LOG_FILE = BASE_DIR / "bot_monitor.log"
EVENTS_JSONL = BASE_DIR / "monitor_events.jsonl"
DB_PATH = BASE_DIR / "tire_bot.db"
STATUS_URL = "http://127.0.0.1:10000/status"
POLL_INTERVAL_SEC = 3.0
HEARTBEAT_EVERY_SEC = 30.0
SLOW_HANDLER_MS = 4000.0
MEM_WARN_MB = 300.0


def fetch_status() -> tuple[bool, dict, float]:
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(STATUS_URL, method="GET")
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            lat = round((time.perf_counter() - t0) * 1000, 1)
            return True, json.loads(resp.read().decode("utf-8")), lat
    except Exception as e:
        lat = round((time.perf_counter() - t0) * 1000, 1)
        return False, {"error": str(e)}, lat


def append_jsonl(event_type: str, payload: dict) -> None:
    try:
        rec = {
            "ts": get_tehran_now()["compact_fa"],
            "time_hms": get_tehran_now()["time_hms"],
            "type": event_type,
            **payload,
        }
        with EVENTS_JSONL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def main():
    print(f"🔭 [PRO REAL-TIME MONITOR STARTED] {get_tehran_now()['full_fa']}", flush=True)
    print(f"   Status API : {STATUS_URL}", flush=True)
    print(f"   Web Panel  : http://127.0.0.1:10000/dashboard", flush=True)
    print(f"   Log Tail   : {BOT_LOG_FILE}", flush=True)

    last_file_pos = 0
    if BOT_LOG_FILE.exists():
        lines = BOT_LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
        for ln in lines[-8:]:
            print(f"   [TAIL_INIT] {ln}", flush=True)
        last_file_pos = BOT_LOG_FILE.stat().st_size

    last_heartbeat = 0.0
    last_error_count = 0
    last_updates_count = -1
    last_stock_sizes: set[str] = set()
    was_down = False
    mem_alerted = False

    while True:
        now_hms = get_tehran_now()["time_hms"]

        # ۱. تعقیب لحظه‌ای خطوط تازه در bot_monitor.log
        if BOT_LOG_FILE.exists():
            size_now = BOT_LOG_FILE.stat().st_size
            if size_now < last_file_pos:
                last_file_pos = 0
            if size_now > last_file_pos:
                with BOT_LOG_FILE.open("r", encoding="utf-8", errors="ignore") as f:
                    f.seek(last_file_pos)
                    chunk = f.read()
                    last_file_pos = f.tell()
                for line in chunk.splitlines():
                    if not line.strip():
                        continue
                    is_err = ("[ERROR]" in line or "[WARNING]" in line or "Traceback" in line)
                    tag = "🚨 [LOG-ALERT]" if is_err else "📄 [LOG]"
                    print(f"{tag} {line}", flush=True)
                    if is_err:
                        append_jsonl("LOG_ALERT", {"line": line[:300]})

        # ۲. دریافت تله‌متری جامع از /status
        ok, st, probe_ms = fetch_status()
        if not ok:
            if not was_down:
                print(f"🚨 [{now_hms}] CRITICAL: Bot /status unreachable ({probe_ms}ms): {st.get('error')}", flush=True)
                append_jsonl("BOT_DOWN", {"probe_ms": probe_ms, "error": st.get("error")})
                was_down = True
        else:
            if was_down:
                print(f"✅ [{now_hms}] RECOVERED: @{st.get('bot_username')} online ({probe_ms}ms)", flush=True)
                append_jsonl("BOT_UP", {"probe_ms": probe_ms})
                was_down = False

            cur_errs = int(st.get("total_errors", 0))
            cur_upds = int(st.get("total_updates", 0))
            mem_mb = float(st.get("memory_mb", 0.0))

            if cur_errs > last_error_count:
                print(
                    f"🚨 [{now_hms}] ERROR_INCREASE ({last_error_count} -> {cur_errs}) | {st.get('last_error')}",
                    flush=True,
                )
                append_jsonl("ERROR_INCREASE", {"from": last_error_count, "to": cur_errs, "last_error": st.get("last_error")})
                last_error_count = cur_errs

            if mem_mb > MEM_WARN_MB and not mem_alerted:
                print(f"⚠️ [{now_hms}] HIGH_MEMORY: {mem_mb} MB > {MEM_WARN_MB} MB", flush=True)
                append_jsonl("HIGH_MEMORY", {"memory_mb": mem_mb})
                mem_alerted = True
            elif mem_mb <= MEM_WARN_MB:
                mem_alerted = False

            if probe_ms > 1500.0:
                print(f"⚠️ [{now_hms}] SLOW_STATUS_PROBE: {probe_ms} ms", flush=True)

            # ردیابی تغییر موجودی لحظه‌ای کارخانه‌های دولتی
            cur_sizes: set[str] = set()
            for p in st.get("portals", []):
                for sz in p.get("in_stock_sizes", []):
                    cur_sizes.add(f"{p.get('portal')}:{sz}")
            if cur_sizes != last_stock_sizes:
                added = sorted(cur_sizes - last_stock_sizes)
                removed = sorted(last_stock_sizes - cur_sizes)
                if added or (last_stock_sizes and removed):
                    print(f"📦 [{now_hms}] STOCK_DIFF added={added} removed={removed}", flush=True)
                    append_jsonl("STOCK_DIFF", {"added": added, "removed": removed})
                last_stock_sizes = cur_sizes

            # ردیابی رویداد جدید کاربر + تشخیص کندی
            if cur_upds > last_updates_count and last_updates_count != -1:
                evs = st.get("recent_events") or []
                delta = min(len(evs), cur_upds - last_updates_count)
                for ev in reversed(evs[:delta]):
                    slow_tag = "🐢 SLOW " if float(ev.get("latency_ms", 0)) >= SLOW_HANDLER_MS else ""
                    print(
                        f"🔔 [{now_hms}] {slow_tag}USER_EVENT updates={cur_upds} | "
                        f"chat={ev.get('chat_id')} {ev.get('label')} status={ev.get('status')} ({ev.get('latency_ms')}ms)",
                        flush=True,
                    )
                    append_jsonl("USER_EVENT", ev)
            last_updates_count = cur_upds

            # ۳. گزارش تحلیلی هر ۳۰ ثانیه
            if time.monotonic() - last_heartbeat >= HEARTBEAT_EVERY_SEC:
                perf = st.get("performance") or {}
                ps = st.get("portals_summary") or {}
                db = st.get("db_analytics") or {}
                top_act = (st.get("top_actions") or [])[:3]
                srcs_txt = ", ".join(
                    f"{s.get('source')}:{s.get('last_count')}({s.get('avg_latency_ms')}ms)"
                    for s in st.get("market_sources", [])
                ) or "none"
                summary_line = (
                    f"📊 [{now_hms}] ANALYTICS | @{st.get('bot_username')} conn={st.get('connected')} "
                    f"bale_ping={st.get('bale_api_latency_ms')}ms ram={mem_mb}MB | "
                    f"upd={cur_upds}(msg={st.get('total_messages')},cb={st.get('total_callbacks')}) "
                    f"err={cur_errs}({st.get('error_rate_pct')}%) | "
                    f"perf=avg:{perf.get('avg_ms',0)}/p95:{perf.get('p95_ms',0)}ms | "
                    f"portals={ps.get('online_now',0)}/{ps.get('tracked',0)} stock_models={ps.get('in_stock_items_now',0)} | "
                    f"users={db.get('total_users','-')} snipers={st.get('active_snipers_count',0)} | "
                    f"mkt=[{srcs_txt}] | top={top_act}"
                )
                print(summary_line, flush=True)
                append_jsonl(
                    "HEARTBEAT",
                    {
                        "uptime_sec": st.get("uptime_sec"),
                        "bale_ping_ms": st.get("bale_api_latency_ms"),
                        "ram_mb": mem_mb,
                        "updates": cur_upds,
                        "errors": cur_errs,
                        "p95_ms": perf.get("p95_ms", 0),
                        "portals_online": ps.get("online_now", 0),
                        "in_stock": ps.get("in_stock_items_now", 0),
                    },
                )
                last_heartbeat = time.monotonic()

        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
