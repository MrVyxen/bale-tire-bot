import base64
from typing import Dict, Any, Optional, Tuple, List
from tire_api.base_client import BaseTireClient
from tire_api.utils import normalize_tire_size, size_to_key

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
        """بررسی فوق‌سریع موجودی محصولات و سایزها در کویر تایر"""
        params = {}
        if size_keyword:
            norm = normalize_tire_size(size_keyword) or size_keyword
            params["size"] = norm

        res = await self.request("GET", "/api/v1/products/available", params=params, timeout_sec=5.5)
        status_code = res.get("status_code", 0)
        raw_txt = res.get("text", "")

        # بررسی محدودیت آی‌پی ایران (مثلاً زمان روشن بودن فیلترشکن)
        if status_code == 403 or "آی‌پی" in raw_txt or "ایران مجاز است" in raw_txt:
            res["ok"] = False
            res["vpn_blocked"] = True
            res["items"] = []
            res["is_out_of_stock"] = True
            res["status_desc"] = "دسترسی کویرتایر مسدود شد (آی‌پی غیرایرانی/VPN فعال است؛ برای اتصال فیلترشکن را خاموش کنید)"
            return res

        # در صورتی که API در دسترس نباشد صفحه اصلی /esale را بررسی می‌کنیم
        if not res.get("ok"):
            page_res = await self.request("GET", "/", timeout_sec=5.5)
            if page_res.get("status_code") == 403 or "ایران مجاز است" in page_res.get("text", ""):
                return {
                    "ok": False,
                    "status_code": 403,
                    "latency_ms": page_res.get("latency_ms", 0),
                    "vpn_blocked": True,
                    "items": [],
                    "is_out_of_stock": True,
                    "status_desc": "دسترسی کویرتایر مسدود شد (آی‌پی غیرایرانی/VPN فعال است؛ فیلترشکن را خاموش کنید)",
                }
            res["items"] = []
            res["is_out_of_stock"] = True
            res["vpn_blocked"] = False
            res["status_desc"] = f"پورتال کویرتایر فعلاً ظرفیت باز نمایش نداد (کد {status_code})"
            return res

        data = res.get("data")
        items: List[Dict[str, Any]] = []
        raw_list = data if isinstance(data, list) else (data.get("items") or data.get("products") or data.get("data") or []) if isinstance(data, dict) else []
        if isinstance(raw_list, list):
            for it in raw_list:
                if not isinstance(it, dict):
                    continue
                sz_raw = str(it.get("size") or it.get("title") or it.get("name") or "")
                norm_sz = normalize_tire_size(sz_raw) or sz_raw
                price_val = int(it.get("price") or it.get("unitPrice") or 0)
                items.append({
                    "id": str(it.get("id") or it.get("productId") or ""),
                    "portal": "kavir",
                    "portal_title": "کویر تایر",
                    "brand": "کویر تایر",
                    "title": str(it.get("title") or it.get("name") or f"کویر تایر {norm_sz}"),
                    "size": norm_sz,
                    "size_key": size_to_key(norm_sz),
                    "price_toman": price_val // 10 if price_val > 50_000_000 else price_val,
                    "in_stock": bool(it.get("available", True)),
                    "url": "https://kavirtire.ir/esale",
                })

        is_oos = len(items) == 0
        res["items"] = items
        res["is_out_of_stock"] = is_oos
        res["vpn_blocked"] = False
        res["status_desc"] = f"{len(items)} محصول در کویرتایر موجود است" if not is_oos else "ظرفیت فروش کویرتایر در این لحظه بسته است"
        return res

    async def fast_add_to_cart(
        self,
        product_id: str,
        vehicle_id: str,
        count: int,
        captcha_code: str = "",
        captcha_token: str = "",
        **kwargs
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
        return await self.request("GET", "/")
