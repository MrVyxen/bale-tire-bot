import ctypes
import os
import re
import sys
import time
from collections import Counter, deque
from typing import Any, Deque, Dict, List, Optional
from tire_api.utils import get_tehran_now

_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")


def redact_secrets(text: Any) -> str:
    """حذف خودکار توکن ربات یا آدرس محرمانه از متن خطاها پیش از ثبت در لاگ و داشبورد"""
    return _TOKEN_RE.sub("bot***:***", str(text or ""))


def get_process_memory_mb() -> float:
    """اندازه‌گیری دقیق حافظه مصرفی پروسه فعلی (RSS / Working Set) بدون وابستگی خارجی"""
    try:
        if sys.platform == "win32":
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            h_proc = k32.GetCurrentProcess()

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)

            for fn_loader in (
                lambda: k32.K32GetProcessMemoryInfo,
                lambda: ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo,
            ):
                try:
                    fn = fn_loader()
                    fn.argtypes = [
                        wintypes.HANDLE,
                        ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                        wintypes.DWORD,
                    ]
                    fn.restype = wintypes.BOOL
                    if fn(h_proc, ctypes.byref(counters), counters.cb):
                        return round(counters.WorkingSetSize / (1024 * 1024), 1)
                except AttributeError:
                    continue
        else:
            statm = f"/proc/{os.getpid()}/statm"
            if os.path.exists(statm):
                with open(statm, "r", encoding="utf-8") as f:
                    pages = int(f.read().split()[1])
                page_size = os.sysconf("SC_PAGE_SIZE")
                return round((pages * page_size) / (1024 * 1024), 1)
    except Exception:
        pass
    return 0.0


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(round((pct / 100.0) * (len(s) - 1))))
    return round(s[idx], 1)


