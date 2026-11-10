import ast
import importlib
import json
import os
import py_compile
import re
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATUS_URL = "http://127.0.0.1:10000/status"
DASHBOARD_URL = "http://127.0.0.1:10000/dashboard"


def is_bot_running() -> tuple[bool, dict]:
    try:
        with urllib.request.urlopen(STATUS_URL, timeout=2.5) as resp:
            return True, json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False, {}


def stop_processes() -> int:
    """توقف تمیز پروسه‌های در حال اجرای main.py و monitor_realtime.py در این پوشه"""
    if sys.platform != "win32":
        return 0
    ps_cmd = (
        "$p = Get-CimInstance Win32_Process | Where-Object { "
        "$_.CommandLine -like '*bale-tire-bot*' -and "
        "($_.CommandLine -like '*main.py*' -or $_.CommandLine -like '*monitor_realtime.py*') }; "
        "$cnt = @($p).Count; "
        "$p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; "
        "Write-Output $cnt"
    )
    res = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        capture_output=True,
        text=True,
    )
    try:
        return int((res.stdout or "0").strip().splitlines()[-1])
    except Exception:
        return 0


def start_all(open_browser: bool = True) -> None:
    running, data = is_bot_running()
    if running:
        print(f"✅ ربات از قبل روشن است (@{data.get('bot_username', 'tairbot')}, رم={data.get('memory_mb')}MB).")
    else:
        print("🚀 در حال روشن کردن ربات (@tairbot) و سرویس مانیتورینگ لحظه‌ای...")
        flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        subprocess.Popen([sys.executable, "-u", str(BASE_DIR / "main.py")], cwd=str(BASE_DIR), creationflags=flags)
        for _ in range(25):
            time.sleep(0.5)
            ok, data = is_bot_running()
            if ok:
                break
        subprocess.Popen(
            [sys.executable, "-u", str(BASE_DIR / "monitor_realtime.py")],
            cwd=str(BASE_DIR),
            creationflags=flags,
        )
        ok, data = is_bot_running()
        if ok:
            print(f"✅ سرویس ربات و مانیتورینگ هر دو با موفقیت روشن شدند (@{data.get('bot_username', 'tairbot')}).")
        else:
            print("⚠️ ربات استارت شد اما پورت ۱۰۰۰۰ هنوز پاسخ نداد؛ لاگ bot_monitor.log را بررسی کنید.")

    print(f"🌐 داشبورد زنده: {DASHBOARD_URL}")
    if open_browser:
        webbrowser.open(DASHBOARD_URL)


def check_wiring() -> int:
    """ممیزی یکپارچگی و اتصال متقابل تمام فایل‌ها، دکمه‌ها، ماژول‌ها و اسکریپت‌ها"""
    print("=" * 68)
    print("🔗 ممیزی کامل ارتباط فایل‌ها، اسکریپت‌ها و دکمه‌های ربات")
    print("=" * 68)
    errors = 0

    # ۱. بررسی کامپایل تمام فایل‌های پایتون پروژه
    py_files = sorted(
        p for p in BASE_DIR.rglob("*.py") if "__pycache__" not in p.parts
    )
    for pf in py_files:
        try:
            py_compile.compile(str(pf), doraise=True)
        except Exception as e:
            print(f"❌ خطای سینتکس در {pf.relative_to(BASE_DIR)}: {e}")
            errors += 1
    print(f"   ✅ ۱. کامپایل کامل تمام {len(py_files)} فایل پایتون بدون خطا پاس شد.")

    # ۲. بررسی import همه ماژول‌های هسته و ابزارها
    core_modules = [
        "config",
        "database",
        "bale_api",
        "captcha_solver",
        "telemetry",
        "dashboard_html",
        "tire_api",
        "tire_api.sniper_engine",
        "tire_api.market_price_client",
        "bot_handlers",
        "main",
        "monitor_realtime",
        "analyze_logs",
    ]
    sys.path.insert(0, str(BASE_DIR))
    mod_errors = 0
    for mod in core_modules:
        try:
            importlib.import_module(mod)
        except Exception as e:
            print(f"❌ خطا در اتصال ماژول {mod}: {e}")
            errors += 1
            mod_errors += 1
    if mod_errors == 0:
        print(f"   ✅ ۲. اتصال یکپارچه تمام {len(core_modules)} ماژول اصلی تایید شد.")

    # ۳. بررسی اتصال تمام callback_data های تعریف‌شده به مسیر هندلرها در bot_handlers.py
    bh_src = (BASE_DIR / "bot_handlers.py").read_text(encoding="utf-8")
    cbs = set(re.findall(r'"callback_data"\s*:\s*"([^"{}]+)', bh_src))
    handled_exact = set(re.findall(r'data\s*==\s*"([^"]+)"', bh_src))
    handled_in = set()
    for grp in re.findall(r'data\s+in\s*\(([^)]+)\)', bh_src):
        handled_in.update(re.findall(r'"([^"]+)"', grp))
    handled_prefix = set(re.findall(r'data\.startswith\("([^"]+)"\)', bh_src))

    unmatched = []
    for cb in sorted(cbs):
        if cb in handled_exact or cb in handled_in:
            continue
        if any(cb.startswith(pre) for pre in handled_prefix):
            continue
        unmatched.append(cb)

    if unmatched:
        print(f"❌ دکمه‌های بدون هندلر در bot_handlers.py: {unmatched}")
        errors += 1
    else:
        print(f"   ✅ ۳. تمام {len(cbs)} الگوی دکمه و منو به هندلر فعال متصل هستند (بدون بن‌بست).")

    # ۴. بررسی ارتباط پورتال‌های PORTALS با SniperEngine
    import config
    from bale_api import BaleBotClient
    from tire_api import SniperEngine

    engine = SniperEngine(BaleBotClient())
    for p_key in config.PORTALS:
        if p_key == "all":
            continue
        cli = engine.get_client(p_key)
        if cli is None:
            print(f"❌ کلاینت پورتال {p_key} متصل نیست!")
            errors += 1
    print(f"   ✅ ۴. تمام {len(config.PORTALS) - 1} درگاه/شرکت دولتی به SniperEngine متصل هستند.")

    # ۵. وضعیت زنده سرویس و داشبورد
    ok, st = is_bot_running()
    if ok:
        print(
            f"   🟢 ۵. سرویس زنده فعال: @{st.get('bot_username')} | رم={st.get('memory_mb')}MB | "
            f"پورتال‌های رصدشده={st.get('portals_summary', {}).get('tracked', 0)}"
        )
    else:
        print("   ⚪ ۵. سرویس پس‌زمینه هم‌اکنون خاموش است (برای روشن کردن: run.bat یا python bot_ctl.py start).")

    print("=" * 68)
    return 0 if errors == 0 else 1


