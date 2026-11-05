import time
import aiohttp
from typing import Dict, Any, Optional
from config import DEFAULT_HEADERS

class BaseTireClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None
        self.auth_token: Optional[str] = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # ایجاد کانکتور پرسرعت TCP با قابلیت Keep-Alive طولانی و حداکثر کانکشن همزمان
            connector = aiohttp.TCPConnector(
                limit=100,
                keepalive_timeout=120,
                enable_cleanup_closed=True,
                force_close=False
            )
            timeout = aiohttp.ClientTimeout(total=10, connect=3)
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
        if custom:
            headers.update(custom)
        return headers

    async def request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        custom_headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        ارسال درخواست مستقیم با محاسبه دقیق تاخیر (Latency) بر حسب میلی‌ثانیه
        """
        session = await self.get_session()
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = self.get_headers(custom_headers)

        start_time = time.perf_counter()
        try:
            async with session.request(
                method=method,
                url=url,
                json=json_data,
                params=params,
                headers=headers
            ) as response:
                latency_ms = (time.perf_counter() - start_time) * 1000

                try:
                    data = await response.json()
                except Exception:
                    text = await response.text()
                    data = {"raw_text": text}

                return {
                    "ok": response.status in [200, 201],
                    "status_code": response.status,
                    "data": data,
                    "latency_ms": round(latency_ms, 2)
                }
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return {
                "ok": False,
                "status_code": 0,
                "error": str(e),
                "latency_ms": round(latency_ms, 2)
            }