class TelemetryStore:
    """هسته مرکزی تله‌متری و آنالیز دقیق عملکرد ربات، کارخانه‌ها، بازار آزاد و کاربران"""

    def __init__(self) -> None:
        self.started_monotonic: float = time.monotonic()
        self.started_tehran: str = get_tehran_now()["full_fa"]
        self.connected: bool = False
        self.bot_username: str = ""
        self.bot_name: str = ""
        self.bale_api_latency_ms: float = 0.0
        self.last_bale_check_at: Optional[str] = None

        self.total_updates: int = 0
        self.total_messages: int = 0
        self.total_callbacks: int = 0
        self.total_errors: int = 0
        self.polling_reconnects: int = 0
        self.last_event_at: Optional[str] = None
        self.last_error: Optional[str] = None

        self.handler_latencies: Deque[float] = deque(maxlen=200)
        self.action_counts: Counter = Counter()
        self.searched_sizes: Counter = Counter()
        self.unique_active_chats_session: set[int] = set()

        self.recent_events: Deque[Dict[str, Any]] = deque(maxlen=50)
        self.recent_errors: Deque[Dict[str, Any]] = deque(maxlen=30)

        # وضعیت تحلیلی هر پورتال دولتی
        self.portals: Dict[str, Dict[str, Any]] = {}
        self.last_portal_scan_at: Optional[str] = None

        # وضعیت تحلیلی منابع قیمت آزاد
        self.market_sources: Dict[str, Dict[str, Any]] = {}
        self.last_market_sizes: Deque[Dict[str, Any]] = deque(maxlen=15)

    def record_bale_health(self, ok: bool, latency_ms: float, username: str = "", first_name: str = "") -> None:
        self.connected = ok
        self.bale_api_latency_ms = round(latency_ms, 1)
        self.last_bale_check_at = get_tehran_now()["time_hms"]
        if username:
            self.bot_username = username
        if first_name:
            self.bot_name = first_name

    def record_update_start(self, kind: str, chat_id: int) -> None:
        self.total_updates += 1
        if kind == "CB":
            self.total_callbacks += 1
        else:
            self.total_messages += 1
        if chat_id:
            self.unique_active_chats_session.add(chat_id)

    def record_update_finish(
        self,
        kind: str,
        chat_id: int,
        label: str,
        latency_ms: float,
        ok: bool = True,
        error_msg: str = "",
    ) -> None:
        now_hms = get_tehran_now()["time_hms"]
        self.last_event_at = now_hms
        self.handler_latencies.append(round(latency_ms, 1))

        # استخراج نام اکشن برای شمارش دقیق محبوب‌ترین قابلیت‌ها
        action_key = label
        if label.startswith("cb="):
            raw_cb = label[3:]
            if raw_cb.startswith("mktrefresh_"):
                action_key = "mktrefresh"
            elif raw_cb.startswith("mkt_"):
                action_key = "mkt_price"
            elif raw_cb.startswith("set_portal_"):
                action_key = "set_portal"
            elif raw_cb.startswith("set_size_"):
                action_key = "set_size"
            elif raw_cb.startswith("set_count_"):
                action_key = "set_count"
            elif raw_cb.startswith("edit_"):
                action_key = "edit_profile"
            elif raw_cb.startswith("otp_send_"):
                action_key = "otp_send"
            else:
                action_key = raw_cb
        elif label.startswith("size="):
            action_key = "direct_size_query"
            self.searched_sizes[label[5:]] += 1
        self.action_counts[action_key] += 1

        if not ok:
            self.record_error(f"handler:{kind}", "HandlerException", f"chat={chat_id} {label}: {error_msg}")

        self.recent_events.appendleft({
            "time": now_hms,
            "chat_id": chat_id,
            "kind": kind,
            "label": label,
            "status": "OK" if ok else "ERR",
            "latency_ms": round(latency_ms, 1),
            **({"error": error_msg} if error_msg else {}),
        })

    def record_polling_reconnect(self, reason: str) -> None:
        self.polling_reconnects += 1

    def record_error(self, component: str, err_type: str, detail: str) -> None:
        now_hms = get_tehran_now()["time_hms"]
        self.total_errors += 1
        safe_detail = redact_secrets(detail)
        msg = f"{now_hms} [{component}] {err_type}: {safe_detail}"
        self.last_error = msg
        self.recent_errors.appendleft({
            "time": now_hms,
            "component": component,
            "type": err_type,
            "detail": safe_detail[:240],
        })

    def record_portal_probe(
        self,
        portal_key: str,
        title: str,
        ok: bool,
        latency_ms: float,
        in_stock_count: int,
        vpn_blocked: bool = False,
        anti_bot: bool = False,
        status_desc: str = "",
        in_stock_sizes: Optional[List[str]] = None,
    ) -> None:
        now_hms = get_tehran_now()["time_hms"]
        self.last_portal_scan_at = now_hms
        entry = self.portals.setdefault(
            portal_key,
            {
                "portal": portal_key,
                "title": title,
                "checks": 0,
                "ok_checks": 0,
                "uptime_pct": 0.0,
                "latencies": deque(maxlen=30),
                "avg_latency_ms": 0.0,
                "last_latency_ms": 0.0,
                "last_ok": False,
                "vpn_blocked": False,
                "anti_bot": False,
                "in_stock_count": 0,
                "in_stock_sizes": [],
                "last_stock_seen_at": None,
                "last_checked_at": None,
                "status_desc": "",
            },
        )
        entry["title"] = title or entry["title"]
        entry["checks"] += 1
        if ok:
            entry["ok_checks"] += 1
        entry["uptime_pct"] = round((entry["ok_checks"] / entry["checks"]) * 100.0, 1)
        if latency_ms and latency_ms > 0:
            entry["latencies"].append(round(latency_ms, 1))
        lats = list(entry["latencies"])
        entry["avg_latency_ms"] = round(sum(lats) / len(lats), 1) if lats else 0.0
        entry["last_latency_ms"] = round(latency_ms, 1)
        entry["last_ok"] = ok
        entry["vpn_blocked"] = vpn_blocked
        entry["anti_bot"] = anti_bot
        entry["in_stock_count"] = in_stock_count
        entry["in_stock_sizes"] = sorted(set(in_stock_sizes or []))
        if in_stock_count > 0:
            entry["last_stock_seen_at"] = now_hms
        entry["last_checked_at"] = now_hms
        entry["status_desc"] = status_desc

    def record_market_query(
        self,
        size: str,
        total_found: int,
        total_latency_ms: float,
        source_details: Dict[str, Dict[str, Any]],
        ir_median: Optional[int] = None,
        imp_median: Optional[int] = None,
    ) -> None:
        now_hms = get_tehran_now()["time_hms"]
        self.searched_sizes[size] += 1
        self.last_market_sizes.appendleft({
            "time": now_hms,
            "size": size,
            "total_found": total_found,
            "latency_ms": round(total_latency_ms, 1),
            "ir_median": ir_median,
            "imp_median": imp_median,
        })

        for src_name, info in source_details.items():
            st = info.get("status", "ok")
            cnt = int(info.get("count", 0))
            lat = float(info.get("latency_ms", 0.0))
            m = self.market_sources.setdefault(
                src_name,
                {
                    "source": src_name,
                    "queries": 0,
                    "ok_queries": 0,
                    "rate_limited_hits": 0,
                    "success_rate_pct": 0.0,
                    "latencies": deque(maxlen=30),
                    "avg_latency_ms": 0.0,
                    "last_count": 0,
                    "last_status": "unknown",
                    "last_checked_at": None,
                },
            )
            m["queries"] += 1
            if st == "ok":
                m["ok_queries"] += 1
            elif st == "rate_limited":
                m["rate_limited_hits"] += 1
            m["success_rate_pct"] = round((m["ok_queries"] / m["queries"]) * 100.0, 1)
            if lat > 0:
                m["latencies"].append(round(lat, 1))
            lats = list(m["latencies"])
            m["avg_latency_ms"] = round(sum(lats) / len(lats), 1) if lats else 0.0
            m["last_count"] = cnt
            m["last_status"] = st
            m["last_checked_at"] = now_hms

    def build_snapshot(
        self,
        active_snipers: Optional[List[int]] = None,
        db_analytics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        uptime_sec = round(time.monotonic() - self.started_monotonic, 1)
        lats = list(self.handler_latencies)
        avg_lat = round(sum(lats) / len(lats), 1) if lats else 0.0
        p50_lat = _percentile(lats, 50)
        p95_lat = _percentile(lats, 95)
        err_rate = round((self.total_errors / self.total_updates) * 100.0, 2) if self.total_updates else 0.0

        # سریال‌سازی تمیز دیکشنری پورتال‌ها و منابع بدون deque
        portals_out = []
        online_portals = 0
        total_in_stock = 0
        for pk, p in self.portals.items():
            if p["last_ok"]:
                online_portals += 1
            total_in_stock += p["in_stock_count"]
            portals_out.append({k: v for k, v in p.items() if k != "latencies"})

        sources_out = [
            {k: v for k, v in m.items() if k != "latencies"}
            for m in self.market_sources.values()
        ]

        active_list = active_snipers or []
        return {
            "status": "ok" if self.connected else "connecting",
            "tehran_now": get_tehran_now()["full_fa"],
            "started_tehran": self.started_tehran,
            "uptime_sec": uptime_sec,
            "bot_username": self.bot_username,
            "bot_name": self.bot_name,
            "connected": self.connected,
            "bale_api_latency_ms": self.bale_api_latency_ms,
            "last_bale_check_at": self.last_bale_check_at,
            "memory_mb": get_process_memory_mb(),
            "total_updates": self.total_updates,
            "total_messages": self.total_messages,
            "total_callbacks": self.total_callbacks,
            "total_errors": self.total_errors,
            "error_rate_pct": err_rate,
            "polling_reconnects": self.polling_reconnects,
            "active_session_chats": len(self.unique_active_chats_session),
            "active_snipers_count": len(active_list),
            "active_snipers": active_list,
            "performance": {
                "samples": len(lats),
                "avg_ms": avg_lat,
                "p50_ms": p50_lat,
                "p95_ms": p95_lat,
                "max_ms": max(lats) if lats else 0.0,
            },
            "top_actions": self.action_counts.most_common(10),
            "top_searched_sizes": self.searched_sizes.most_common(10),
            "portals_summary": {
                "tracked": len(portals_out),
                "online_now": online_portals,
                "in_stock_items_now": total_in_stock,
                "last_scan_at": self.last_portal_scan_at,
            },
            "portals": portals_out,
            "market_sources": sources_out,
            "recent_market_queries": list(self.last_market_sizes),
            "db_analytics": db_analytics or {},
            "last_event_at": self.last_event_at,
            "last_error": self.last_error,
            "recent_errors": list(self.recent_errors),
            "recent_events": list(self.recent_events),
        }


# نمونه سراسری مشترک در کل برنامه
telemetry = TelemetryStore()
