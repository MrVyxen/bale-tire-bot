import re
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
from tire_api.base_client import BaseTireClient
from tire_api.utils import clean_search_text, normalize_tire_size, parse_size_parts, size_to_key


class FactoryPortalClient(BaseTireClient):
    """
    کلاینت یکپارچه برای رصد زنده و واقعی کارخانه‌های فروش تایر دولتی:
    ایران تایر، یزد تایر، رازی تایر، کیان تایر، آرتاویل (گلدستون) و دنا تایر
    """

    def __init__(self, portal_key: str):
        self.portal_key = portal_key
        urls = {
            "irantire": "https://eshop.irantire.ir",
            "yazd": "https://yric.com",
            "razi": "https://razi-tire.com",
            "kian": "https://kiantire.ir",
            "artawheel": "https://artawheeltire.com",
            "dena": "https://dena-tire.com",
        }
        super().__init__(urls.get(portal_key, "https://hypertire.com"))

    async def check_available_products(self, size_keyword: Optional[str] = None) -> Dict[str, Any]:
        target_parts = parse_size_parts(size_keyword) if size_keyword else None

        if self.portal_key == "irantire":
            return await self._check_irantire(target_parts)
        if self.portal_key == "yazd":
            return await self._check_yazd(target_parts)
        if self.portal_key == "razi":
            return await self._check_razi()
        if self.portal_key == "kian":
            return await self._check_kian()
        if self.portal_key in ("artawheel", "dena"):
            return await self._check_generic(self.portal_key)

        return {
            "ok": False,
            "portal": self.portal_key,
            "items": [],
            "catalog_sizes": [],
            "is_out_of_stock": True,
            "status_desc": "پورتال ناشناخته",
            "latency_ms": 0.0,
        }

    async def _check_irantire(self, target_parts) -> Dict[str, Any]:
        res = await self.request("GET", "/", timeout_sec=6.0)
        lat = res.get("latency_ms", 0.0)
        if not res.get("ok"):
            return {
                "ok": False,
                "portal": "irantire",
                "items": [],
                "catalog_sizes": [],
                "is_out_of_stock": True,
                "status_desc": f"عدم پاسخ فروشگاه ایران‌تایر (کد {res.get('status_code', 0)})",
                "latency_ms": lat,
            }

        html = res.get("text", "")
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        if "coming soon" in title.lower() or "coming soon" in html[:4000].lower():
            return {
                "ok": True,
                "portal": "irantire",
                "items": [],
                "catalog_sizes": [],
                "is_out_of_stock": True,
                "status_desc": "فروشگاه آنلاین ایران‌تایر در حالت Coming Soon است (در انتظار بازگشایی رسمی)",
                "latency_ms": lat,
            }

        # اگر فروشگاه آنلاین باز شده باشد، محصولات واقعی آن را استخراج می‌کنیم
        items: List[Dict[str, Any]] = []
        catalog_sizes: List[str] = []
        for prod in soup.select(".product, li.product, .type-product"):
            txt = clean_search_text(prod.get_text(" ", strip=True))
            sz = normalize_tire_size(txt)
            if sz:
                catalog_sizes.append(sz)
            if ("افزودن به سبد" in txt or "خرید" in txt) and "ناموجود" not in txt:
                if target_parts and sz and parse_size_parts(sz) != target_parts:
                    continue
                price_m = re.search(r"(\d[\d,]{5,})", txt)
                price_v = int(price_m.group(1).replace(",", "")) if price_m else 0
                items.append({
                    "id": txt[:40],
                    "portal": "irantire",
                    "portal_title": "ایران تایر",
                    "brand": "ایران تایر",
                    "title": txt[:90],
                    "size": sz or "نامشخص",
                    "size_key": size_to_key(sz) if sz else "",
                    "price_toman": price_v // 10 if price_v > 50_000_000 else price_v,
                    "in_stock": True,
                    "url": "https://eshop.irantire.ir",
                })

        return {
            "ok": True,
            "portal": "irantire",
            "items": items,
            "catalog_sizes": sorted(set(catalog_sizes)),
            "is_out_of_stock": len(items) == 0,
            "status_desc": (
                f"{len(items)} محصول ایران‌تایر برای خرید باز است!"
                if items
                else "فروشگاه ایران‌تایر آنلاین است اما ظرفیت دولتی باز یافت نشد"
            ),
            "latency_ms": lat,
        }

    async def _check_yazd(self, target_parts) -> Dict[str, Any]:
        # ابتدا دسته‌بندی تایر سواری را بررسی می‌کنیم؛ اگر تایم‌اوت داد صفحه اصلی را می‌بینیم
        res = await self.request(
            "GET",
            "/product-category/%d8%aa%d8%a7%db%8c%d8%b1-%d8%b3%d9%88%d8%a7%d8%b1%db%8c/pcr/",
            timeout_sec=7.0,
        )
        if not res.get("ok"):
            res = await self.request("GET", "/", timeout_sec=5.0)
        lat = res.get("latency_ms", 0.0)
        if not res.get("ok"):
            return {
                "ok": False,
                "portal": "yazd",
                "items": [],
                "catalog_sizes": [],
                "is_out_of_stock": True,
                "status_desc": f"سایت یزدتایر پاسخ نداد (کد {res.get('status_code', 0)})",
                "latency_ms": lat,
            }

        soup = BeautifulSoup(res.get("text", ""), "html.parser")
        catalog_sizes: List[str] = []
        items: List[Dict[str, Any]] = []
        for prod in soup.select(".product, li.product"):
            txt = clean_search_text(prod.get_text(" ", strip=True))
            sz = normalize_tire_size(txt)
            if sz:
                catalog_sizes.append(sz)
            if "سبد خرید" in txt and "تومان" in txt and "ناموجود" not in txt:
                if target_parts and sz and parse_size_parts(sz) != target_parts:
                    continue
                items.append({
                    "id": txt[:40],
                    "portal": "yazd",
                    "portal_title": "یزد تایر",
                    "brand": "یزد تایر",
                    "title": txt[:90],
                    "size": sz or "",
                    "size_key": size_to_key(sz) if sz else "",
                    "price_toman": 0,
                    "in_stock": True,
                    "url": "https://yric.com/shop/",
                })

        return {
            "ok": True,
            "portal": "yazd",
            "items": items,
            "catalog_sizes": sorted(set(catalog_sizes)),
            "is_out_of_stock": len(items) == 0,
            "status_desc": (
                f"{len(items)} محصول مستقیم یزدتایر باز است!"
                if items
                else f"سایت یزدتایر آنلاین ({len(set(catalog_sizes))} سایز کاتالوگ سواری؛ فروش اینترنتی با حواله سامانه تجارت / نمایندگی)"
            ),
            "latency_ms": lat,
        }

    async def _check_razi(self) -> Dict[str, Any]:
        res = await self.request("GET", "/sales", timeout_sec=6.0)
        lat = res.get("latency_ms", 0.0)
        if not res.get("ok"):
            return {
                "ok": False,
                "portal": "razi",
                "items": [],
                "catalog_sizes": [],
                "is_out_of_stock": True,
                "status_desc": f"عدم دسترسی به سایت رازی‌تایر (کد {res.get('status_code', 0)})",
                "latency_ms": lat,
            }
        return {
            "ok": True,
            "portal": "razi",
            "items": [],
            "catalog_sizes": [],
            "is_out_of_stock": True,
            "status_desc": "سایت رازی‌تایر آنلاین است (توزیع فعلی از طریق نمایندگان مجاز و حواله سامانه تجارت)",
            "latency_ms": lat,
        }

    async def _check_kian(self) -> Dict[str, Any]:
        res = await self.request("GET", "/", timeout_sec=5.0)
        lat = res.get("latency_ms", 0.0)
        txt = res.get("text", "").lower()
        if "selva" in txt or "challenge" in txt or "jschallenge" in txt:
            return {
                "ok": True,
                "portal": "kian",
                "anti_bot": True,
                "items": [],
                "catalog_sizes": [],
                "is_out_of_stock": True,
                "status_desc": "سایت کیان‌تایر پشت سپر امنیتی ضدربات است (برای ثبت‌نام مستقیم با مرورگر kiantire.ir را باز کنید)",
                "latency_ms": lat,
            }
        if not res.get("ok"):
            return {
                "ok": False,
                "portal": "kian",
                "items": [],
                "catalog_sizes": [],
                "is_out_of_stock": True,
                "status_desc": f"عدم پاسخ کیان‌تایر (کد {res.get('status_code', 0)})",
                "latency_ms": lat,
            }
        return {
            "ok": True,
            "portal": "kian",
            "items": [],
            "catalog_sizes": [],
            "is_out_of_stock": True,
            "status_desc": "سایت کیان‌تایر آنلاین است (در حال پایش ظرفیت)",
            "latency_ms": lat,
        }

    async def _check_generic(self, key: str) -> Dict[str, Any]:
        names = {"artawheel": "آرتاویل / گلدستون", "dena": "دنا تایر"}
        label = names.get(key, key)
        res = await self.request("GET", "/", timeout_sec=4.5)
        lat = res.get("latency_ms", 0.0)
        sc = res.get("status_code", 0)
        if not res.get("ok"):
            err = res.get("error", "")
            reason = (
                "در حال به‌روزرسانی/خارج از دسترس (503)"
                if sc == 503
                else "نیازمند اینترنت ایران / عدم پاسخ در سرور فعلی"
                if sc == 0 or "timeout" in err.lower()
                else f"کد پاسخ {sc}"
            )
            return {
                "ok": False,
                "portal": key,
                "vpn_blocked": sc == 0,
                "items": [],
                "catalog_sizes": [],
                "is_out_of_stock": True,
                "status_desc": f"{label}: {reason}",
                "latency_ms": lat,
            }
        return {
            "ok": True,
            "portal": key,
            "items": [],
            "catalog_sizes": [],
            "is_out_of_stock": True,
            "status_desc": f"{label}: سایت آنلاین است (در انتظار بازگشایی فروش)",
            "latency_ms": lat,
        }

    async def fast_add_to_cart(self, product_id: str, vehicle_id: str = "", count: int = 2, **kwargs) -> Dict[str, Any]:
        return {
            "ok": False,
            "error": f"ثبت مستقیم سبد خرید در پورتال {self.portal_key} فعلاً نیازمند اتمام مراحل در سایت اصلی کارخانه است.",
            "latency_ms": 0,
        }

    async def test_ping(self) -> Dict[str, Any]:
        return await self.request("GET", "/", timeout_sec=5.0)
