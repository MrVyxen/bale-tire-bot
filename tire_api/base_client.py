import asyncio
import socket
import time
import urllib.parse
import aiohttp
from typing import Dict, Any, Optional
from config import DEFAULT_HEADERS

# کش کوتاه‌مدت برای جلوگیری از تکرار خطاهای DNS و حذف هشدارهای shielded future در ویندوز
_DNS_NEG_CACHE: Dict[str, float] = {}
_DNS_POS_CACHE: Dict[str, float] = {}
_DNS_TASKS: Dict[str, asyncio.Task] = {}


def _consume_task_exception(task: asyncio.Task) -> None:
    if not task.cancelled():
        try:
            task.exception()
        except Exception:
            pass


async def _probe_dns_safe(loop: asyncio.AbstractEventLoop, host: str, port: int) -> Optional[str]:
    try:
        await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return None
    except Exception as e:
        return f"DNS error for {host}: {e}"


async def safe_pre_resolve(url: str, timeout_sec: float = 4.0) -> Optional[str]:
    """پیش‌بررسی امن DNS بدون به‌جا گذاشتن exception رهاشده در shielded future"""
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except Exception:
        return None
    if not host:
        return None

    now = time.monotonic()
    if now < _DNS_NEG_CACHE.get(host, 0.0):
        return f"DNS cached failure for {host}"
    if now < _DNS_POS_CACHE.get(host, 0.0):
        return None

    # بررسی اینکه آیا IP عددی است
    try:
        socket.inet_pton(socket.AF_INET, host)
        return None
    except OSError:
        pass

    loop = asyncio.get_running_loop()
    task = _DNS_TASKS.get(host)
    if task is None or task.done():
        task = asyncio.create_task(_probe_dns_safe(loop, host, port))
        task.add_done_callback(_consume_task_exception)
        _DNS_TASKS[host] = task

    done, _ = await asyncio.wait({task}, timeout=min(timeout_sec, 4.0))
    if not done:
        _DNS_NEG_CACHE[host] = time.monotonic() + 30.0
        return f"DNS resolution timeout for {host}"

    err = task.result()
    if err:
        _DNS_NEG_CACHE[host] = time.monotonic() + 45.0
        return err

    _DNS_POS_CACHE[host] = time.monotonic() + 300.0
    return None


class BaseTireClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None
        self.auth_token: Optional[str] = None
        self.csrf_token: Optional[str] = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # فعال‌سازی کانکتور بدون قفل SSL برای سازگاری ۱۰۰٪ با سرورهای داخلی ایران
            connector = aiohttp.TCPConnector(
                ssl=False,
                limit=100,
                keepalive_timeout=120,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
                force_close=False
            )
            timeout = aiohttp.ClientTimeout(total=15, connect=5)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers=DEFAULT_HEADERS
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def get_headers(self, custom: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = DEFAULT_HEADERS.copy()
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        if self.csrf_token:
            headers["X-CSRF-TOKEN"] = self.csrf_token
            headers["X-Requested-With"] = "XMLHttpRequest"
        if custom:
            headers.update(custom)
        return headers

    async def request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        custom_headers: Optional[Dict[str, str]] = None,
        timeout_sec: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        ارسال درخواست مستقیم با محاسبه دقیق تاخیر بر حسب میلی‌ثانیه
        پشتیبانی کامل از فرم‌دیتا (data) و جیسون (json_data)
        """
        session = await self.get_session()
        url = endpoint if endpoint.startswith("http") else f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = self.get_headers(custom_headers)

        req_kwargs: Dict[str, Any] = {
            "method": method,
            "url": url,
            "json": json_data,
            "data": data,
            "params": params,
            "headers": headers,
        }
        if timeout_sec is not None:
            req_kwargs["timeout"] = aiohttp.ClientTimeout(total=timeout_sec, connect=min(timeout_sec, 4.0))

        start_time = time.perf_counter()
        dns_err = await safe_pre_resolve(url, timeout_sec=timeout_sec or 4.0)
        if dns_err:
            return {
                "ok": False,
                "status_code": 0,
                "error": dns_err,
                "text": "",
                "latency_ms": round((time.perf_counter() - start_time) * 1000, 2)
            }

        try:
            async with session.request(**req_kwargs) as response:
                latency_ms = (time.perf_counter() - start_time) * 1000

                raw_text = await response.text(errors="ignore")
                try:
                    resp_json = await response.json(content_type=None)
                except Exception:
                    resp_json = None

                return {
                    "ok": response.status in [200, 201],
                    "status_code": response.status,
                    "data": resp_json if resp_json is not None else {"raw_text": raw_text},
                    "text": raw_text,
                    "latency_ms": round(latency_ms, 2)
                }
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return {
                "ok": False,
                "status_code": 0,
                "error": str(e),
                "text": "",
                "latency_ms": round(latency_ms, 2)
            }
