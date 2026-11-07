import re
import logging
from typing import Dict, Any, Optional, List
from bs4 import BeautifulSoup
from tire_api.base_client import BaseTireClient

logger = logging.getLogger("BarezClient")

class BarezTireClient(BaseTireClient):
    """
    کلاینت مستقیم و کاملاً واقعی سامانه فروش اینترنتی گروه صنعتی بارز (shop.barez.org)
    مبتنی بر استخراج اختصاصی wizard.js، لاگین پیامکی و رزرواسیون فوری
    """
    def __init__(self, base_url: str = "https://shop.barez.org"):
        super().__init__(base_url)

    async def init_session(self) -> Dict[str, Any]:
        """دریافت سشن اولیه و استخراج توکن ضدجعل CSRF از تگ‌های متای صفحه اصلی"""
        res = await self.request("GET", "/start-live")
        if res.get("ok"):
            html = res.get("text", "")
            soup = BeautifulSoup(html, "html.parser")
            meta_csrf = soup.find("meta", {"name": "csrf-token"})
            if meta_csrf and meta_csrf.get("content"):
                self.csrf_token = meta_csrf["content"]
                logger.info(f"Barez CSRF initialized: {self.csrf_token[:10]}...")
        return res

    async def send_login_otp(self, phone: str) -> Dict[str, Any]:
        """ارسال واقعی کد یکبار مصرف پیامکی به تلفن همراه کاربر (/customer/verifylogin)"""
        if not self.csrf_token:
            await self.init_session()

        custom_h = {
            "Referer": f"{self.base_url}/start-live",
            "X-Requested-With": "XMLHttpRequest"
        }
        res = await self.request(
            method="POST",
            endpoint="/customer/verifylogin",
            data={"phone": phone},
            custom_headers=custom_h
        )
        return res

    async def verify_login_otp(self, phone: str, otp_code: str) -> Dict[str, Any]:
        """تایید کد پیامکی و دریافت سشن ورود به حساب بارز (/customer/login)"""
        if not self.csrf_token:
            await self.init_session()

        custom_h = {
            "Referer": f"{self.base_url}/start-live",
            "X-Requested-With": "XMLHttpRequest"
        }
        res = await self.request(
            method="POST",
            endpoint="/customer/login",
            data={"phone": phone, "password": otp_code},
            custom_headers=custom_h
        )
        raw_text = res.get("text", "").strip()
        # در صورت موفقیت سرور بارز عبارت "success" را برمی‌گرداند
        is_success = "success" in raw_text.lower()
        res["login_success"] = is_success
        return res

    async def check_available_products(self, size_keyword: str = "185_65_14") -> Dict[str, Any]:
        """
        استعلام زنده و واقعی موجودی انبار تایر بارز
        """
        if not self.csrf_token:
            await self.init_session()

        # استخراج شماره رینگ از سایز تایر (مثلا 14 از 185_65_14)
        ring = "14"
        parts = size_keyword.replace("/", "_").replace("-", "_").split("_")
        if len(parts) >= 3:
            ring = parts[2]
        elif "13" in size_keyword:
            ring = "13"
        elif "15" in size_keyword:
            ring = "15"
        elif "16" in size_keyword:
            ring = "16"

        custom_h = {
            "Referer": f"{self.base_url}/start-live",
            "X-Requested-With": "XMLHttpRequest"
        }
        params = {
            "search_type": "product",
            "ring": ring
        }

        res = await self.request(
            method="GET",
            endpoint="/wizard/search",
            params=params,
            custom_headers=custom_h
        )

        items: List[Dict[str, Any]] = []
        is_out_of_stock = True
        status_desc = "اتمام موجودی در انبار بارز"

        if res.get("ok"):
            html = res.get("data", {}).get("html", "") or res.get("text", "")
            if "اتمام موجودی" not in html and ("change-product-count" in html or "reserve-check" in html):
                is_out_of_stock = False
                status_desc = "سهمیه باز است! موجودی فعال یافت شد."
                # استخراج اطلاعات تایرها از HTML
                soup = BeautifulSoup(html, "html.parser")
                for select in soup.find_all("select", class_=re.compile(r"change-product-count")):
                    p_id = select.get("data-id") or select.get("name")
                    price = select.get("data-price", "0")
                    items.append({
                        "id": p_id,
                        "price": price,
                        "ring": ring,
                        "title": f"تایر رینگ {ring} بارز"
                    })

        res["items"] = items
        res["is_out_of_stock"] = is_out_of_stock
        res["status_desc"] = status_desc
        return res

    async def fast_reserve_tire(
        self,
        product_id: str,
        count: int = 2,
        center_id: str = "1",
        schedule_id: str = "1",
        time_id: str = "1"
    ) -> Dict[str, Any]:
        """
        رزرو ضربتی و قفل کردن تایر در انبار بارز (/wizard/reserve)
        """
        if not self.csrf_token:
            await self.init_session()

        custom_h = {
            "Referer": f"{self.base_url}/start-live",
            "X-Requested-With": "XMLHttpRequest"
        }
        form_data = {
            "product_id": str(product_id),
            "count": str(count),
            "center_id": str(center_id),
            "schedule_id": str(schedule_id),
            "time_id": str(time_id)
        }
        return await self.request(
            method="POST",
            endpoint="/wizard/reserve",
            data=form_data,
            custom_headers=custom_h
        )

    async def fast_add_to_cart(
        self,
        product_id: str,
        vehicle_id: str,
        count: int,
        **kwargs
    ) -> Dict[str, Any]:
        """سازگاری با رابط مشترک اسنایپر برای افزودن به سبد و رزرو"""
        return await self.fast_reserve_tire(product_id=product_id, count=count)

    async def get_captcha(self):
        """بارز در مرحله رزرو وب از کپچای تصویری مرسوم استفاده نمی‌کند و توکن CSRF و پیامک دارد"""
        return None, None

    async def test_ping(self) -> Dict[str, Any]:
        """تست آنلاین بودن و پینگ واقعی به سرور مرکزی بارز"""
        return await self.request("GET", "/start-live")
