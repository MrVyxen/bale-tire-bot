from typing import Dict, Any, Optional
from tire_api.base_client import BaseTireClient

class KalaNtswClient(BaseTireClient):
    """
    کلاینت مستقیم سامانه تخصیص تایر و کالا (kala.ntsw.ir)
    """
    def __init__(self, base_url: str = "https://kala.ntsw.ir"):
        super().__init__(base_url)

    async def login_user(self, national_id: str, password: str) -> Dict[str, Any]:
        """ورود به سامانه جامع تجارت"""
        payload = {
            "username": national_id,
            "password": password
        }
        res = await self.request("POST", "/api/Account/Login", json_data=payload)
        if res.get("ok"):
            token = res.get("data", {}).get("access_token")
            if token:
                self.auth_token = token
        return res

    async def inquire_car_quota(self, car_plate: str, vin: str) -> Dict[str, Any]:
        """استعلام برخط سهمیه خودرو از سامانه راهور"""
        params = {
            "plate": car_plate,
            "vin": vin
        }
        return await self.request("GET", "/api/Tire/InquireQuota", params=params)

    async def get_active_distribution_centers(self, province_id: int) -> Dict[str, Any]:
        """دریافت لیست مراکز توزیع و عاملیت‌های مجاز دارای موجودی"""
        return await self.request("GET", f"/api/Tire/DistributionCenters?provinceId={province_id}")

    async def submit_tire_request(self, car_id: str, size: str, brand: str, center_id: str) -> Dict[str, Any]:
        """ثبت سهمیه و حواله خرید تایر"""
        payload = {
            "carId": car_id,
            "tireSize": size,
            "brand": brand,
            "distributionCenterId": center_id
        }
        return await self.request("POST", "/api/Tire/RegisterAllocation", json_data=payload)

    async def test_ping(self) -> Dict[str, Any]:
        return await self.request("GET", "/api/HealthCheck")
