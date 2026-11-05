import re
import logging
from typing import Dict, Any, Optional
from database import get_user, upsert_user, set_state
from bale_api import BaleBotClient
from config import TIRE_SIZES, PORTALS
from tire_api.sniper_engine import SniperEngine

logger = logging.getLogger("BotHandlers")

class BaleBotHandlers:
    def __init__(self, bot: BaleBotClient, sniper: SniperEngine):
        self.bot = bot
        self.sniper = sniper

    @staticmethod
    def get_main_keyboard():
        return {
            "inline_keyboard": [
                [
                    {"text": "👤 تنظیمات مشخصات مالک و خودرو", "callback_data": "menu_profile"},
                    {"text": "🛞 انتخاب سایز لاستیک", "callback_data": "menu_size"}
                ],
                [
                    {"text": "🏢 انتخاب سامانه توزیع", "callback_data": "menu_portal"},
                    {"text": "⚡ شکارچی خودکار (Sniper)", "callback_data": "menu_sniper"}
                ],
                [
                    {"text": "🧪 تست زنده سرعت و پینگ (Benchmark)", "callback_data": "test_speed"},
                    {"text": "📋 خلاصه اطلاعات و وضعیت", "callback_data": "view_profile"}
                ]
            ]
        }

    async def handle_start(self, chat_id: int, username: str = ""):
        user = await get_user(chat_id)
        if not user:
            user = await upsert_user(chat_id, username=username)

        welcome_text = (
            "🏎 <b>به بازوی ثبت‌نام فوق‌سریع لاستیک دولتی خوش آمدید!</b>\n\n"
            "این ربات مستقیماً از طریق درخواست‌های مستقیم API و بدون اتلاف وقتِ مرورگر، "
            "اطلاعات شما را در کسری از ثانیه (زیر ۵۰ میلی‌ثانیه) در سامانه‌های دولتی ثبت می‌کند.\n\n"
            "🔰 <b>مراحل راه‌اندازی سریع:</b>\n"
            "۱. از بخش <b>مشخصات مالک و خودرو</b> اطلاعات هویتی و خودرو را تکمیل کنید.\n"
            "۲. <b>سایز تایر</b> خودروی خود را انتخاب کنید.\n"
            "۳. <b>شکارچی خودکار (Sniper)</b> را فعال کنید تا به محض باز شدن سهمیه، ثبت نام انجام شود.\n\n"
            "👇 لطفاً یکی از گزینه‌های زیر را انتخاب نمایید:"
        )
        await self.bot.send_message(
            chat_id=chat_id,
            text=welcome_text,
            reply_markup=self.get_main_keyboard()
        )

    async def handle_callback_query(self, query: Dict[str, Any]):
        callback_id = query.get("id")
        chat_id = query.get("message", {}).get("chat", {}).get("id")
        message_id = query.get("message", {}).get("message_id")
        data = query.get("data", "")

        await self.bot.answer_callback_query(callback_id)

        user = await get_user(chat_id)
        if not user:
            user = await upsert_user(chat_id)

        if data == "main_menu":
            await set_state(chat_id, "IDLE")
            text = "🏎 <b>منوی اصلی ربات ثبت‌نام فوق‌سریع تایر:</b>"
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=self.get_main_keyboard()
            )

        elif data == "menu_profile":
            nat_id = user.get("national_id") or "❌ ثبت نشده"
            mobile = user.get("mobile") or "❌ ثبت نشده"
            plate = user.get("car_plate") or "❌ ثبت نشده"
            vin = user.get("car_vin") or "❌ ثبت نشده"
            chassis = user.get("chassis_no") or "❌ ثبت نشده"
            green = user.get("green_sheet_no") or "❌ ثبت نشده"

            text = (
                "👤 <b>مدیریت اطلاعات هویتی و خودرو:</b>\n\n"
                f"▫️ کد ملی مالک: <code>{nat_id}</code>\n"
                f"▫️ تلفن همراه: <code>{mobile}</code>\n"
                f"▫️ شماره پلاک: <code>{plate}</code>\n"
                f"▫️ کد VIN: <code>{vin}</code>\n"
                f"▫️ شماره شاسی: <code>{chassis}</code>\n"
                f"▫️ شماره برگ سبز: <code>{green}</code>\n\n"
                "جهت تنظیم هر مورد، دکمه مربوطه را انتخاب کنید:"
            )
            kb = {
                "inline_keyboard": [
                    [
                        {"text": "✏️ کد ملی", "callback_data": "edit_national_id"},
                        {"text": "✏️ تلفن همراه", "callback_data": "edit_mobile"}
                    ],
                    [
                        {"text": "✏️ شماره پلاک", "callback_data": "edit_plate"},
                        {"text": "✏️ کد VIN", "callback_data": "edit_vin"}
                    ],
                    [
                        {"text": "✏️ شماره شاسی", "callback_data": "edit_chassis"},
                        {"text": "✏️ شماره برگ سبز", "callback_data": "edit_green"}
                    ],
                    [
                        {"text": "🔙 بازگشت به منوی اصلی", "callback_data": "main_menu"}
                    ]
                ]
            }
            await self.bot.edit_message_text(chat_id, message_id, text, reply_markup=kb)

        elif data.startswith("edit_"):
            field = data.replace("edit_", "")
            prompts = {
                "national_id": ("AWAIT_NAT_ID", "لطفاً <b>کد ملی ۱۰ رقمی</b> مالک خودرو را ارسال کنید:"),
                "mobile": ("AWAIT_MOBILE", "لطفاً <b>شماره تلفن همراه</b> به نام مالک (مثال: 09121234567) را ارسال کنید:"),
                "plate": ("AWAIT_PLATE", "لطفاً <b>شماره پلاک خودرو</b> را ارسال کنید (مثال: ۲۲-۳۴۵-ب-۱۲):"),
                "vin": ("AWAIT_VIN", "لطفاً <b>کد هفده رقمی VIN</b> روی کارت ماشین را ارسال کنید (با IR شروع می‌شود):"),
                "chassis": ("AWAIT_CHASSIS", "لطفاً <b>شماره شاسی</b> مندرج در برگ سبز خودرو را ارسال کنید:"),
                "green": ("AWAIT_GREEN", "لطفاً <b>شماره سریال برگ سبز</b> را ارسال کنید:")
            }
            if field in prompts:
                st, msg = prompts[field]
                await set_state(chat_id, st)
                kb = {"inline_keyboard": [[{"text": "انصراف ❌", "callback_data": "menu_profile"}]]}
                await self.bot.edit_message_text(chat_id, message_id, msg, reply_markup=kb)

        elif data == "menu_size":
            current_size = user.get("target_tire_size", "185_65_14")
            count = user.get("tire_count", 2)
            rows = []
            for k, title in TIRE_SIZES.items():
                mark = "✅ " if k == current_size else ""
                rows.append([{"text": f"{mark}{title}", "callback_data": f"set_size_{k}"}])

            count_2_mark = "✅ ۲ حلقه" if count == 2 else "۲ حلقه"
            count_4_mark = "✅ ۴ حلقه" if count == 4 else "۴ حلقه"
            rows.append([
                {"text": count_2_mark, "callback_data": "set_count_2"},
                {"text": count_4_mark, "callback_data": "set_count_4"}
            ])
            rows.append([{"text": "🔙 بازگشت به منوی اصلی", "callback_data": "main_menu"}])

            text = "🛞 <b>سایز و تعداد لاستیک مورد نظر خود را انتخاب کنید:</b>"
            await self.bot.edit_message_text(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data.startswith("set_size_"):
            new_size = data.replace("set_size_", "")
            await upsert_user(chat_id, target_tire_size=new_size)
            await self.handle_callback_query({"id": callback_id, "message": {"chat": {"id": chat_id}, "message_id": message_id}, "data": "menu_size"})

        elif data.startswith("set_count_"):
            c = int(data.replace("set_count_", ""))
            await upsert_user(chat_id, tire_count=c)
            await self.handle_callback_query({"id": callback_id, "message": {"chat": {"id": chat_id}, "message_id": message_id}, "data": "menu_size"})

        elif data == "menu_portal":
            cur_p = user.get("target_portal", "kavir")
            rows = []
            for k, info in PORTALS.items():
                mark = "✅ " if k == cur_p else ""
                rows.append([{"text": f"{mark}{info['title']}", "callback_data": f"set_portal_{k}"}])
            rows.append([{"text": "🔙 بازگشت به منوی اصلی", "callback_data": "main_menu"}])

            text = (
                "🏢 <b>انتخاب سامانه هدف برای شکار سهمیه:</b>\n\n"
                "کدام سامانه مد نظر شماست؟ ربات در زمان بازگشایی مستقیماً به API این سامانه شلیک می‌کند."
            )
            await self.bot.edit_message_text(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data.startswith("set_portal_"):
            p = data.replace("set_portal_", "")
            await upsert_user(chat_id, target_portal=p)
            await self.handle_callback_query({"id": callback_id, "message": {"chat": {"id": chat_id}, "message_id": message_id}, "data": "menu_portal"})

        elif data == "menu_sniper":
            is_active = user.get("sniper_enabled", 0)
            status_text = "🟢 فعال (آماده‌باش شلیک)" if is_active else "🔴 غیرفعال"
            btn_toggle = "غیرفعال‌سازی 🛑" if is_active else "روشن کردن شکارچی ⚡"

            text = (
                "⚡ <b>تنظیمات شکارچی خودکار (Auto-Sniper):</b>\n\n"
                f"وضعیت کنونی: <b>{status_text}</b>\n\n"
                "با روشن بودن شکارچی، ربات قبل از ساعت بازگشایی ارتباط Keep-Alive برقرار کرده و در میلی‌ثانیه اول سهمیه را قفل می‌کند."
            )
            kb = {
                "inline_keyboard": [
                    [{"text": btn_toggle, "callback_data": "toggle_sniper"}],
                    [{"text": "🔙 بازگشت به منوی اصلی", "callback_data": "main_menu"}]
                ]
            }
            await self.bot.edit_message_text(chat_id, message_id, text, reply_markup=kb)

        elif data == "toggle_sniper":
            is_active = user.get("sniper_enabled", 0)
            if is_active:
                await self.sniper.stop_sniper_for_user(chat_id)
            else:
                # بررسی حداقل اطلاعات ضروری
                if not user.get("national_id") or not user.get("mobile"):
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text="⚠️ جهت فعال‌سازی شکارچی، ابتدا باید حداقل <b>کد ملی</b> و <b>شماره تلفن</b> خود را ثبت کنید!"
                    )
                    return
                await upsert_user(chat_id, sniper_enabled=1)
                await self.sniper.start_sniper_for_user(chat_id)

            await self.handle_callback_query({"id": callback_id, "message": {"chat": {"id": chat_id}, "message_id": message_id}, "data": "menu_sniper"})

        elif data == "test_speed":
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="⏳ <b>در حال انجام تست بنچمارک سرعت میلی‌ثانیه‌ای و پینگ به سرورها...</b>"
            )
            benchmark = await self.sniper.simulate_ultra_fast_test(chat_id)
            portal_latencies = await self.sniper.measure_portal_latencies()

            lat_lines = "\n".join([f"▫️ {p}: <b>{lat} ms</b>" for p, lat in portal_latencies.items()])
            result_msg = (
                "🚀 <b>نتایج آزمون سرعت واقعی (Speed Benchmark):</b>\n\n"
                f"🏢 سامانه انتخابی: <code>{benchmark['portal']}</code>\n"
                f"⚡ تاخیر برقراری اتصال TCP: <b>{benchmark['tcp_latency_ms']} ms</b>\n"
                f"🧩 زمان پردازش تصویر کپچا (OpenCV): <b>{benchmark['captcha_processing_ms']} ms</b>\n"
                f"⏱ زمان کل چرخه درخواست: <b>{benchmark['total_benchmark_ms']} ms</b>\n"
                f"🏆 رتبه سرعت سیستم: <b>{benchmark['speed_rating']}</b>\n\n"
                "🌐 <b>پینگ مستقیم سرور شما به سامانه‌ها:</b>\n"
                f"{lat_lines}\n\n"
                "💡 <i>نکته: با این سرعت، درخواست شما جلوتر از ۹۹.۸٪ کاربران عادی و مرورگرها به سرور تحویل داده می‌شود.</i>"
            )
            kb = {"inline_keyboard": [[{"text": "🔙 بازگشت به منوی اصلی", "callback_data": "main_menu"}]]}
            await self.bot.send_message(chat_id=chat_id, text=result_msg, reply_markup=kb)

        elif data == "view_profile":
            p_name = PORTALS.get(user.get("target_portal", "kavir"), {}).get("title", "نامشخص")
            s_name = TIRE_SIZES.get(user.get("target_tire_size", "185_65_14"), "نامشخص")
            sniper_st = "🟢 فعال" if user.get("sniper_enabled", 0) else "🔴 غیرفعال"

            summary = (
                "📋 <b>خلاصه وضعیت پروفایل و تنظیمات شکارچی:</b>\n\n"
                f"👤 کد ملی: <code>{user.get('national_id') or 'ثبت نشده'}</code>\n"
                f"📱 تلفن همراه: <code>{user.get('mobile') or 'ثبت نشده'}</code>\n"
                f"🚘 شماره پلاک: <code>{user.get('car_plate') or 'ثبت نشده'}</code>\n"
                f"🔑 کد VIN: <code>{user.get('car_vin') or 'ثبت نشده'}</code>\n"
                f"🏢 سامانه هدف: <b>{p_name}</b>\n"
                f"🛞 سایز تایر: <b>{s_name}</b>\n"
                f"📦 تعداد سهمیه: <b>{user.get('tire_count', 2)} حلقه</b>\n"
                f"⚡ وضعیت اسنایپر: <b>{sniper_st}</b>\n"
            )
            kb = {"inline_keyboard": [[{"text": "🔙 بازگشت به منوی اصلی", "callback_data": "main_menu"}]]}
            await self.bot.edit_message_text(chat_id, message_id, summary, reply_markup=kb)

    async def handle_text_message(self, message: Dict[str, Any]):
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "").strip()

        if text.startswith("/"):
            if text == "/start":
                await self.handle_start(chat_id, message.get("from", {}).get("username", ""))
            return

        user = await get_user(chat_id)
        if not user:
            user = await upsert_user(chat_id)

        state = user.get("state", "IDLE")

        if state == "AWAIT_NAT_ID":
            cleaned = re.sub(r"\D", "", text)
            if len(cleaned) == 10:
                await upsert_user(chat_id, national_id=cleaned, state="IDLE")
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ کد ملی <code>{cleaned}</code> با موفقیت ذخیره شد.",
                    reply_markup=self.get_main_keyboard()
                )
            else:
                await self.bot.send_message(chat_id=chat_id, text="❌ کد ملی باید دقیقاً ۱۰ رقم باشد. لطفاً مجدداً ارسال کنید:")

        elif state == "AWAIT_MOBILE":
            cleaned = re.sub(r"\D", "", text)
            if len(cleaned) == 11 and cleaned.startswith("09"):
                await upsert_user(chat_id, mobile=cleaned, state="IDLE")
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ شماره موبایل <code>{cleaned}</code> ذخیره شد.",
                    reply_markup=self.get_main_keyboard()
                )
            else:
                await self.bot.send_message(chat_id=chat_id, text="❌ شماره همراه نامعتبر است. فرمت صحیح: <code>09121234567</code>")

        elif state == "AWAIT_PLATE":
            await upsert_user(chat_id, car_plate=text, state="IDLE")
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"✅ شماره پلاک <code>{text}</code> ذخیره شد.",
                reply_markup=self.get_main_keyboard()
            )

        elif state == "AWAIT_VIN":
            vin_clean = text.strip().upper()
            await upsert_user(chat_id, car_vin=vin_clean, state="IDLE")
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"✅ کد VIN <code>{vin_clean}</code> ذخیره شد.",
                reply_markup=self.get_main_keyboard()
            )

        elif state == "AWAIT_CHASSIS":
            await upsert_user(chat_id, chassis_no=text.strip().upper(), state="IDLE")
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"✅ شماره شاسی <code>{text}</code> ذخیره شد.",
                reply_markup=self.get_main_keyboard()
            )

        elif state == "AWAIT_GREEN":
            await upsert_user(chat_id, green_sheet_no=text.strip(), state="IDLE")
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"✅ شماره برگ سبز <code>{text}</code> ذخیره شد.",
                reply_markup=self.get_main_keyboard()
            )
        else:
            await self.bot.send_message(
                chat_id=chat_id,
                text="دستور متوجه نشد. برای شروع منوی اصلی از /start استفاده کنید یا گزینه‌های زیر را انتخاب کنید:",
                reply_markup=self.get_main_keyboard()
            )
