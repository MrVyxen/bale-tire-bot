import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import aiohttp
from config import DEFAULT_HEADERS
from tire_api.utils import clean_search_text, get_tehran_now, persian_to_english_digits

logger = logging.getLogger("OilPriceClient")

_BAD_OIL_KEYWORDS = (
    "موتور سیکلت",
    "موتورسیکلت",
    "موتوربایک",
    "motorbike",
    "motorcycle",
    "اسکوتر",
    "scooter",
    "گیربکس",
    "دنده",
    "هیدرولیک",
    "روغن ترمز",
    "ضد یخ",
    "ضدیخ",
    "گریس",
    "اکتان",
    "مکمل",
    "انژکتور شور",
    "موتورشور",
    "شستشو",
    "واکس",
    "اسپری",
    "فیلتر روغن",
    "کارتن",
    "بسته 6",
    "بسته 12",
    "بسته 4",
    "6 عددی",
    "12 عددی",
    "4 عددی",
    "پک 6",
    "پک 12",
    "عمده",
    "بشکه",
    "208 لیتر",
)

_DK_OIL_BRANDS = ("behran", "iranol", "speedy", "caspian", "castrol", "total", "liqui-moly")


def normalize_oil_grade(raw: str) -> Optional[str]:
    """نرمال‌سازی گرانروی روغن موتور (مثلاً '10w-40' یا '۱۰/۴۰' -> '10W40')"""
    if not raw:
        return None
    t = persian_to_english_digits(raw).upper().strip()
    m = re.search(r"(?<!\d)(0|5|10|15|20)\s*[Ww/\-]\s*(20|30|40|50|60)(?!\d)", t)
    if not m:
        return None
    return f"{m.group(1)}W{m.group(2)}"


def matches_exact_oil_grade(title: str, grade: str) -> bool:
    """بررسی تطابق دقیق گرانروی روغن موتور در عنوان محصول"""
    m_g = re.match(r"^(\d+)W(\d+)$", grade.upper())
    if not m_g:
        return False
    a, b = m_g.group(1), m_g.group(2)
    t = clean_search_text(title).upper()
    pat = rf"(?<!\d){a}\s*[Ww]\s*[\-/\s]?\s*{b}(?!\d)"
    return bool(re.search(pat, t))


def detect_oil_volume(title: str) -> Optional[float]:
    """تشخیص دقیق حجم روغن موتور به لیتر (۱، ۳.۵، ۴، ۴.۵، ۵ یا ۲۰ لیتر)"""
    t = clean_search_text(title).lower()
    # بررسی ۲۰ لیتری (گالن دیزل / سنگین)
    if re.search(r"(?<!\d)20\s*(?:لیتر|ليتر|لیتری|ليتری|l\b|lit)", t):
        return 20.0
    for pat, val in (
        (r"(?<!\d)4[./]5\s*(?:لیتر|ليتر|لیتری|ليتری|l\b|lit)", 4.5),
        (r"(?<!\d)3[./]5\s*(?:لیتر|ليتر|لیتری|ليتری|l\b|lit)", 3.5),
        (r"(?<!\d)5\s*(?:لیتر|ليتر|لیتری|ليتری|l\b|lit)", 5.0),
        (r"(?<!\d)4\s*(?:لیتر|ليتر|لیتری|ليتری|l\b|lit)", 4.0),
        (r"(?<!\d)1\s*(?:لیتر|ليتر|لیتری|ليتری|l\b|lit)", 1.0),
        (r"(?:چهار|۴)\s*(?:لیتر|ليتر|لیتری)", 4.0),
        (r"(?:پنج|۵)\s*(?:لیتر|ليتر|لیتری)", 5.0),
        (r"(?:یک|۱)\s*(?:لیتر|ليتر|لیتری)", 1.0),
        (r"(?:بیست|۲۰)\s*(?:لیتر|ليتر|لیتری)", 20.0),
    ):
        if re.search(pat, t):
            return val
    return None


def detect_oil_api_level(title: str) -> str:
    """تشخیص سطح کیفیت API روغن (مثل SP, SN, SM, SL, SJ, CI-4)"""
    t = clean_search_text(title).upper()
    for lvl in ("CI-4", "CH-4", "CK-4", "SP", "SN PLUS", "SN", "SM", "SL", "SJ", "SG"):
        if re.search(rf"(?<![A-Z0-9]){re.escape(lvl)}(?![A-Z0-9])", t):
            return lvl
    return ""