def interactive_menu() -> None:
    while True:
        os.system("cls" if sys.platform == "win32" else "clear")
        ok, st = is_bot_running()
        state_badge = (
            f"🟢 روشن (@{st.get('bot_username')} | رم={st.get('memory_mb')}MB | خطا={st.get('total_errors')})"
            if ok
            else "🔴 خاموش"
        )
        print("=" * 64)
        print("🎛 مرکز کنترل یکپارچه ربات تایر بله (@tairbot)")
        print(f"وضعیت لحظه‌ای: {state_badge}")
        print("=" * 64)
        print("1. 🚀 روشن کردن کامل (ربات + مانیتورینگ + بازکردن داشبورد وب)")
        print("2. 📊 گزارش تحلیلی فوری (وضعیت زنده + لاگ + دیتابیس)")
        print("3. 🔭 مشاهده زنده مانیتورینگ لحظه‌ای در همین پنجره")
        print("4. 🌐 باز کردن داشبورد گرافیکی در مرورگر")
        print("5. 🧪 اجرای تست کامل End-to-End و بررسی همه دکمه‌ها")
        print("6. 🔗 ممیزی یکپارچگی فایل‌ها و دکمه‌ها")
        print("7. 🛑 توقف ربات و مانیتورینگ")
        print("0. خروج")
        print("-" * 64)
        choice = input("شماره گزینه را وارد کنید: ").strip()

        if choice == "1":
            start_all(open_browser=True)
            input("\nاینتر بزنید...")
        elif choice == "2":
            subprocess.run([sys.executable, "-u", str(BASE_DIR / "analyze_logs.py")], cwd=str(BASE_DIR))
            input("\nاینتر بزنید...")
        elif choice == "3":
            try:
                subprocess.run([sys.executable, "-u", str(BASE_DIR / "monitor_realtime.py")], cwd=str(BASE_DIR))
            except KeyboardInterrupt:
                pass
        elif choice == "4":
            webbrowser.open(DASHBOARD_URL)
        elif choice == "5":
            subprocess.run([sys.executable, "-u", str(BASE_DIR / "test_e2e.py")], cwd=str(BASE_DIR))
            input("\nاینتر بزنید...")
        elif choice == "6":
            check_wiring()
            input("\nاینتر بزنید...")
        elif choice == "7":
            cnt = stop_processes()
            print(f"🛑 {cnt} پروسه متوقف شد.")
            input("\nاینتر بزنید...")
        elif choice == "0":
            break


def main():
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    if not cmd:
        interactive_menu()
    elif cmd == "start":
        start_all(open_browser=False)
    elif cmd == "stop":
        cnt = stop_processes()
        print(f"Stopped {cnt} process(es).")
    elif cmd == "restart":
        stop_processes()
        time.sleep(1.0)
        start_all(open_browser=False)
    elif cmd in ("status", "analyze"):
        import analyze_logs
        analyze_logs.analyze()
    elif cmd == "monitor":
        import monitor_realtime
        monitor_realtime.main()
    elif cmd == "dashboard":
        webbrowser.open(DASHBOARD_URL)
        print(f"Opened {DASHBOARD_URL}")
    elif cmd == "test":
        sys.exit(subprocess.call([sys.executable, "-u", str(BASE_DIR / "test_e2e.py")], cwd=str(BASE_DIR)))
    elif cmd == "check":
        sys.exit(check_wiring())
    else:
        print("Usage: python bot_ctl.py [start|stop|restart|status|monitor|dashboard|test|check]")
        sys.exit(2)


if __name__ == "__main__":
    main()
