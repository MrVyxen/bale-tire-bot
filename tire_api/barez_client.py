from typing import Dict, Any, Optional
from tire_api.base_client import BaseTireClient

class BarezTireClient(BaseTireClient):
    """
    کلاینت مستقیم سامانه توزیع اینترنتی گروه صنعتی بارز
    """
    def __init__(self, base_url: str = "https://pos.barez.org"):
        super().__init__(base_url)

    async def send_otp(self, mobile: str, national_id: str) -> Dict[str, Any]:
        """ارسال کد ورود پیامکی سامانه بارز"""
        payload = {
            "cellphone": mobile,
            "nationalCode": national_id
        }
        return await self.request("POST", "/api/v1/Account/SendVerificationCode", json_data=payload)

    async def verify_otp(self, mobile: str, code: str) -> Dict[str, Any]:
        """تایید کد و دریافت توکن نشست"""
        payload = {
            "cellphone": mobile,
            "verificationCode": code
        }
        res = await self.request("POST", "/api/v1/Account/VerifyCode", json_data=payload)
        if res.get("ok"):
            token = res.get("data", {}).get("token")
            if token:
                self.auth_token = token
        return res

    async def check_stock(self, size_id: Optional[str] = None) -> Dict[str, Any]:
        """بررسی ظرفیت‌های آزاد استان‌ها و سایزها"""
        params = {}
        if size_id:
            params["sizeId"] = size_id
        return await self.request("GET", "/api/v1/Store/GetAvailableTires", params=params)

    async def reserve_tire(self, item_id: str, car_plate: str, vin: str) -> Dict[str, Any]:
        """ثبت سهمیه و رزرو نوبت دریافت"""
        payload = {
            "itemId": item_id,
            "carPlate": car_plate,
            "vin": vin
        }
        return await self.request("POST", "/api/v1/Order/Reserve", json_data=payload)

    async def test_ping(self) -> Dict[str, Any]:
        return await self.request("GET", "/api/v1/General/Status")
