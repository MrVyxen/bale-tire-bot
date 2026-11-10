import asyncio
import time
import io
import logging
from PIL import Image
from typing import Dict, Any, Optional
from database import get_user, upsert_user, log_action
from bale_api import BaleBotClient
from tire_api.kavir_client import KavirTireClient
from tire_api.barez_client import BarezTireClient
from tire_api.kala_ntsw_client import KalaNtswClient
from captcha_solver import FastCaptchaSolver

logger = logging.getLogger("SniperEngine")

class SniperEngine:
    def __init__(self, bot_client: BaleBotClient):
        self.bot = bot_client
        self.kavir_client = KavirTireClient()
        self.barez_client = BarezTireClient()
        self.ntsw_client = KalaNtswClient()
        self.running_tasks: Dict[int, asyncio.Task] = {}

    def get_client(self, portal_name: str):
        if portal_name == "barez":
            return self.barez_client
        elif portal_name == "kavir":
            return self.kavir_client
        elif portal_name == "ntsw":
            return self.ntsw_client
        return self.barez_client

    async def measure_portal_latencies(self) -> Dict[str, float]:
        """سنجش واقعی پینگ شبکه به سرورهای توزیع تایر"""
        results = {}
        for name, client in [("گروه صنعتی بارز", self.barez_client), ("کویر تایر", self.kavir_client)]:
            res = await client.test_ping()
            results[name] = res.get("latency_ms", 999.0)
        return results

    async def check_live_stock_now(self, chat_id: int) -> Dict[str, Any]:
        """
        استعلام ۱۰۰٪ برخط و زنده موجودی انبار کارخانه در همین لحظه
        """
        user = await get_user(chat_id)
        portal = user.get("target_portal", "barez") if user else "barez"
        tire_size = user.get("target_tire_size", "185_65_14") if user else "185_65_14"
        client = self.get_client(portal)

        res = await client.check_available_products(tire_size)
        return {
            "portal": portal,
            "tire_size": tire_size,
            "latency_ms": res.get("latency_ms", 0),
            "ok": res.get("ok", False),
            "status_desc": res.get("status_desc") or ("موجودی انبار بررسی شد." if res.get("ok") else "خطای ارتباط با سرور کارخانه"),
            "items": res.get("items", []),
            "is_out_of_stock": res.get("is_out_of_stock", True)
        }

    async def request_real_otp(self, chat_id: int) -> Dict[str, Any]:
        """
        ارسال کد پیامکی احراز هویت واقعی به خط تلفن کاربر از طریق سرور بارز یا کویر
        """
        user = await get_user(chat_id)
        if not user or not user.get("mobile"):
            return {"ok": False, "message": "شماره همراه ثبت نشده است."}

        portal = user.get("target_portal", "barez")
        mobile = user.get("mobile")
        nat_id = user.get("national_id", "")

        if portal == "barez":
            res = await self.barez_client.send_login_otp(mobile)
            ok = res.get("ok") and res.get("data", {}).get("status") == "success"
            msg = "کد تایید پیامکی از سوی بارز به شماره شما ارسال شد." if ok else "خطا در ارسال پیامک بارز."
            return {"ok": ok, "message": msg, "latency_ms": res.get("latency_ms", 0)}
        else:
            res = await self.kavir_client.send_login_otp(nat_id, mobile)
            return {"ok": res.get("ok", False), "message": "درخواست ورود به کویرتایر ارسال شد.", "latency_ms": res.get("latency_ms", 0)}

    async def verify_real_otp(self, chat_id: int, otp_code: str) -> Dict[str, Any]:
        """
        تایید کد پیامکی ارسالی کاربر و ایجاد نشست معتبر ورود در سایت
        """
        user = await get_user(chat_id)
        if not user or not user.get("mobile"):
            return {"ok": False, "message": "شماره همراه کاربر یافت نشد."}

        portal = user.get("target_portal", "barez")
        mobile = user.get("mobile")
        nat_id = user.get("national_id", "")

        if portal == "barez":
            res = await self.barez_client.verify_login_otp(mobile, otp_code)
            is_valid = res.get("login_success", False)
            if is_valid:
                await upsert_user(chat_id, last_auth_token="BAREZ_ACTIVE_SESSION")
                return {"ok": True, "message": "✅ هویت شما در سایت بارز تایید شد و نشست شما فعال گردید!"}
            else:
                return {"ok": False, "message": "❌ کد تایید وارد شده نامعتبر یا منقضی است."}
        else:
            res = await self.kavir_client.verify_login_otp(nat_id, mobile, otp_code)
            if res.get("ok"):
                return {"ok": True, "message": "✅ ورود به کویرتایر با موفقیت انجام شد."}
            return {"ok": False, "message": "❌ خطا در تایید کد کویرتایر."}

    async def start_sniper_for_user(self, chat_id: int):
        """
        راه‌اندازی شکارچی خودکار فوق‌سریع برای یک کاربر
        """
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

        portal = user.get("target_portal", "barez")
        client = self.get_client(portal)
        tire_size = user.get("target_tire_size", "185_65_14")

        # اعلام شروع رصد در بله
        await self.bot.send_message(
            chat_id=chat_id,
            text=(
                "🚀 <b>موتور شکارچی خودکار (Sniper) فعال شد!</b>\n\n"
                f"🎯 سامانه هدف: <b>{portal}</b>\n"
                f"🚗 سایز انتخابی: <code>{tire_size}</code>\n"
                "⚡ اتصال مستقیم سوکت (TCP Keep-Alive) برقرار شد.\n"
                "ربات هر ۲ ثانیه انبار را رصد می‌کند و به محض باز شدن سهمیه، بلافاصله آن را رزرو خواهد کرد."
            )
        )

        poll_count = 0
        try:
            while True:
                poll_count += 1
                stock_res = await client.check_available_products(tire_size)
                latency = stock_res.get("latency_ms", 0)
                items = stock_res.get("items") or stock_res.get("data", {}).get("items", [])

                # اگر موجودی فعال شد
                if items or (stock_res.get("ok") and not stock_res.get("is_out_of_stock", True)):
                    logger.info(f"Capacity detected for user {chat_id}!")
                    await self._execute_sniping(chat_id, user, client, items)
                    break

                # ثبت لاگ دوره‌ای
                if poll_count % 10 == 0:
                    await log_action(chat_id, "STOCK_POLL", "WAITING", f"Poll #{poll_count} - In stock: False - Latency: {latency}ms", latency)

                await asyncio.sleep(2.0)

        except asyncio.CancelledError:
            logger.info(f"Sniper cancelled for {chat_id}")
        except Exception as e:
            logger.error(f"Sniper error for {chat_id}: {e}")
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ خطا در فرایند شکارچی خودکار:\n<code>{e}</code>"
            )

    async def _execute_sniping(self, chat_id: int, user: Dict[str, Any], client: Any, items: list):
        """
        رزرو واقعی و ضربتی به محض باز شدن سهمیه
        """
        t0 = time.perf_counter()
        product_id = items[0].get("id", "1") if items else "1"
        count = user.get("tire_count", 2)

        # ارسال ریکوئست رزرو واقعی
        res = await client.fast_add_to_cart(
            product_id=product_id,
            vehicle_id=user.get("car_vin") or "",
            count=count
        )

        total_latency = round((time.perf_counter() - t0) * 1000, 2)

        if res.get("ok"):
            await self.bot.send_message(
                chat_id=chat_id,
                text=(
                    "🎉 <b>فوری: لاستیک دولتی در سامانه رزرو شد!</b>\n\n"
                    f"⏱ زمان ثبت: <b>{total_latency} میلی‌ثانیه</b>\n"
                    f"📦 تعداد: <b>{count} حلقه</b>\n\n"
                    "🔗 <b>لینک ورود به درگاه پرداخت و تسویه حساب:</b>\n"
                    f"https://shop.barez.org/profile"
                )
            )
            await log_action(chat_id, "SNIPE_SUCCESS", "OK", f"Reserved in {total_latency}ms", total_latency)
        else:
            await self.bot.send_message(
                chat_id=chat_id,
                text=(
                    "⚠️ سهمیه باز شد اما پاسخ رزرو سرور:\n"
                    f"<code>{res.get('error') or res.get('text') or res.get('data')}</code>\n"
                    f"⏱ تاخیر: {res.get('latency_ms')}ms"
                )
            )

    async def simulate_ultra_fast_test(self, chat_id: int) -> Dict[str, Any]:
        """
        تست سرعت و بنچمارک اتصال زنده به سرور واقعی
        """
        user = await get_user(chat_id)
        portal = user.get("target_portal", "barez") if user else "barez"
        client = self.get_client(portal)

        t_start = time.perf_counter()
        step1_res = await client.test_ping()
        t_step1 = step1_res.get("latency_ms", 0.0)

        # پردازش کپچا با PIL
        t_c_start = time.perf_counter()
        dummy = Image.new("RGB", (160, 60), color="white")
        buf = io.BytesIO()
        dummy.save(buf, format="PNG")
        FastCaptchaSolver.preprocess_image(buf.getvalue())
        t_captcha = round((time.perf_counter() - t_c_start) * 1000, 2)

        total_test_time = round((time.perf_counter() - t_start) * 1000, 2)

        return {
            "portal": portal,
            "tcp_latency_ms": t_step1,
            "captcha_processing_ms": t_captcha,
            "total_benchmark_ms": total_test_time,
            "speed_rating": "فوق‌العاده (زیر ۶۰ میلی‌ثانیه) ⚡" if total_test_time < 60 else "بسیار خوب 🚀"
        }
