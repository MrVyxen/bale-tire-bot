import asyncio
import logging
import re
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
from tire_api.base_client import BaseTireClient
from tire_api.utils import (
    clean_search_text,
    normalize_tire_size,
    parse_size_parts,
    size_to_key,
)

logger = logging.getLogger("HyperTireClient")

_BRAND_FA_MAP = {
    "barez": "بارز",
    "kavir": "کویر تایر",
    "kavir-tire": "کویر تایر",
    "kavir tire": "کویر تایر",
    "yazd": "یزد تایر",
    "irantire": "ایران تایر",
    "iran-tire": "ایران تایر",
    "razi": "رازی تایر",
    "goldstone": "گلدستون",
    "dena": "دنا تایر",
    "kian": "کیان تایر",
}


class HyperTireClient(BaseTireClient):
    """
    کلاینت مستقیم سامانه هایپرتایر (hypertire.com)
    پشتیبانی از رصد لحظه‌ای بخش تایر دولتی (/tires/dolati)، استعلام قیمت بازار آزاد (/tires/)
    و افزودن خودکار به سبد خرید (/basket/item/).
    """

    def __init__(self, base_url: str = "https://hypertire.com"):
        super().__init__(base_url)

    @staticmethod
    def _parse_brand(card, href: str) -> str:
        # 1. از آدرس محصول مثل /tires/Barez/HT-2258/
        parts = [p for p in (href or "").split("/") if p]
        if len(parts) >= 2 and parts[0].lower() == "tires":
            slug = parts[1].strip()
            mapped = _BRAND_FA_MAP.get(slug.lower())
            if mapped:
                return mapped
            return slug

        # 2. از تگ img داخل کارت
        for img in card.find_all("img", alt=True):
            alt = img.get("alt", "").strip()
            if alt and alt.lower() != "snapp icon" and "لاستیک" not in alt:
                return _BRAND_FA_MAP.get(alt.lower(), alt)
        return "نامشخص"

    @classmethod
    def _parse_cards(cls, html_text: str) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html_text or "", "html.parser")
        cards = soup.find_all("neo-component-products-card")
        items: List[Dict[str, Any]] = []

        for card in cards:
            text_all = clean_search_text(card.get_text(" ", strip=True))
            h4 = card.find("h4")
            raw_size = clean_search_text(h4.get_text(strip=True)) if h4 else ""
            if not raw_size:
                continue

            norm_size = normalize_tire_size(raw_size) or raw_size.upper()
            size_key = size_to_key(norm_size)

            h3 = card.find("h3")
            model_name = clean_search_text(h3.get_text(strip=True)) if h3 else ""

            link_el = card.find("a", href=re.compile(r"^/tires/[^/]+/"))
            href = link_el.get("href", "") if link_el else ""
            product_url = f"https://hypertire.com{href}" if href else "https://hypertire.com/tires/dolati"
            brand = cls._parse_brand(card, href)

            # سال تولید
            b_tag = card.find("b")
            year = clean_search_text(b_tag.get_text(strip=True)) if b_tag else ""

            # قیمت واحد (تومان)
            price_toman = 0
            p_price = card.find("p", class_="price")
            if p_price:
                attr_price = p_price.get("price")
                if attr_price and str(attr_price).isdigit():
                    price_toman = int(attr_price)
                else:
                    digits = re.sub(r"\D", "", clean_search_text(p_price.get_text()))
                    if digits:
                        price_toman = int(digits)

            # شناسه سلکتور جهت ارسال سبد خرید
            sel_input = card.find("input", {"name": "selector"})
            selector = sel_input.get("value", "").strip() if sel_input else ""
            if not selector:
                btn = card.find("button", attrs={"selector": True})
                if btn:
                    selector = btn.get("selector", "").strip()

            # موجودی و وضعیت خرید
            has_add_btn = ("اضافه به سبد خرید" in text_all) or ("سبد خرید" in text_all)
            is_oos_badge = "نا موجود" in text_all or "ناموجود" in text_all
            in_stock = bool(has_add_btn and not is_oos_badge and price_toman > 0)

            # تعداد موجودی یا سقف سفارش
            remaining_text = ""
            lbl = card.find("span", class_=re.compile(r"label"))
            if lbl:
                remaining_text = clean_search_text(lbl.get_text(strip=True))
            max_qty = 0
            count_sel = card.find("select", {"name": "count"})
            if count_sel:
                opts = [int(clean_search_text(o.get("value", "0"))) for o in count_sel.find_all("option") if clean_search_text(o.get("value", "")).isdigit()]
                if opts:
                    max_qty = max(opts)

            items.append({
                "id": selector or href,
                "selector": selector,
                "portal": "hypertire",
                "portal_title": "هایپرتایر دولتی",
                "brand": brand,
                "model": model_name,
                "title": f"{brand} {model_name}".strip(),
                "size": norm_size,
                "size_key": size_key,
                "year": year,
                "price_toman": price_toman,
                "in_stock": in_stock,
                "remaining_text": remaining_text,
                "max_qty": max_qty,
                "url": product_url,
            })

        return items

    async def scan_dolati_inventory(self, include_catalog_pages: int = 3) -> Dict[str, Any]:
        """
        دریافت موجودی زنده بخش تایر دولتی هایپرتایر.
        صفحه ۱ همیشه اقلام دارای موجودی (in_stock) را در صدر نمایش می‌دهد.
        """
        res1 = await self.request("GET", "/tires/dolati", timeout_sec=10.0)
        if not res1.get("ok"):
            await asyncio.sleep(0.35)
            res1 = await self.request("GET", "/tires/dolati", timeout_sec=10.0)
        if not res1.get("ok"):
            return {
                "ok": False,
                "latency_ms": res1.get("latency_ms", 0),
                "in_stock_items": [],
                "catalog_items": [],
                "status_desc": f"خطا در اتصال به هایپرتایر (کد {res1.get('status_code', 0)})",
            }

        all_items = self._parse_cards(res1.get("text", ""))
        max_lat = res1.get("latency_ms", 0.0)

        if include_catalog_pages > 1:
            extra_tasks = [
                self.request("GET", "/tires/dolati", params={"page": str(pg)})
                for pg in range(2, include_catalog_pages + 1)
            ]
            extra_res = await asyncio.gather(*extra_tasks, return_exceptions=True)
            for er in extra_res:
                if isinstance(er, dict) and er.get("ok"):
                    all_items.extend(self._parse_cards(er.get("text", "")))

        in_stock_items = [it for it in all_items if it["in_stock"]]
        return {
            "ok": True,
            "latency_ms": max_lat,
            "in_stock_items": in_stock_items,
            "catalog_items": all_items,
            "status_desc": (
                f"{len(in_stock_items)} مدل لاستیک دولتی هم‌اکنون موجود و آماده خرید است"
                if in_stock_items
                else "در این لحظه همه سایزهای دولتی ناموجود است (در انتظار شارژ)"
            ),
        }

    async def check_available_products(self, size_keyword: str = "185_65_14") -> Dict[str, Any]:
        """بررسی زنده موجودی دولتی هایپرتایر برای یک سایز مشخص"""
        norm_size = normalize_tire_size(size_keyword) or clean_search_text(size_keyword)
        parts = parse_size_parts(norm_size)

        res = await self.request("GET", "/tires/dolati", params={"search": norm_size})
        if not res.get("ok"):
            return {
                "ok": False,
                "status_code": res.get("status_code", 0),
                "latency_ms": res.get("latency_ms", 0),
                "items": [],
                "is_out_of_stock": True,
                "status_desc": "خطا در ارتباط با هایپرتایر",
            }

        parsed = self._parse_cards(res.get("text", ""))
        # فیلتر سخت‌گیرانه سایز تا محصول غیرمرتبط شمارش نشود
        matched_in_stock: List[Dict[str, Any]] = []
        for it in parsed:
            if not it["in_stock"]:
                continue
            if parts:
                it_parts = parse_size_parts(it["size"])
                if it_parts == parts:
                    matched_in_stock.append(it)
            elif norm_size.upper() in it["size"].upper():
                matched_in_stock.append(it)

        is_oos = len(matched_in_stock) == 0
        return {
            "ok": True,
            "status_code": res.get("status_code", 200),
            "latency_ms": res.get("latency_ms", 0),
            "items": matched_in_stock,
            "is_out_of_stock": is_oos,
            "status_desc": (
                f"{len(matched_in_stock)} مورد دولتی برای سایز {norm_size} در هایپرتایر موجود است!"
                if not is_oos
                else f"سایز {norm_size} در این لحظه در هایپرتایر دولتی ناموجود است"
            ),
        }

    async def fast_add_to_cart(
        self,
        product_id: str,
        vehicle_id: str = "",
        count: int = 2,
        **kwargs,
    ) -> Dict[str, Any]:
        """ارسال واقعی درخواست افزودن لاستیک دولتی به سبد خرید هایپرتایر (/basket/item/)"""
        # دریافت کوکی سشن قبل از ارسال POST
        await self.request("GET", "/tires/dolati")
        custom_h = {
            "Referer": f"{self.base_url}/tires/dolati",
            "X-Requested-With": "XMLHttpRequest",
        }
        res = await self.request(
            method="POST",
            endpoint="/basket/item/",
            data={"selector": str(product_id), "count": str(count)},
            custom_headers=custom_h,
        )
        res["checkout_url"] = f"{self.base_url}/basket/"
        return res

    async def search_free_market(self, norm_size: str) -> List[Dict[str, Any]]:
        """استعلام زنده قیمت آزاد تایر از فروشگاه هایپرتایر (/tires/?search=...)"""
        parts = parse_size_parts(norm_size)
        if not parts:
            return []
        res = await self.request("GET", "/tires/", params={"search": norm_size})
        if not res.get("ok"):
            return []

        cards = self._parse_cards(res.get("text", ""))
        offers: List[Dict[str, Any]] = []
        for it in cards:
            if not it["in_stock"]:
                continue
            it_parts = parse_size_parts(it["size"])
            if it_parts != parts:
                continue
            offers.append({
                "source": "هایپرتایر",
                "title": f"لاستیک {it['brand']} {it['model']} سایز {it['size']} (تولید {it['year']})" if it["year"] else f"لاستیک {it['brand']} {it['model']} سایز {it['size']}",
                "brand": it["brand"],
                "year": it["year"],
                "shop_name": "هایپرتایر",
                "price_toman": it["price_toman"],
                "pack_count": 1,  # قیمت هر کارت در هایپرتایر دقیقاً برای ۱ حلقه است
                "unit_price_toman": it["price_toman"],
                "url": it["url"],
            })
        return offers

    async def test_ping(self) -> Dict[str, Any]:
        return await self.request("GET", "/tires/dolati")
