import json
import re
import sqlite3
import urllib.request
from collections import Counter
from pathlib import Path
from tire_api.utils import get_tehran_now

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "bot_monitor.log"
DB_PATH = BASE_DIR / "tire_bot.db"
STATUS_URL = "http://127.0.0.1:10000/status"


def analyze():
    print("=" * 72)
    print(f"🔬 گزارش آنالیز جامع رصد ربات (@tairbot) | {get_tehran_now()['full_fa']}")
    print("=" * 72)

    # ۱. وضعیت زنده از /status
    try:
        st = json.loads(urllib.request.urlopen(STATUS_URL, timeout=4.0).read().decode("utf-8"))
        perf = st.get("performance") or {}
        ps = st.get("portals_summary") or {}
        print("\n📡 ۱. وضعیت لحظه‌ای سرور و تله‌متری:")
        print(f"   • ربات: @{st.get('bot_username')} | متصل: {st.get('connected')} | آپتایم: {st.get('uptime_sec')} ثانیه")
        print(f"   • پینگ بله: {st.get('bale_api_latency_ms')} ms | حافظه مصرفی: {st.get('memory_mb')} MB")
        print(f"   • آپدیت‌ها: {st.get('total_updates')} (پیام={st.get('total_messages')}, دکمه={st.get('total_callbacks')})")
        print(f"   • خطاها: {st.get('total_errors')} (نرخ خطا={st.get('error_rate_pct')}%) | تجدید Polling={st.get('polling_reconnects')}")
        print(f"   • کارایی پردازش: avg={perf.get('avg_ms')}ms | p50={perf.get('p50_ms')}ms | p95={perf.get('p95_ms')}ms | max={perf.get('max_ms')}ms")

        print(f"\n🏭 ۲. آنالیز کارخانه‌های دولتی ({ps.get('online_now',0)}/{ps.get('tracked',0)} آنلاین | موجودی={ps.get('in_stock_items_now',0)}):")
        for p in st.get("portals", []):
            flag = "🟢" if p.get("in_stock_count", 0) > 0 else ("🟡" if p.get("last_ok") else ("📵" if p.get("vpn_blocked") else "🔴"))
            print(
                f"   {flag} {p.get('title'):<22} | uptime={p.get('uptime_pct'):>5}% | "
                f"lat={p.get('last_latency_ms'):>6}ms (avg={p.get('avg_latency_ms')}ms) | "
                f"موجودی={p.get('in_stock_count')} {p.get('in_stock_sizes') or ''}"
            )

        if st.get("market_sources"):
            print("\n💰 ۳. عملکرد موتور قیمت روز آزاد:")
            for s in st["market_sources"]:
                print(
                    f"   • {s['source']:<12} | وضعیت={s['last_status']} | نتایج={s['last_count']} | "
                    f"میانگین تاخیر={s['avg_latency_ms']}ms | موفقیت={s['success_rate_pct']}%"
                )
    except Exception as e:
        print(f"\n⚠️ عدم دسترسی به اندپوینت زنده {STATUS_URL}: {e}")

    # ۲. آنالیز خط‌به‌خط فایل bot_monitor.log
    print("\n📜 ۴. تحلیل فایل لاگ دائمی (bot_monitor.log):")
    if LOG_FILE.exists():
        lines = LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
        levels = Counter()
        err_lines = []
        latencies = []
        for ln in lines:
            m = re.search(r"\[(INFO|WARNING|ERROR|CRITICAL)\]", ln)
            if m:
                levels[m.group(1)] += 1
                if m.group(1) in ("ERROR", "WARNING", "CRITICAL"):
                    err_lines.append(ln)
            em = re.search(r"elapsed=(\d+(?:\.\d+)?)ms", ln)
            if em:
                latencies.append((float(em.group(1)), ln))
        print(f"   • کل خطوط لاگ: {len(lines)} | سطوح: {dict(levels)}")
        if latencies:
            latencies.sort(reverse=True)
            print("   • کندترین پردازش‌های ثبت‌شده:")
            for lat_val, raw in latencies[:5]:
                print(f"     - {lat_val}ms: {raw}")
        if err_lines:
            print("   • آخرین خطاها و هشدارها:")
            for e_ln in err_lines[-5:]:
                print(f"     - {e_ln}")
    else:
        print("   • فایل bot_monitor.log هنوز ایجاد نشده است.")

    # ۳. آنالیز دیتابیس SQLite
    print("\n🗄 ۵. آنالیز دیتابیس (tire_bot.db):")
    if DB_PATH.exists():
        con = sqlite3.connect(DB_PATH)
        users_cnt = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        ready_cnt = con.execute(
            "SELECT COUNT(*) FROM users WHERE national_id IS NOT NULL AND national_id != '' AND mobile IS NOT NULL AND mobile != ''"
        ).fetchone()[0]
        portals = con.execute("SELECT target_portal, COUNT(*) FROM users GROUP BY target_portal").fetchall()
        actions = con.execute("SELECT action, status, COUNT(*), ROUND(AVG(latency_ms),1) FROM logs GROUP BY action, status").fetchall()
        price_cnt = 0
        try:
            price_cnt = con.execute("SELECT COUNT(*) FROM market_price_history").fetchone()[0]
        except Exception:
            pass
        con.close()
        print(f"   • کل کاربران: {users_cnt} | دارای مدارک پایه: {ready_cnt} | انتخاب پورتال: {portals}")
        print(f"   • آمار اکشن‌های ثبت‌شده: {actions or 'هنوز ثبت نشده'}")
        print(f"   • رکوردهای تاریخچه قیمت آزاد: {price_cnt}")
    print("\n" + "=" * 72)


if __name__ == "__main__":
    analyze()
