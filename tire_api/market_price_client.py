import asyncio
import json
import logging
import re
import time
from typing import Dict, Any, List, Optional, Tuple
import aiohttp
from config import DEFAULT_HEADERS
from database import record_market_price_snapshot
from telemetry import telemetry
from tire_api.hypertire_client import HyperTireClient
from tire_api.utils import (
    clean_search_text,
    detect_tire_brand,
    detect_tire_pack_count,
    format_toman,
    get_tehran_now,
    is_valid_car_tire_listing,
    matches_exact_tire_size,
    normalize_tire_size,
    parse_size_parts,
    resolve_tire_pack_and_unit_price,
)

logger = logging.getLogger("MarketPriceClient")

# اسلاگ برندهای معتبر تایر در دیجی‌کالا
_DK_TIRE_BRANDS = (
    ("barez", "بارز", "IR"),
    ("kavir-tire", "کویر تایر", "IR"),
    ("yazdtire", "یزد تایر", "IR"),
    ("goldstone", "گلدستون", "IR"),
    ("razi", "رازی تایر", "IR"),
    ("dena", "دنا تایر", "IR"),
    ("nexen", "نکسن", "IMP"),
    ("triangle", "تراینگل", "IMP"),
    ("hankook", "هانکوک", "IMP"),
    ("michelin", "میشلن", "IMP"),
)


