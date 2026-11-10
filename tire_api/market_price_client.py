import asyncio
import logging
import re
import time
from typing import Dict, Any, List, Optional
import aiohttp
from config import DEFAULT_HEADERS
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
)

logger = logging.getLogger("MarketPriceClient")


class MarketPriceClient:
    """
    موتور هوشمند و فوق‌دقیق استعلام لحظه‌ای قیمت روز لاستیک آزاد
    متصل به‌صورت هم‌زمان به:
    1. ترب (تجمیع‌کننده ده‌ها فروشگاه معتبر لاستیک در سراسر کشور)
    2. دیجی‌کالا (موجودی و قیمت لحظه‌ای)
    3. باسلام (فروشندگان مستقیم تایر سراسر کشور)
    4. هایپرتایر (فروشگاه تخصصی لاستیک با سال ساخت دقیق)
    """

    def __init__(self, hypertire: Optional[HyperTireClient] = None):
        self._session: Optional[aiohttp.ClientSession] = None
        self._owns_hypertire = hypertire is None
        self.hypertire = hypertire or HyperTireClient()
        self._torob_blocked_until: float = 0.0
        self._price_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}

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
    def _is_downpayment_bait(title: str) -> bool:
        t = clean_search_text(title).lower()
        return any(k in t for k in ("بیعانه", "پیش پرداخت", "پیش‌پرداخت", "رزرو", "کارکرده", "دست دوم", "استوک", "آج "))

    async def _fetch_torob_offers(self, norm_size: str, w: str, a: str, r: str) -> tuple[List[Dict[str, Any]], str]:
        """
        دریافت قیمت از ترب با احترام کامل به محدودیت نرخ (Circuit Breaker + ۱ کوئری سبک).
        خروجی: (لیست پیشنهادها, وضعیت: 'ok' | 'rate_limited' | 'empty')
        """
        if time.monotonic() < self._torob_blocked_until:
            return [], "rate_limited"

        session = await self.get_session()
        base_candidates: List[Dict[str, Any]] = []
        seen_keys = set()

        try:
            async with session.get(
                "https://api.torob.com/v4/base-product/search/",
                params={"q": f"لاستیک {norm_size}", "page": 0, "size": 12},
                timeout=aiohttp.ClientTimeout(total=7),
            ) as resp:
                if resp.status != 200:
                    if resp.status in (403, 429, 490):
                        self._torob_blocked_until = time.monotonic() + 600.0
                        logger.warning(f"Torob rate-limit/WAF ({resp.status}); cooling down for 10m")
                        return [], "rate_limited"
                    return [], "error"
                data = await resp.json(content_type=None)
        except Exception as e:
            logger.warning(f"Torob search error: {e}")
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
            seen_keys.add(prk)
            base_candidates.append(item)

        all_offers: List[Dict[str, Any]] = []
        detail_fetches = 0

        for item in base_candidates[:10]:
            base_name = clean_search_text(item.get("name1") or "")
            base_pack = detect_tire_pack_count(base_name)
            abs_url = item.get("web_client_absolute_url") or ""
            full_url = f"https://torob.com{abs_url}" if abs_url.startswith("/") else "https://torob.com"
            miu = item.get("more_info_url")

            got_detail = False
            # فقط حداکثر ۲ بار با تاخیر متوالی برای مواردی که تعداد حلقه در عنوان پایه مشخص نیست جزئیات می‌گیریم
            if miu and base_pack is None and detail_fetches < 2 and time.monotonic() >= self._torob_blocked_until:
                detail_fetches += 1
                await asyncio.sleep(0.35)
                try:
                    async with session.get(miu, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            md = await resp.json(content_type=None)
                            raw_offers = (md.get("products_info") or {}).get("result") or []
                            valid_shop_offers = []
                            for off in raw_offers:
                                if not off.get("availability", True):
                                    continue
                                o_name = clean_search_text(off.get("name1") or base_name)
                                if not matches_exact_tire_size(o_name + " " + base_name, w, a, r):
                                    continue
                                if self._is_downpayment_bait(o_name):
                                    continue
                                price_toman = int(off.get("price") or 0)
                                if not is_valid_car_tire_listing(o_name + " " + base_name, price_toman):
                                    continue
                                pack = detect_tire_pack_count(o_name) or base_pack
                                shop = re.sub(
                                    r"^در\s+", "", clean_search_text(off.get("shop_name") or item.get("shop_text") or "فروشگاه ترب")
                                ).strip()
                                brand, origin = detect_tire_brand(o_name + " " + base_name)
                                valid_shop_offers.append({
                                    "source": "ترب",
                                    "title": o_name,
                                    "base_title": base_name,
                                    "brand": brand,
                                    "origin": origin,
                                    "year": self._extract_year(o_name + " " + base_name),
                                    "shop_name": shop,
                                    "price_toman": price_toman,
                                    "pack_count": pack,
                                    "unit_price_toman": (price_toman // pack) if pack else None,
                                    "url": full_url,
                                })
                            if valid_shop_offers:
                                valid_shop_offers.sort(
                                    key=lambda x: x["unit_price_toman"] if x["unit_price_toman"] else x["price_toman"]
                                )
                                all_offers.extend(valid_shop_offers[:2])
                                got_detail = True
                        elif resp.status in (403, 429, 490):
                            self._torob_blocked_until = time.monotonic() + 600.0
                except Exception as e:
                    logger.debug(f"Torob detail err: {e}")

            if not got_detail:
                price_toman = int(item.get("price") or 0)
                if is_valid_car_tire_listing(base_name, price_toman):
                    shop = re.sub(r"^در\s+", "", clean_search_text(item.get("shop_text") or "ترب")).strip()
                    brand, origin = detect_tire_brand(base_name)
                    all_offers.append({
                        "source": "ترب",
                        "title": base_name,
                        "base_title": base_name,
                        "brand": brand,
                        "origin": origin,
                        "year": self._extract_year(base_name),
                        "shop_name": shop,
                        "price_toman": price_toman,
                        "pack_count": base_pack,
                        "unit_price_toman": (price_toman // base_pack) if base_pack else None,
                        "url": full_url,
                    })

        return all_offers, "ok"

    async def _fetch_digikala_offers(self, norm_size: str, w: str, a: str, r: str) -> List[Dict[str, Any]]:
        session = await self.get_session()
        offers: List[Dict[str, Any]] = []
        seen_ids = set()

        queries = (f"لاستیک {norm_size}", f"لاستیک {w}/{a}/{r}", f"تایر {w} {a} {r}")

        async def _query(q: str):
            try:
                async with session.get(
                    "https://api.digikala.com/v1/search/",
                    params={"q": q, "page": 1},
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json(content_type=None)
            except Exception as e:
                logger.warning(f"Digikala search error ({q}): {e}")
            return {}

        responses = await asyncio.gather(*[_query(q) for q in queries])
        for data in responses:
            for p in (data.get("data") or {}).get("products") or []:
                pid = p.get("id")
                if not pid or pid in seen_ids or p.get("status") != "marketable":
                    continue
                title = clean_search_text(p.get("title_fa") or "")
                title_en = clean_search_text(p.get("title_en") or "")
                if not matches_exact_tire_size(title + " " + title_en, w, a, r):
                    continue
                if self._is_downpayment_bait(title):
                    continue
                dv = p.get("default_variant") or {}
                price_rial = (dv.get("price") or {}).get("selling_price")
                if not price_rial:
                    continue
                price_toman = int(price_rial) // 10
                if not is_valid_car_tire_listing(title, price_toman):
                    continue
                seen_ids.add(pid)
                pack = detect_tire_pack_count(title)
                seller = clean_search_text((dv.get("seller") or {}).get("title") or "دیجی‌کالا")
                brand, origin = detect_tire_brand(title + " " + title_en)
                offers.append({
                    "source": "دیجی‌کالا",
                    "title": title,
                    "brand": brand,
                    "origin": origin,
                    "year": self._extract_year(title + " " + title_en),
                    "shop_name": seller,
                    "price_toman": price_toman,
                    "pack_count": pack,
                    "unit_price_toman": (price_toman // pack) if pack else None,
                    "url": f"https://www.digikala.com/product/dkp-{pid}/",
                })
        return offers

    async def _fetch_basalam_offers(self, norm_size: str, w: str, a: str, r: str) -> List[Dict[str, Any]]:
        session = await self.get_session()
        offers: List[Dict[str, Any]] = []
        seen_ids = set()

        queries = [
            (f"لاستیک {norm_size}", 40),
            (f"تایر {w} {a} {r}", 20),
        ]

        async def _query(q: str, sz: int):
            try:
                async with session.get(
                    "https://search.basalam.com/ai-engine/api/v2.0/product/search",
                    params={"q": q, "size": sz},
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json(content_type=None)
            except Exception as e:
                logger.warning(f"Basalam search error ({q}): {e}")
            return {}

        responses = await asyncio.gather(*[_query(q, sz) for q, sz in queries])
        for data in responses:
            for p in data.get("products") or []:
                pid = p.get("id")
                if not pid or pid in seen_ids:
                    continue
                if not p.get("IsAvailable", True) or not p.get("IsSaleable", True) or (p.get("stock") or 0) <= 0:
                    continue
                title = clean_search_text(p.get("name") or "")
                if not matches_exact_tire_size(title, w, a, r):
                    continue
                if self._is_downpayment_bait(title):
                    continue
                raw_price = p.get("price") or 0
                if not raw_price:
                    continue
                price_toman = int(round(float(raw_price) / 10))
                if not is_valid_car_tire_listing(title, price_toman):
                    continue
                seen_ids.add(pid)
                pack = detect_tire_pack_count(title)
                vendor = p.get("vendor") or {}
                v_name = clean_search_text(vendor.get("name") or vendor.get("title") or "غرفه‌دار باسلام")
                v_id = vendor.get("identifier")
                p_url = f"https://basalam.com/{v_id}/product/{pid}" if v_id else "https://basalam.com"
                brand, origin = detect_tire_brand(title)
                offers.append({
                    "source": "باسلام",
                    "title": title,
                    "brand": brand,
                    "origin": origin,
                    "year": self._extract_year(title),
                    "shop_name": v_name,
                    "price_toman": price_toman,
                    "pack_count": pack,
                    "unit_price_toman": (price_toman // pack) if pack else None,
                    "url": p_url,
                })
        return offers

    async def _fetch_hypertire_offers(self, norm_size: str) -> List[Dict[str, Any]]:
        try:
            raw = await self.hypertire.search_free_market(norm_size)
            for o in raw:
                _, origin = detect_tire_brand(o.get("title", ""))
                o["origin"] = origin
            return raw
        except Exception as e:
            logger.warning(f"HyperTire free market error: {e}")
            return []

    async def fetch_live_market_prices(self, raw_size: str, force_refresh: bool = False) -> Dict[str, Any]:
        """
        استعلام لحظه‌ای و زنده قیمت بازار آزاد برای سایز درخواستی با دقت بسیار بالا
        """
        parts = parse_size_parts(raw_size)
        if not parts:
            return {"ok": False, "error": "سایز تایر نامعتبر است."}

        w, a, r = parts
        norm_size = f"{w}/{a}R{r}"
        now_info = get_tehran_now()

        if not force_refresh and norm_size in self._price_cache:
            exp_ts, cached_res = self._price_cache[norm_size]
            if time.monotonic() < exp_ts:
                fresh_copy = dict(cached_res)
                fresh_copy["timestamp"] = now_info
                fresh_copy["cached"] = True
                return fresh_copy

        t0 = time.perf_counter()

        torob_task = self._fetch_torob_offers(norm_size, w, a, r)
        dk_task = self._fetch_digikala_offers(norm_size, w, a, r)
        basalam_task = self._fetch_basalam_offers(norm_size, w, a, r)
        ht_task = self._fetch_hypertire_offers(norm_size)

        torob_res, dk_list, basalam_list, ht_list = await asyncio.gather(
            torob_task, dk_task, basalam_task, ht_task, return_exceptions=True
        )

        torob_list: List[Dict[str, Any]] = []
        torob_status = "error"
        if isinstance(torob_res, tuple):
            torob_list, torob_status = torob_res

        combined: List[Dict[str, Any]] = []
        source_counts: Dict[str, int] = {}
        source_status: Dict[str, str] = {
            "ترب": torob_status,
            "دیجی‌کالا": "ok" if isinstance(dk_list, list) else "error",
            "باسلام": "ok" if isinstance(basalam_list, list) else "error",
            "هایپرتایر": "ok" if isinstance(ht_list, list) else "error",
        }

        for s_name, batch in (
            ("ترب", torob_list),
            ("دیجی‌کالا", dk_list),
            ("باسلام", basalam_list),
            ("هایپرتایر", ht_list),
        ):
            if isinstance(batch, list):
                source_counts[s_name] = len(batch)
                combined.extend(batch)
            else:
                source_counts[s_name] = 0

        # حذف موارد تکراری مشابه
        deduped: List[Dict[str, Any]] = []
        seen_sig = set()
        for off in combined:
            sig = (off["source"], off["shop_name"], off["brand"], off["price_toman"], off.get("pack_count"))
            if sig not in seen_sig:
                seen_sig.add(sig)
                deduped.append(off)

        # تفکیک پیشنهادهای دارای تعداد حلقه شفاف vs نامشخص (تا قیمت تک با جفت قاطی نشود)
        confirmed = [o for o in deduped if o["unit_price_toman"] is not None]
        unspecified = [o for o in deduped if o["unit_price_toman"] is None]

        ir_confirmed = sorted([o for o in confirmed if o["origin"] == "IR"], key=lambda x: x["unit_price_toman"])
        imp_confirmed = sorted([o for o in confirmed if o["origin"] != "IR"], key=lambda x: x["unit_price_toman"])

        def _drop_extreme_outliers(items: List[Dict[str, Any]], max_ratio: float = 2.0) -> List[Dict[str, Any]]:
            if len(items) < 4:
                return items
            median_u = items[len(items) // 2]["unit_price_toman"]
            return [
                x
                for x in items
                if int(median_u * 0.45) <= x["unit_price_toman"] <= int(median_u * max_ratio)
            ]

        ir_confirmed = _drop_extreme_outliers(ir_confirmed, max_ratio=1.75)
        imp_confirmed = _drop_extreme_outliers(imp_confirmed, max_ratio=2.4)

        def _build_summary(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if not items:
                return None
            mid = items[len(items) // 2]["unit_price_toman"]
            p85_idx = min(len(items) - 1, int(len(items) * 0.85))
            min_u = items[0]["unit_price_toman"]
            typ_max_u = items[p85_idx]["unit_price_toman"]
            return {
                "min_unit": min_u,
                "max_unit": typ_max_u,
                "median_unit": mid,
                "min_pair": min_u * 2,
                "max_pair": typ_max_u * 2,
                "count": len(items),
            }

        ir_summary = _build_summary(ir_confirmed)
        imp_summary = _build_summary(imp_confirmed)

        unspecified.sort(key=lambda x: x["price_toman"])
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)

        result = {
            "ok": True,
            "size": norm_size,
            "timestamp": now_info,
            "latency_ms": latency_ms,
            "cached": False,
            "source_counts": source_counts,
            "source_status": source_status,
            "total_found": len(ir_confirmed) + len(imp_confirmed) + len(unspecified),
            "ir_summary": ir_summary,
            "imp_summary": imp_summary,
            "ir_offers": ir_confirmed,
            "imp_offers": imp_confirmed,
            "unspecified_offers": unspecified,
        }
        if result["total_found"] > 0:
            self._price_cache[norm_size] = (time.monotonic() + 60.0, result)
        return result
