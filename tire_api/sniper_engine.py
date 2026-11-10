import asyncio
import logging
import time
from typing import Dict, Any, List, Optional
from config import PORTALS
from database import get_user, upsert_user, log_action
from bale_api import BaleBotClient
from telemetry import telemetry
from tire_api.hypertire_client import HyperTireClient
from tire_api.barez_client import BarezTireClient
from tire_api.kavir_client import KavirTireClient
from tire_api.kala_ntsw_client import KalaNtswClient
from tire_api.multi_portal_client import FactoryPortalClient
from tire_api.market_price_client import MarketPriceClient
from tire_api.utils import key_to_size, normalize_tire_size, parse_size_parts, size_to_key

logger = logging.getLogger("SniperEngine")


class SniperEngine:
    def __init__(self, bot_client: BaleBotClient):
        self.bot = bot_client
        self.hypertire_client = HyperTireClient()
        self.barez_client = BarezTireClient()
        self.kavir_client = KavirTireClient()
        self.ntsw_client = KalaNtswClient()
        self.factory_clients: Dict[str, FactoryPortalClient] = {
            k: FactoryPortalClient(k)
            for k in ("irantire", "yazd", "razi", "kian", "artawheel", "dena")
        }
        self.market_client = MarketPriceClient(self.hypertire_client)
        self.running_tasks: Dict[int, asyncio.Task] = {}

    async def close_all(self):
        for client in (
            self.hypertire_client,
            self.barez_client,
            self.kavir_client,
            self.ntsw_client,
            *self.factory_clients.values(),
            self.market_client,
        ):
            try:
                await client.close()
            except Exception:
                pass

    def get_client(self, portal_name: str):
        if portal_name == "hypertire":
            return self.hypertire_client
        if portal_name == "barez":
            return self.barez_client
        if portal_name == "kavir":
            return self.kavir_client
        if portal_name == "ntsw":
            return self.ntsw_client
        if portal_name in self.factory_clients:
            return self.factory_clients[portal_name]
        return self.barez_client

    async def scan_all_portals_live(
        self, target_portal: str = "all", filter_size_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        اسکن هم‌زمان و واقعی تمام سایت‌ها و کارخانه‌های فروش تایر دولتی.
        خروجی شامل وضعیت زنده تک‌تک پورتال‌ها + سایزهای واقعاً موجود + کاتالوگ کشف‌شده از سایت‌هاست.
        """
        keys_to_scan = (
            ["hypertire", "barez", "kavir", "irantire", "yazd", "razi", "kian", "artawheel", "dena", "ntsw"]
            if target_portal == "all"
            else [target_portal]
        )

        async def _probe_one(p_key: str) -> Dict[str, Any]:
            info = PORTALS.get(p_key, {})
            if p_key == "hypertire":
                r = await self.hypertire_client.scan_dolati_inventory(include_catalog_pages=2)
                in_stock = r.get("in_stock_items", [])
                cat_sizes = sorted({it["size"] for it in r.get("catalog_items", []) if it.get("size")})
                return {
                    "portal": p_key,
                    "title": info.get("short", p_key),
                    "url": info.get("base_url", ""),
                    "ok": r.get("ok", False),
                    "latency_ms": r.get("latency_ms", 0),
                    "in_stock_items": in_stock,
                    "catalog_sizes": cat_sizes,
                    "vpn_blocked": False,
                    "anti_bot": False,
                    "status_desc": r.get("status_desc", ""),
                }
            if p_key == "barez":
                r = await self.barez_client.scan_all_rings()
                return {
                    "portal": p_key,
                    "title": info.get("short", p_key),
                    "url": info.get("base_url", ""),
                    "ok": r.get("ok", False),
                    "latency_ms": r.get("latency_ms", 0),
                    "in_stock_items": r.get("in_stock_items", []),
                    "catalog_sizes": [],
                    "vpn_blocked": False,
                    "anti_bot": False,
                    "status_desc": r.get("status_desc", ""),
                }

            client = self.get_client(p_key)
            r = await client.check_available_products(filter_size_key)
            return {
                "portal": p_key,
                "title": info.get("short", p_key),
                "url": info.get("base_url", ""),
                "ok": r.get("ok", False),
                "latency_ms": r.get("latency_ms", 0),
                "in_stock_items": r.get("items", []),
                "catalog_sizes": r.get("catalog_sizes", []),
                "vpn_blocked": r.get("vpn_blocked", False),
                "anti_bot": r.get("anti_bot", False),
                "status_desc": r.get("status_desc", ""),
            }

        results = await asyncio.gather(*[_probe_one(k) for k in keys_to_scan], return_exceptions=True)

        portals_status: List[Dict[str, Any]] = []
        all_in_stock_items: List[Dict[str, Any]] = []
        catalog_sizes_set = set()

        for res in results:
            if isinstance(res, dict):
                portals_status.append(res)
                in_stock = res.get("in_stock_items", [])
                all_in_stock_items.extend(in_stock)
                in_stock_sizes = [it.get("size", "") for it in in_stock if it.get("size")]
                telemetry.record_portal_probe(
                    portal_key=res.get("portal", ""),
                    title=res.get("title", ""),
                    ok=bool(res.get("ok", False)),
                    latency_ms=float(res.get("latency_ms", 0.0)),
                    in_stock_count=len(in_stock),
                    vpn_blocked=bool(res.get("vpn_blocked", False)),
                    anti_bot=bool(res.get("anti_bot", False)),
                    status_desc=res.get("status_desc", ""),
                    in_stock_sizes=in_stock_sizes,
                )
                for cs in res.get("catalog_sizes", []):
                    norm = normalize_tire_size(cs) or cs
                    catalog_sizes_set.add(norm)

        # تجمیع سایزهایی که هم‌اکنون موجودی واقعی دارند
        available_sizes: Dict[str, Dict[str, Any]] = {}
        for it in all_in_stock_items:
            sz = it.get("size") or ""
            sk = it.get("size_key") or size_to_key(sz)
            if not sk:
                continue
            bucket = available_sizes.setdefault(
                sk,
                {
                    "size_key": sk,
                    "size": sz,
                    "count": 0,
                    "min_price_toman": 0,
                    "portals": set(),
                    "brands": set(),
                    "items": [],
                },
            )
            bucket["count"] += 1
            bucket["items"].append(it)
            if it.get("portal_title"):
                bucket["portals"].add(it["portal_title"])
            if it.get("brand"):
                bucket["brands"].add(it["brand"])
            pr = int(it.get("price_toman") or 0)
            if pr > 0 and (bucket["min_price_toman"] == 0 or pr < bucket["min_price_toman"]):
                bucket["min_price_toman"] = pr

        for sk, b in available_sizes.items():
            b["portals"] = sorted(b["portals"])
            b["brands"] = sorted(b["brands"])

        # فیلتر بر اساس سایز انتخابی کاربر (در صورت درخواست)
        matched_items = all_in_stock_items
        if filter_size_key:
            f_parts = parse_size_parts(filter_size_key)
            if f_parts:
                matched_items = [
                    it
                    for it in all_in_stock_items
                    if parse_size_parts(it.get("size", "")) == f_parts
                ]

        return {
            "portals_status": portals_status,
            "all_in_stock_items": all_in_stock_items,
            "matched_items": matched_items,
            "available_sizes": available_sizes,
            "catalog_sizes": sorted(catalog_sizes_set),
        }

    async def check_live_stock_now(self, chat_id: int) -> Dict[str, Any]:
        """استعلام ۱۰۰٪ برخط و زنده موجودی انبار همه یا سامانه انتخابی کاربر"""
        user = await get_user(chat_id)
        portal = user.get("target_portal", "all") if user else "all"
        tire_size = user.get("target_tire_size", "185_65_14") if user else "185_65_14"

        scan = await self.scan_all_portals_live(portal, filter_size_key=tire_size)
        return {
            "portal": portal,
            "tire_size": tire_size,
            "tire_size_display": key_to_size(tire_size),
            "portals_status": scan["portals_status"],
            "matched_items": scan["matched_items"],
            "all_in_stock_items": scan["all_in_stock_items"],
            "available_sizes": scan["available_sizes"],
        }

    async def request_real_otp(self, chat_id: int, portal_override: Optional[str] = None) -> Dict[str, Any]:
        """ارسال کد پیامکی احراز هویت واقعی به خط تلفن کاربر از طریق بارز یا کویرتایر"""
        user = await get_user(chat_id)
        if not user or not user.get("mobile"):
            return {"ok": False, "message": "شماره همراه ثبت نشده است."}

        portal = portal_override or user.get("target_portal", "barez")
        if portal == "all":
            portal = "barez"
        mobile = user.get("mobile")
        nat_id = user.get("national_id", "")

        if portal == "barez":
            res = await self.barez_client.send_login_otp(mobile)
            ok = res.get("ok") and res.get("data", {}).get("status") == "success"
            msg = "کد تایید پیامکی از سوی بارز به شماره شما ارسال شد." if ok else "خطا در ارسال پیامک بارز (ممکن است خارج از ساعات فروش باشد)."
            return {"ok": ok, "portal": "barez", "message": msg, "latency_ms": res.get("latency_ms", 0)}

        if portal == "kavir":
            res = await self.kavir_client.send_login_otp(nat_id, mobile)
            if res.get("status_code") == 403 or "ایران" in res.get("text", ""):
                return {
                    "ok": False,
                    "portal": "kavir",
                    "message": "کویرتایر به دلیل روشن بودن فیلترشکن (آی‌پی غیرایرانی) کد پیامکی ارسال نکرد. VPN را خاموش کنید.",
                }
            ok = bool(res.get("ok"))
            return {
                "ok": ok,
                "portal": "kavir",
                "message": "درخواست کد پیامکی به کویرتایر ارسال شد." if ok else "کویرتایر فعلاً پاسخ نداد.",
                "latency_ms": res.get("latency_ms", 0),
            }

        return {
            "ok": False,
            "portal": portal,
            "message": f"پورتال «{PORTALS.get(portal, {}).get('short', portal)}» ثبت‌نام مستقیم با کد پیامکی ربات ندارد؛ برای بارز یا کویرتایر استفاده کنید.",
        }

    async def verify_real_otp(self, chat_id: int, otp_code: str, portal_override: Optional[str] = None) -> Dict[str, Any]:
        """تایید کد پیامکی ارسالی کاربر و ایجاد نشست معتبر ورود در سایت"""
        user = await get_user(chat_id)
        if not user or not user.get("mobile"):
            return {"ok": False, "message": "شماره همراه کاربر یافت نشد."}

        portal = portal_override or user.get("target_portal", "barez")
        if portal == "all":
            portal = "barez"
        mobile = user.get("mobile")
        nat_id = user.get("national_id", "")

        if portal == "barez":
            res = await self.barez_client.verify_login_otp(mobile, otp_code)
            is_valid = res.get("login_success", False)
            if is_valid:
                await upsert_user(chat_id, last_auth_token="BAREZ_ACTIVE_SESSION")
                return {"ok": True, "message": "✅ هویت شما در سایت بارز تایید شد و نشست شما فعال گردید!"}
            return {"ok": False, "message": "❌ کد تایید وارد شده نامعتبر یا منقضی است."}

        if portal == "kavir":
            res = await self.kavir_client.verify_login_otp(nat_id, mobile, otp_code)
            if res.get("ok"):
                await upsert_user(chat_id, last_auth_token="KAVIR_ACTIVE_SESSION")
                return {"ok": True, "message": "✅ ورود به کویرتایر با موفقیت انجام شد."}
            return {"ok": False, "message": "❌ خطا در تایید کد کویرتایر."}

        return {"ok": False, "message": "❌ پورتال انتخابی از ورود پیامکی پشتیبانی نمی‌کند."}

    async def start_sniper_for_user(self, chat_id: int):
        """راه‌اندازی شکارچی خودکار چندپورتالی برای یک کاربر"""
        if chat_id in self.running_tasks and not self.running_tasks[chat_id].done():
            return
        task = asyncio.create_task(self._sniper_worker(chat_id))
        self.running_tasks[chat_id] = task

    async def stop_sniper_for_user(self, chat_id: int):
        if chat_id in self.running_tasks:
            task = self.running_tasks[chat_id]
            task.cancel()
            del self.running_tasks[chat_id]
        await upsert_user(chat_id, sniper_enabled=0)

    async def _sniper_worker(self, chat_id: int):
        logger.info(f"Sniper worker started for chat_id={chat_id}")
        user = await get_user(chat_id)
        if not user:
            return

        portal = user.get("target_portal", "all")
        tire_size = user.get("target_tire_size", "185_65_14")
        size_display = key_to_size(tire_size)
        portal_title = PORTALS.get(portal, {}).get("title", portal)

        await self.bot.send_message(
            chat_id=chat_id,
            text=(
                "🚀 <b>شکارچی خودکار تایر دولتی روشن شد!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🏭 <b>سامانه هدف:</b> <code>{portal_title}</code>\n"
                f"🛞 <b>سایز هدف:</b> <code>{size_display}</code>\n"
                f"📦 <b>تعداد درخواستی:</b> <b>{user.get('tire_count', 2)} حلقه</b>\n\n"
                "⚡ ربات هر ۳ ثانیه سایت‌های انتخاب‌شده را بررسی می‌کند و به محض باز شدن موجودی، فوراً آن را رزرو و لینک پرداخت را برایتان می‌فرستد."
            ),
        )

        poll_count = 0
        try:
            while True:
                poll_count += 1
                # رفرش تنظیمات کاربر در هر چرخه در صورتی که سایز را تغییر داده باشد
                fresh_user = await get_user(chat_id)
                if not fresh_user or not fresh_user.get("sniper_enabled", 0):
                    break
                portal = fresh_user.get("target_portal", "all")
                tire_size = fresh_user.get("target_tire_size", "185_65_14")

                if portal == "all":
                    scan = await self.scan_all_portals_live("all", filter_size_key=tire_size)
                    matched = scan["matched_items"]
                    if matched:
                        chosen = matched[0]
                        client = self.get_client(chosen["portal"])
                        await self._execute_sniping(chat_id, fresh_user, client, chosen)
                        break
                else:
                    client = self.get_client(portal)
                    stock_res = await client.check_available_products(tire_size)
                    items = stock_res.get("items") or []
                    if items or (stock_res.get("ok") and not stock_res.get("is_out_of_stock", True)):
                        chosen = items[0] if items else {"portal": portal, "id": "1", "url": PORTALS.get(portal, {}).get("base_url", "")}
                        await self._execute_sniping(chat_id, fresh_user, client, chosen)
                        break

                if poll_count % 20 == 0:
                    await log_action(chat_id, "STOCK_POLL", "WAITING", f"Poll #{poll_count} ({portal} / {tire_size})", 0.0)

                await asyncio.sleep(3.0)

        except asyncio.CancelledError:
            logger.info(f"Sniper cancelled for {chat_id}")
        except Exception as e:
            logger.error(f"Sniper error for {chat_id}: {e}")
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ خطا در چرخه شکارچی خودکار:\n<code>{e}</code>",
            )

    async def _execute_sniping(self, chat_id: int, user: Dict[str, Any], client: Any, item: Dict[str, Any]):
        """رزرو واقعی و ضربتی در کسری از ثانیه به محض مشاهده موجودی"""
        t0 = time.perf_counter()
        portal_key = item.get("portal") or user.get("target_portal", "barez")
        product_id = item.get("selector") or item.get("id") or "1"
        count = int(user.get("tire_count", 2) or 2)
        if item.get("max_qty") and count > int(item["max_qty"]):
            count = int(item["max_qty"])

        res = await client.fast_add_to_cart(
            product_id=str(product_id),
            vehicle_id=user.get("car_vin") or "",
            count=count,
        )
        total_latency = round((time.perf_counter() - t0) * 1000, 1)
        checkout_url = res.get("checkout_url") or item.get("url") or PORTALS.get(portal_key, {}).get("base_url", "")

        await upsert_user(chat_id, sniper_enabled=0)

        if res.get("ok"):
            await self.bot.send_message(
                chat_id=chat_id,
                text=(
                    "🎉 <b>فوری: تایر دولتی موجود و رزرو شد!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🏭 <b>فروشگاه/کارخانه:</b> {item.get('portal_title', portal_key)}\n"
                    f"🛞 <b>محصول:</b> <code>{item.get('title', item.get('size', ''))}</code>\n"
                    f"📦 <b>تعداد رزرو:</b> <b>{count} حلقه</b>\n"
                    f"⏱ <b>سرعت شلیک:</b> <b>{total_latency} میلی‌ثانیه</b>\n\n"
                    f"🔗 <b>لینک تکمیل خرید و پرداخت:</b>\n{checkout_url}"
                ),
            )
            await log_action(chat_id, "SNIPE_SUCCESS", "OK", f"Reserved on {portal_key} in {total_latency}ms", total_latency)
        else:
            await self.bot.send_message(
                chat_id=chat_id,
                text=(
                    "🚨 <b>سهمیه باز شد! (نیازمند ورود یا تکمیل دستی فوری)</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🏭 <b>سامانه:</b> {item.get('portal_title', portal_key)}\n"
                    f"🛞 <b>سایز و مدل:</b> <code>{item.get('size', '')} — {item.get('title', '')}</code>\n"
                    f"⚙️ <b>پاسخ سامانه به رزرو:</b> <code>{res.get('error') or res.get('status_code')}</code>\n\n"
                    f"🔗 <b>همین الان وارد لینک زیر شوید و سبد را نهایی کنید:</b>\n{checkout_url}"
                ),
            )