def detect_oil_brand(title: str) -> Tuple[str, str]:
    """تشخیص برند روغن موتور و تفکیک ایرانی (IR) از خارجی/وارداتی (IMP)"""
    t = clean_search_text(title).lower()
    iranian = (
        ("بهران", ("بهران", "behran", "رانا", "سوپرپیشتاز", "سوپر پیشتاز", "پیشتاز", "تکتاز")),
        ("ایرانول", ("ایرانول", "iranol", "رونیا", "ریسینگ")),
        ("اسپیدی", ("اسپیدی", "speedy", "پلاتینیوم", "سوپرپاور")),
        ("نفت پارس", ("پارس", "pars", "سوپرپایا", "سوپر پایا", "سوپرپیشرو", "سوپر پیشرو", "پایا")),
        ("کاسپین", ("کاسپین", "caspian")),
        ("بهتام", ("بهتام", "behtam", "کوانتیک")),
        ("فلومکس", ("فلومکس", "flomax", "فلو مکس")),
        ("سپاهان", ("سپاهان", "sepahan")),
        ("پترونول", ("پترونول", "petronol")),
        ("اپتیمکس", ("اپتیمکس", "optimax")),
    )
    for name, kws in iranian:
        for kw in kws:
            if kw in t:
                return name, "IR"

    foreign = (
        ("کاسترول", ("کاسترول", "castrol", "مگناتک", "magnatec")),
        ("لیکومولی", ("لیکومولی", "لیکویی مولی", "liqui", "moly")),
        ("توتال", ("توتال", "total", "کوارتز", "quartz")),
        ("الف", ("الف", "elf")),
        ("شل", ("شل", "shell", "هلیکس", "helix")),
        ("موبیل", ("موبیل", "mobil")),
        ("ادینول", ("ادینول", "addinol")),
        ("هیوندای اکستیر", ("اکستیر", "xteer", "هیوندای")),
        ("کیکس", ("کیکس", "kixx")),
        ("زیگ", ("زیگ", "zic")),
        ("مگل", ("مگل", "megol", "مگوین")),
        ("فوسر", ("فوسر", "fosser")),
        ("مانول / موتول", ("مانول", "موتول", "mannol", "motul")),
        ("پتروکانادا / کانادا", ("کانادا", "canada")),
        ("پونته میلانو", ("پونته", "میلانو", "ponte")),
        ("والوالین", ("والوالین", "valvoline")),
    )
    for name, kws in foreign:
        for kw in kws:
            if kw in t:
                return name, "IMP"

    return "سایر برندها", "IR"


def is_valid_car_oil_listing(title: str, price_toman: int, volume: Optional[float], grade: str) -> bool:
    """حذف آگهی‌های غیرمرتبط (موتورسیکلت، فیلتر، کارتن عمده، قیمت‌های غیرمنطقی)"""
    t = clean_search_text(title).lower()
    if "روغن" not in t and "oil" not in t:
        return False
    # اگر پک همراه فیلتر بود و خیلی گران یا فقط فیلتر بود حذف می‌کنیم
    if "فیلتر" in t and "پک" not in t and "روغن موتور" not in t:
        return False
    for bad in _BAD_OIL_KEYWORDS:
        if bad in t:
            return False

    if grade == "15W40":
        # دیزلی (گالن ۴ یا ۲۰ لیتری)
        if volume == 20.0:
            return 2_500_000 <= price_toman <= 120_000_000
        return 450_000 <= price_toman <= 30_000_000

    if volume == 1.0:
        return 120_000 <= price_toman <= 4_500_000
    if volume in (3.5, 4.0, 4.5, 5.0):
        return 450_000 <= price_toman <= 25_000_000
    return 450_000 <= price_toman <= 25_000_000


