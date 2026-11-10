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
            "password": password,
        }
        res = await self.request("POST", "/api/Account/Login", json_data=payload, timeout_sec=6.0)
        if res.get("ok"):
            token = res.get("data", {}).get("access_token")
            if token:
                self.auth_token = token
        return res

    async def inquire_car_quota(self, car_plate: str, vin: str) -> Dict[str, Any]:
        """استعلام برخط سهمیه خودرو از سامانه راهور"""
        params = {"plate": car_plate, "vin": vin}
        return await self.request("GET", "/api/Tire/InquireQuota", params=params, timeout_sec=6.0)

    async def get_active_distribution_centers(self, province_id: int) -> Dict[str, Any]:
        """دریافت لیست مراکز توزیع و عاملیت‌های مجاز دارای موجودی"""
        return await self.request(
            "GET", f"/api/Tire/DistributionCenters?provinceId={province_id}", timeout_sec=6.0
        )

    async def check_available_products(self, size_keyword: Optional[str] = None) -> Dict[str, Any]:
        """بررسی زنده دسترسی‌پذیری سامانه جامع تجارت (kala.ntsw.ir)"""
        res = await self.request("GET", "/", timeout_sec=5.0)
        if not res.get("ok"):
            err = res.get("error", "")
            is_vpn = res.get("status_code") in (0, 403) or "timeout" in err.lower()
            return {
                "ok": False,
                "status_code": res.get("status_code", 0),
                "latency_ms": res.get("latency_ms", 0),
                "vpn_blocked": is_vpn,
                "items": [],
                "is_out_of_stock": True,
                "status_desc": (
                    "اتصال به سامانه جامع تجارت برقرار نشد (فیلترشکن را خاموش کرده و با اینترنت ایران تست کنید)"
                    if is_vpn
                    else f"پاسخ سامانه تجارت: کد {res.get('status_code', 0)}"
                ),
            }
        return {
            "ok": True,
            "status_code": res.get("status_code", 200),
            "latency_ms": res.get("latency_ms", 0),
            "vpn_blocked": False,
            "items": [],
            "is_out_of_stock": True,
            "status_desc": "درگاه سامانه جامع تجارت در دسترس است (برای ثبت حواله نیازمند ورود با حساب سامانه تجارت است)",
        }

    async def submit_tire_request(self, car_id: str, size: str, brand: str, center_id: str) -> Dict[str, Any]:
        """ثبت سهمیه و حواله خرید تایر"""
        payload = {
            "carId": car_id,
            "tireSize": size,
            "brand": brand,
            "distributionCenterId": center_id,
        }
        return await self.request("POST", "/api/Tire/RegisterAllocation", json_data=payload, timeout_sec=8.0)

    async def fast_add_to_cart(self, product_id: str, vehicle_id: str = "", count: int = 2, **kwargs) -> Dict[str, Any]:
        return {
            "ok": False,
            "error": "ثبت حواله در سامانه جامع تجارت نیازمند ورود با نام کاربری سامانه در kala.ntsw.ir است.",
            "latency_ms": 0,
        }

    async def test_ping(self) -> Dict[str, Any]:
        return await self.request("GET", "/", timeout_sec=5.0)