class MarketPriceClient:
    """
    موتور استعلام فوق‌دقیق و زنده قیمت روز لاستیک آزاد
    متصل هم‌زمان به دیجی‌کالا، ترب، باسلام و هایپرتایر با تفکیک قطعی قیمت تک و جفت
    """

    def __init__(self, hypertire: Optional[HyperTireClient] = None):
        self._session: Optional[aiohttp.ClientSession] = None
        self._owns_hypertire = hypertire is None
        self.hypertire = hypertire or HyperTireClient()
        self._torob_blocked_until: float = 0.0
        self._price_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=False, limit=60, keepalive_timeout=60, ttl_dns_cache=300)
            timeout = aiohttp.ClientTimeout(total=12, connect=4)
            self._session = aiohttp.ClientSession(
                connector=connector, timeout=timeout, headers=DEFAULT_HEADERS
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
        if self._owns_hypertire and self.hypertire:
            await self.hypertire.close()

    @staticmethod
    def _extract_year(title: str) -> str:
        t = clean_search_text(title)
        m = re.search(r"\b(202[0-9]|140[0-9])\b", t)
        return m.group(1) if m else ""

    @staticmethod
    def _extract_model_pattern(title: str) -> str:
        """استخراج مدل و طرح گل تایر (مثل P640, P648, KB27, اورانوس, مرسانا)"""
        t = clean_search_text(title)
        patterns = (
            r"\b([Pp]\s*\d{3}[A-Za-z]?)\b",
            r"\b([Kk][Bb]\s*\d{2,3})\b",
            r"\b(اورانوس|مرسانا|آرتیمیس|سهند|تکتاز|دابلیو|الوند|کپیتال|ونوس|شهاب|پریمیر)\b",
        )
        for pat in patterns:
            m = re.search(pat, t)
            if m:
                return m.group(1).replace(" ", "").upper()
        return ""

    @staticmethod
    def _is_downpayment_bait(title: str) -> bool:
        t = clean_search_text(title).lower()
        return any(k in t for k in ("بیعانه", "پیش پرداخت", "پیش‌پرداخت", "رزرو", "کارکرده", "دست دوم", "استوک", "آج ", "داغی"))

    async def _fetch_digikala_offers(self, norm_size: str, w: str, a: str, r: str) -> List[Dict[str, Any]]:
        session = await self.get_session()
        offers: List[Dict[str, Any]] = []
        seen_ids = set()
        q_num = f"{w}/{a}" if a != "INCH" else f"{w}"

        async def _fetch_brand(slug: str, brand_name_fa: str, origin: str):
            try:
                async with session.get(
                    f"https://api.digikala.com/v1/brands/{slug}/search/",
                    params={"q": q_num, "page": 1},
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json(content_type=None)
                    items = []
                    for p in (data.get("data") or {}).get("products") or []:
                        pid = p.get("id")
                        if not pid or pid in seen_ids or p.get("status") != "marketable":
                            continue
                        t_fa = clean_search_text(p.get("title_fa") or "")
                        t_en = clean_search_text(p.get("title_en") or "")
                        full_t = f"{t_fa} {t_en}"
                        if not matches_exact_tire_size(full_t, w, a, r):
                            continue
                        if self._is_downpayment_bait(full_t):
                            continue
                        dv = p.get("default_variant") or {}
                        price_rial = (dv.get("price") or {}).get("selling_price")
                        if not price_rial:
                            continue
                        price_toman = int(price_rial) // 10
                        if not is_valid_car_tire_listing(full_t, price_toman):
                            continue
                        seen_ids.add(pid)
                        pack, unit_p, pair_p = resolve_tire_pack_and_unit_price(
                            full_t, price_toman, is_iranian=(origin == "IR")
                        )
                        seller = clean_search_text((dv.get("seller") or {}).get("title") or "دیجی‌کالا")
                        model = self._extract_model_pattern(full_t)
                        yr = self._extract_year(full_t)
                        items.append({
                            "source": "دیجی‌کالا",
                            "title": t_fa,
                            "brand": brand_name_fa,
                            "model": model,
                            "origin": origin,
                            "year": yr,
                            "shop_name": seller,
                            "price_toman": price_toman,
                            "pack_count": pack,
                            "unit_price_toman": unit_p,
                            "pair_price_toman": pair_p,
                            "url": f"https://www.digikala.com/product/dkp-{pid}/",
                        })
                    return items
            except Exception as e:
                logger.debug(f"Digikala brand {slug} err: {e}")
                return []

        tasks = [_fetch_brand(slug, b_fa, orig) for slug, b_fa, orig in _DK_TIRE_BRANDS]
        batches = await asyncio.gather(*tasks, return_exceptions=True)
        for b in batches:
            if isinstance(b, list):
                offers.extend(b)
        return offers

    async def _fetch_torob_offers(self, norm_size: str, w: str, a: str, r: str) -> Tuple[List[Dict[str, Any]], str]:
        if time.monotonic() < self._torob_blocked_until:
            return [], "rate_limited"

        session = await self.get_session()
        offers: List[Dict[str, Any]] = []
        seen_keys = set()
        q_torob = f"لاستیک {norm_size}" if a != "INCH" else f"لاستیک {w} {r}"

        try:
            async with session.get(
                "https://api.torob.com/v4/base-product/search/",
                params={"q": q_torob, "page": 0, "size": 18},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status in (403, 429, 490):
                    self._torob_blocked_until = time.monotonic() + 300.0
                    return [], "rate_limited"
                if resp.status != 200:
                    return [], "error"
                data = await resp.json(content_type=None)
        except Exception as e:
            logger.debug(f"Torob search err: {e}")
            return [], "error"

        for item in (data or {}).get("results", []):
            prk = item.get("random_key")
            if not prk or prk in seen_keys:
                continue
            name_full = f"{item.get('name1', '')} {item.get('name2', '')}".strip()
            if not matches_exact_tire_size(name_full, w, a, r):
                continue
            if self._is_downpayment_bait(name_full):
                continue
            price_toman = int(item.get("price") or 0)
            if not is_valid_car_tire_listing(name_full, price_toman):
                continue
            seen_keys.add(prk)
            brand, origin = detect_tire_brand(name_full)
            pack, unit_p, pair_p = resolve_tire_pack_and_unit_price(
                name_full, price_toman, is_iranian=(origin == "IR")
            )
            abs_url = item.get("web_client_absolute_url") or ""
            full_url = f"https://torob.com{abs_url}" if abs_url.startswith("/") else "https://torob.com"
            shop = re.sub(r"^در\s+", "", clean_search_text(item.get("shop_text") or "ترب")).strip()
            model = self._extract_model_pattern(name_full)
            yr = self._extract_year(name_full)
            offers.append({
                "source": "ترب",
                "title": name_full,
                "brand": brand,
                "model": model,
                "origin": origin,
                "year": yr,
                "shop_name": shop,
                "price_toman": price_toman,
                "pack_count": pack,
                "unit_price_toman": unit_p,
                "pair_price_toman": pair_p,
                "url": full_url,
            })

        return offers, "ok"

    async def _fetch_basalam_offers(self, norm_size: str, w: str, a: str, r: str) -> List[Dict[str, Any]]:
        session = await self.get_session()
        offers: List[Dict[str, Any]] = []
        seen_ids = set()
        q_basalam = f"لاستیک {norm_size}" if a != "INCH" else f"لاستیک {w}-{r}"

        try:
            async with session.get(
                "https://search.basalam.com/ai-engine/api/v2.0/product/search",
                params={"q": q_basalam, "size": 25},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json(content_type=None)
        except Exception as e:
            logger.debug(f"Basalam search err: {e}")
            return []

        for p in (data or {}).get("products") or []:
            pid = p.get("id")
            if not pid or pid in seen_ids or not p.get("IsAvailable", True):
                continue
            title = clean_search_text(p.get("name") or "")
            if not matches_exact_tire_size(title, w, a, r):
                continue
            if self._is_downpayment_bait(title):
                continue
            raw_pr = p.get("price") or 0
            if not raw_pr:
                continue
            # تبدیل دقیق ریال به تومان
            price_rial = int(float(raw_pr))
            price_toman = price_rial // 10 if price_rial > 400_000 else price_rial
            if not is_valid_car_tire_listing(title, price_toman):
                continue
            seen_ids.add(pid)
            brand, origin = detect_tire_brand(title)
            pack, unit_p, pair_p = resolve_tire_pack_and_unit_price(
                title, price_toman, is_iranian=(origin == "IR")
            )
            vendor = p.get("vendor") or {}
            v_id = vendor.get("identifier")
            v_name = clean_search_text(vendor.get("name") or "غرفه باسلام")
            p_url = f"https://basalam.com/{v_id}/product/{pid}" if v_id else f"https://basalam.com/p/{pid}"
            model = self._extract_model_pattern(title)
            yr = self._extract_year(title)
            offers.append({
                "source": "باسلام",
                "title": title,
                "brand": brand,
                "model": model,
                "origin": origin,
                "year": yr,
                "shop_name": v_name,
                "price_toman": price_toman,
                "pack_count": pack,
                "unit_price_toman": unit_p,
                "pair_price_toman": pair_p,
                "url": p_url,
            })

        return offers

    async def fetch_live_market_prices(self, raw_size: str, force_refresh: bool = False) -> Dict[str, Any]:
        """استعلام زنده، تفکیک‌شده و دقیق قیمت روز بازار آزاد تایر"""
        parts = parse_size_parts(raw_size)
        if not parts:
            return {"ok": False, "error": "سایز تایر نامعتبر است."}

        w, a, r = parts
        norm_size = f"{w}R{r}" if a == "INCH" else f"{w}/{a}R{r}"
        now_info = get_tehran_now()

        if not force_refresh and norm_size in self._price_cache:
            exp_ts, cached_res = self._price_cache[norm_size]
            if time.monotonic() < exp_ts:
                cp = dict(cached_res)
                cp["timestamp"] = now_info
                cp["cached"] = True
                return cp

        t0 = time.perf_counter()

        dk_res, torob_res, bs_res = await asyncio.gather(
            self._fetch_digikala_offers(norm_size, w, a, r),
            self._fetch_torob_offers(norm_size, w, a, r),
            self._fetch_basalam_offers(norm_size, w, a, r),
            return_exceptions=True,
        )

        dk_list = dk_res if isinstance(dk_res, list) else []
        torob_list, torob_st = torob_res if isinstance(torob_res, tuple) else ([], "error")
        bs_list = bs_res if isinstance(bs_res, list) else []

        source_counts = {
            "دیجی‌کالا": len(dk_list),
            "ترب": len(torob_list),
            "باسلام": len(bs_list),
            "هایپرتایر": 0,
        }
        source_status = {
            "دیجی‌کالا": "ok" if isinstance(dk_res, list) else "error",
            "ترب": torob_st,
            "باسلام": "ok" if isinstance(bs_res, list) else "error",
            "هایپرتایر": "ok",
        }

        combined = dk_list + torob_list + bs_list

        # حذف آگهی‌های کاملاً تکراری
        deduped: List[Dict[str, Any]] = []
        seen_sig = set()
        for off in combined:
            sig = (off["brand"], off["price_toman"], off["source"], off["shop_name"])
            if sig not in seen_sig:
                seen_sig.add(sig)
                deduped.append(off)

        # تفکیک تایرهای ایرانی و خارجی
        ir_pool = [o for o in deduped if o["origin"] == "IR"]
        imp_pool = [o for o in deduped if o["origin"] != "IR"]

        # مرتب‌سازی بر اساس ارزان‌ترین قیمت هر حلقه
        ir_pool.sort(key=lambda x: x["unit_price_toman"])
        imp_pool.sort(key=lambda x: x["unit_price_toman"])

        # ساخت پیشنهادات شاخص ایرانی به تفکیک برندهای اصلی
        # انتخاب بهترین و ارزان‌ترین قیمت برای هر برند شاخص (بارز، کویر، یزد، ایران‌تایر، گلدستون)
        featured_ir_brands: Dict[str, Dict[str, Any]] = {}
        target_brands = ["بارز", "کویر تایر", "یزد تایر", "ایران تایر", "گلدستون"]
        for o in ir_pool:
            b = o["brand"]
            matched_b = next((tb for tb in target_brands if tb in b), None)
            if matched_b and matched_b not in featured_ir_brands:
                featured_ir_brands[matched_b] = o

        def _calc_summary(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if not items:
                return None
            units = [x["unit_price_toman"] for x in items]
            min_u = min(units)
            med_u = units[len(units) // 2]
            p85_idx = min(len(units) - 1, int(len(units) * 0.85))
            typ_max_u = units[p85_idx]
            return {
                "min_unit": min_u,
                "median_unit": med_u,
                "max_unit": typ_max_u,
                "min_pair": min_u * 2,
                "max_pair": typ_max_u * 2,
                "count": len(items),
            }

        ir_summary = _calc_summary(ir_pool)
        imp_summary = _calc_summary(imp_pool)
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)

        result = {
            "ok": True,
            "size": norm_size,
            "timestamp": now_info,
            "latency_ms": latency_ms,
            "cached": False,
            "source_counts": source_counts,
            "source_status": source_status,
            "total_found": len(ir_pool) + len(imp_pool),
            "ir_summary": ir_summary,
            "imp_summary": imp_summary,
            "featured_ir_brands": featured_ir_brands,
            "ir_offers": ir_pool,
            "imp_offers": imp_pool,
        }

        telemetry.record_market_query(
            size=norm_size,
            total_found=result["total_found"],
            total_latency_ms=latency_ms,
            source_details={
                s: {
                    "count": source_counts.get(s, 0),
                    "status": source_status.get(s, "ok"),
                    "latency_ms": 0.0,
                }
                for s in ("دیجی‌کالا", "باسلام", "هایپرتایر", "ترب")
            },
            ir_median=ir_summary["median_unit"] if ir_summary else None,
            imp_median=imp_summary["median_unit"] if imp_summary else None,
        )

        if result["total_found"] > 0:
            self._price_cache[norm_size] = (time.monotonic() + 90.0, result)
            try:
                await record_market_price_snapshot(
                    tire_size=norm_size,
                    ir_min=ir_summary["min_unit"] if ir_summary else None,
                    ir_med=ir_summary["median_unit"] if ir_summary else None,
                    imp_min=imp_summary["min_unit"] if imp_summary else None,
                    imp_med=imp_summary["median_unit"] if imp_summary else None,
                    total_offers=result["total_found"],
                    sources_json=json.dumps(source_counts, ensure_ascii=False),
                    tehran_time=now_info["compact_fa"],
                )
            except Exception as e:
                logger.debug(f"Price snapshot skip: {e}")

        return result