class OilPriceClient:
    """
    موتور استعلام زنده و دقیق قیمت روز روغن موتور خودرو از دیجی‌کالا، ترب و باسلام
    همراه با لینک مستقیم خرید و تفکیک حجم و برند ایرانی/خارجی
    """

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._torob_blocked_until: float = 0.0

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(limit=25, ssl=False)
            self._session = aiohttp.ClientSession(
                connector=connector,
                headers={
                    **DEFAULT_HEADERS,
                    "Accept": "application/json, text/plain, */*",
                },
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _fetch_digikala_oils(self, grade: str) -> List[Dict[str, Any]]:
        session = await self.get_session()
        offers: List[Dict[str, Any]] = []
        seen_ids = set()

        async def _query_brand(brand_slug: str):
            try:
                async with session.get(
                    f"https://api.digikala.com/v1/brands/{brand_slug}/search/",
                    params={"q": f"روغن موتور {grade}", "page": 1},
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json(content_type=None)
            except Exception as e:
                logger.debug(f"Digikala oil brand {brand_slug} err: {e}")
            return {}

        responses = await asyncio.gather(*[_query_brand(b) for b in _DK_OIL_BRANDS])
        for data in responses:
            for p in (data.get("data") or {}).get("products") or []:
                pid = p.get("id")
                if not pid or pid in seen_ids or p.get("status") != "marketable":
                    continue
                title = clean_search_text(p.get("title_fa") or "")
                title_en = clean_search_text(p.get("title_en") or "")
                full_t = f"{title} {title_en}"
                if not matches_exact_oil_grade(full_t, grade):
                    continue
                dv = p.get("default_variant") or {}
                price_rial = (dv.get("price") or {}).get("selling_price")
                if not price_rial:
                    continue
                price_toman = int(price_rial) // 10
                vol = detect_oil_volume(full_t)
                if not is_valid_car_oil_listing(full_t, price_toman, vol, grade):
                    continue
                seen_ids.add(pid)
                brand, origin = detect_oil_brand(full_t)
                seller = clean_search_text((dv.get("seller") or {}).get("title") or "دیجی‌کالا")
                offers.append({
                    "source": "دیجی‌کالا",
                    "title": title,
                    "brand": brand,
                    "origin": origin,
                    "api_level": detect_oil_api_level(full_t),
                    "volume": vol,
                    "price_toman": price_toman,
                    "shop_name": seller,
                    "url": f"https://www.digikala.com/product/dkp-{pid}/",
                })
        return offers

    async def _fetch_torob_oils(self, grade: str) -> Tuple[List[Dict[str, Any]], str]:
        if time.monotonic() < self._torob_blocked_until:
            return [], "rate_limited"
        session = await self.get_session()
        vol_hint = "20 لیتری" if grade == "15W40" else "4 لیتری"
        offers: List[Dict[str, Any]] = []
        seen_keys = set()
        rate_limited = False

        for q in (f"روغن موتور {grade} {vol_hint}", f"روغن موتور خودرو {grade}"):
            try:
                async with session.get(
                    "https://api.torob.com/v4/base-product/search/",
                    params={"q": q, "page": 0, "size": 24},
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status == 429:
                        self._torob_blocked_until = time.monotonic() + 300.0
                        rate_limited = True
                        break
                    if resp.status != 200:
                        continue
                    data = await resp.json(content_type=None)
                    for item in data.get("results") or []:
                        title = clean_search_text(item.get("name1") or "")
                        if not matches_exact_oil_grade(title, grade):
                            continue
                        price_toman = int(item.get("price") or 0)
                        vol = detect_oil_volume(title)
                        if not is_valid_car_oil_listing(title, price_toman, vol, grade):
                            continue
                        key = item.get("random_key") or title
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        brand, origin = detect_oil_brand(title)
                        abs_url = item.get("web_client_absolute_url") or ""
                        full_url = f"https://torob.com{abs_url}" if abs_url.startswith("/") else "https://torob.com"
                        shop = re.sub(r"^در\s+", "", clean_search_text(item.get("shop_text") or "فروشگاه ترب")).strip()
                        offers.append({
                            "source": "ترب",
                            "title": title,
                            "brand": brand,
                            "origin": origin,
                            "api_level": detect_oil_api_level(title),
                            "volume": vol,
                            "price_toman": price_toman,
                            "shop_name": shop,
                            "url": full_url,
                        })
            except Exception as e:
                logger.debug(f"Torob oil err ({q}): {e}")
        return offers, ("rate_limited" if rate_limited and not offers else "ok")

    async def _fetch_basalam_oils(self, grade: str) -> List[Dict[str, Any]]:
        session = await self.get_session()
        vol_hint = "20 لیتری" if grade == "15W40" else "4 لیتری"
        offers: List[Dict[str, Any]] = []
        seen_ids = set()

        async def _query(q: str):
            try:
                async with session.get(
                    "https://search.basalam.com/ai-engine/api/v2.0/product/search",
                    params={"q": q, "size": 30},
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json(content_type=None)
            except Exception as e:
                logger.debug(f"Basalam oil err ({q}): {e}")
            return {}

        responses = await asyncio.gather(
            _query(f"روغن موتور {grade} {vol_hint}"),
            _query(f"روغن موتور خودرو {grade}"),
        )
        for data in responses:
            for p in data.get("products") or []:
                pid = p.get("id")
                if not pid or pid in seen_ids or p.get("stock", 1) == 0:
                    continue
                title = clean_search_text(p.get("name") or "")
                if not matches_exact_oil_grade(title, grade):
                    continue
                price_rial = int(p.get("price") or 0)
                price_toman = price_rial // 10 if price_rial > 500_000 else price_rial
                vol = detect_oil_volume(title)
                if not is_valid_car_oil_listing(title, price_toman, vol, grade):
                    continue
                seen_ids.add(pid)
                vendor = p.get("vendor") or {}
                v_ident = vendor.get("identifier") or ""
                v_name = clean_search_text(vendor.get("name") or "غرفه باسلام")
                url = f"https://basalam.com/{v_ident}/product/{pid}" if v_ident else f"https://basalam.com/p/{pid}"
                brand, origin = detect_oil_brand(title)
                offers.append({
                    "source": "باسلام",
                    "title": title,
                    "brand": brand,
                    "origin": origin,
                    "api_level": detect_oil_api_level(title),
                    "volume": vol,
                    "price_toman": price_toman,
                    "shop_name": v_name,
                    "url": url,
                })
        return offers

    async def fetch_live_oil_prices(self, raw_grade: str, force_refresh: bool = False) -> Dict[str, Any]:
        """استعلام زنده و دقیق قیمت روز روغن موتور بر اساس گرانروی (مثلاً 10W40)"""
        grade = normalize_oil_grade(raw_grade)
        if not grade:
            return {"ok": False, "error": "گرانروی روغن موتور نامعتبر است."}

        now_info = get_tehran_now()
        if not force_refresh and grade in self._cache:
            exp_ts, cached_res = self._cache[grade]
            if time.monotonic() < exp_ts:
                cp = dict(cached_res)
                cp["timestamp"] = now_info
                cp["cached"] = True
                return cp

        t0 = time.perf_counter()
        dk_res, torob_res, bs_res = await asyncio.gather(
            self._fetch_digikala_oils(grade),
            self._fetch_torob_oils(grade),
            self._fetch_basalam_oils(grade),
            return_exceptions=True,
        )

        dk_list = dk_res if isinstance(dk_res, list) else []
        torob_list, torob_st = torob_res if isinstance(torob_res, tuple) else ([], "error")
        bs_list = bs_res if isinstance(bs_res, list) else []

        source_counts = {
            "دیجی‌کالا": len(dk_list),
            "ترب": len(torob_list),
            "باسلام": len(bs_list),
        }
        source_status = {
            "دیجی‌کالا": "ok" if isinstance(dk_res, list) else "error",
            "ترب": torob_st,
            "باسلام": "ok" if isinstance(bs_res, list) else "error",
        }

        combined = dk_list + torob_list + bs_list
        # حذف تکراری‌ها
        deduped: List[Dict[str, Any]] = []
        seen_sig = set()
        for off in combined:
            sig = (off["source"], off["shop_name"], off["brand"], off["price_toman"], off["volume"])
            if sig not in seen_sig:
                seen_sig.add(sig)
                deduped.append(off)

        # انتخاب حجم هدف اصلی (۴ تا ۵ لیتر برای سواری، ۲۰ لیتر برای ۱۵W40 دیزلی در اولویت)
        if grade == "15W40":
            main_pool = [o for o in deduped if o["volume"] == 20.0]
            if not main_pool:
                main_pool = [o for o in deduped if o["volume"] in (4.0, 5.0, None)]
            target_vol_label = "گالن ۲۰ لیتری (دیزلی)" if any(o["volume"] == 20.0 for o in main_pool) else "گالن ۴/۵ لیتری"
        else:
            # حذف ۱ لیتری‌ها از لیست اصلی گالن ۴/۵ لیتری تا قیمت‌ها قاطی نشوند
            main_pool = [o for o in deduped if o["volume"] in (3.5, 4.0, 4.5, 5.0)]
            if len(main_pool) < 3:
                main_pool = [o for o in deduped if o["volume"] != 1.0]
            target_vol_label = "گالن ۴ تا ۵ لیتری"

        ir_offers = sorted([o for o in main_pool if o["origin"] == "IR"], key=lambda x: x["price_toman"])
        imp_offers = sorted([o for o in main_pool if o["origin"] != "IR"], key=lambda x: x["price_toman"])

        def _drop_outliers(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            if len(items) < 4:
                return items
            med = items[len(items) // 2]["price_toman"]
            return [x for x in items if int(med * 0.45) <= x["price_toman"] <= int(med * 2.2)]

        ir_offers = _drop_outliers(ir_offers)
        imp_offers = _drop_outliers(imp_offers)

        def _summary(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if not items:
                return None
            p85 = min(len(items) - 1, int(len(items) * 0.85))
            return {
                "min": items[0]["price_toman"],
                "max": items[p85]["price_toman"],
                "median": items[len(items) // 2]["price_toman"],
                "count": len(items),
            }

        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        result = {
            "ok": True,
            "grade": grade,
            "target_volume_label": target_vol_label,
            "timestamp": now_info,
            "latency_ms": latency_ms,
            "cached": False,
            "source_counts": source_counts,
            "source_status": source_status,
            "total_found": len(ir_offers) + len(imp_offers),
            "ir_summary": _summary(ir_offers),
            "imp_summary": _summary(imp_offers),
            "ir_offers": ir_offers,
            "imp_offers": imp_offers,
        }
        if result["total_found"] > 0:
            self._cache[grade] = (time.monotonic() + 60.0, result)
        return result
