import base64
from typing import Dict, Any, Optional, Tuple
from tire_api.base_client import BaseTireClient

class KavirTireClient(BaseTireClient):
    """
    کلاینت مستقیم و بهینه‌شده سامانه فروش اینترنتی کویرتایر
    """
    def __init__(self, base_url: str = "https://kavirtire.ir/esale"):
        super().__init__(base_url)

    async def send_login_otp(self, national_id: str, mobile: str) -> Dict[str, Any]:
        """ارسال پیامک کد یکبار مصرف ورود"""
        payload = {
            "nationalCode": national_id,
            "mobile": mobile
        }
        return await self.request("POST", "/api/v1/auth/otp/send", json_data=payload)

    async def verify_login_otp(self, national_id: str, mobile: str, code: str) -> Dict[str, Any]:
        """اعتبارسنجی کد پیامکی و دریافت توکن دسترسی"""
        payload = {
            "nationalCode": national_id,
            "mobile": mobile,
            "code": code
        }
        res = await self.request("POST", "/api/v1/auth/otp/verify", json_data=payload)
        if res.get("ok"):
            data = res.get("data", {})
            token = data.get("token") or data.get("accessToken")
            if token:
                self.auth_token = token
        return res

    async def get_captcha(self) -> Tuple[Optional[bytes], Optional[str]]:
        """دریافت تصویر کد کپچا و توکن امنیتی مرتبط"""
        res = await self.request("GET", "/api/v1/captcha")
        if res.get("ok"):
            data = res.get("data", {})
            b64_image = data.get("image") or data.get("imageBase64", "")
            captcha_token = data.get("token") or data.get("captchaToken", "")
            if b64_image:
                if "," in b64_image:
                    b64_image = b64_image.split(",")[1]
                img_bytes = base64.b64decode(b64_image)
                return img_bytes, captcha_token
        return None, None

    async def get_vehicles(self) -> Dict[str, Any]:
        """لیست خودروهای تایید شده کاربر"""
        return await self.request("GET", "/api/v1/vehicles")

    async def register_vehicle(self, plate: str, vin: str, chassis_no: str, green_sheet: str) -> Dict[str, Any]:
        """ثبت خودرو در سامانه جهت اخذ سهمیه"""
        payload = {
            "plate": plate,
            "vin": vin,
            "chassisNo": chassis_no,
            "greenSheetNo": green_sheet
        }
        return await self.request("POST", "/api/v1/vehicles", json_data=payload)

    async def check_available_products(self, size_keyword: Optional[str] = None) -> Dict[str, Any]:
        """بررسی فوق‌سریع موجودی محصولات و سایزها"""
        params = {}
        if size_keyword:
            params["size"] = size_keyword
        return await self.request("GET", "/api/v1/products/available", params=params)

    async def fast_add_to_cart(
        self,
        product_id: str,
        vehicle_id: str,
        count: int,
        captcha_code: str,
        captcha_token: str
    ) -> Dict[str, Any]:
        """
        ارسال بسته خرید تایر در کسری از ثانیه
        """
        payload = {
            "productId": product_id,
            "vehicleId": vehicle_id,
            "count": count,
            "captcha": captcha_code,
            "captchaToken": captcha_token
        }
        return await self.request("POST", "/api/v1/cart/items", json_data=payload)

    async def test_ping(self) -> Dict[str, Any]:
        """تست سرعت پینگ مستقیم به سرور کویرتایر"""
        return await self.request("GET", "/api/v1/health")
