import re
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup
from tire_api.base_client import BaseTireClient

class BarezTireClient(BaseTireClient):
    """
    کلاینت مستقیم و واقعی سامانه فروش اینترنتی گروه صنعتی بارز (shop.barez.org)
    مبتنی بر تحلیل عمیق wizard.js و سیستم رزرواسیون لایووایر
    """
    def __init__(self, base_url: str = "https://shop.barez.org"):
        super().__init__(base_url)
        self.csrf_token: Optional[str] = None

    async def init_session(self) -> Dict[str, Any]:
        """دریافت سشن اولیه و استخراج توکن ضدجعل CSRF"""
        res = await self.request("GET", "/start-live")
        if res.get("ok"):
            html = res.get("text", "")
            soup = BeautifulSoup(html, "html.parser")
            meta_csrf = soup.find("meta", {"name": "csrf-token"})
            if meta_csrf and meta_csrf.get("content"):
                self.csrf_token = meta_csrf["content"]
                self.session.headers.update({"X-CSRF-TOKEN": self.csrf_token})
        return res

    async def send_login_otp(self, phone: str) -> Dict[str, Any]:
        """ارسال کد یکبار مصرف پیامکی جهت ورود به بارز (/customer/verifylogin)"""
        if not self.csrf_token:
            await self.init_session()
        data = {"phone": phone}
        return await self.request("POST", "/customer/verifylogin", data=data)

    async def verify_login_otp(self, phone: str, otp_code: str) -> Dict[str, Any]:
        """تایید پیامک و لاگین به حساب بارز (/customer/login)"""
        if not self.csrf_token:
            await self.init_session()
        data = {
            "phone": phone,
            "password": otp_code
        }
        return await self.request("POST", "/customer/login", data=data)

    async def resend_otp(self, phone: str, otp_type: str = "customer") -> Dict[str, Any]:
        """ارسال مجدد کد تایید (/resendVerifyCode)"""
        data = {
            "phone": phone,
            "type": otp_type
        }
        return await self.request("POST", "/resendVerifyCode", data=data)

    async def get_address_by_postal_code(self, postal_code: str) -> Dict[str, Any]:
        """استعلام مشخصات جغرافیایی با کدپستی ۱۰ رقمی (/wizard/getDataByPostalCode)"""
        data = {"postal_code": postal_code}
        return await self.request("POST", "/wizard/getDataByPostalCode", data=data)

    async def search_inventory(
        self,
        ring: str = "",
        size: str = "",
        car: str = "",
        center_id: str = "",
        search_type: str = "product"
    ) -> Dict[str, Any]:
        """جستجوی برخط لاستیک‌های موجود بر اساس سایز و رینگ (/wizard/search)"""
        params = {
            "search_type": search_type,
            "ring": ring,
            "size": size,
            "car": car,
            "center_id": center_id
        }
        return await self.request("GET", "/wizard/search", params=params)

    async def step_wizard(self, step_name: str, payload_data: Dict[str, Any]) -> Dict[str, Any]:
        """گام‌های مختلف فرآیند خرید شامل customer, verify_mobile, product, detail, end (/wizard/step)"""
        data = {"step": step_name, **payload_data}
        return await self.request("GET", "/wizard/step", params=data)

    async def fast_reserve_tire(
        self,
        product_id: str,
        count: int,
        center_id: str,
        schedule_id: str = "",
        time_id: str = ""
    ) -> Dict[str, Any]:
        """رزرو فوری تایر در کسری از ثانیه (/wizard/reserve)"""
        data = {
            "product_id": product_id,
            "count": str(count),
            "center_id": center_id,
            "schedule_id": schedule_id,
            "time_id": time_id
        }
        return await self.request("POST", "/wizard/reserve", data=data)

    async def test_ping(self) -> Dict[str, Any]:
        """تست آنلاین بودن سامانه بارز"""
        return await self.request("GET", "/start-live")
