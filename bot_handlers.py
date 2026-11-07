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
    def calculate_profile_completion(user: Dict[str, Any]) -> tuple[int, str]:
        fields = ["national_id", "mobile", "car_plate", "car_vin", "chassis_no", "green_sheet_no"]
        filled = sum(1 for f in fields if user.get(f))
        pct = int((filled / len(fields)) * 100)
        
        # نوار پیشرفت گرافیکی شیک
        total_blocks = 10
        filled_blocks = int((filled / len(fields)) * total_blocks)
        bar = "█" * filled_blocks + "░" * (total_blocks - filled_blocks)
        return pct, f"[{bar}] {pct}%"

    @classmethod
    def get_main_keyboard(cls, user: Optional[Dict[str, Any]] = None):
        user = user or {}
        is_sniper_on = bool(user.get("sniper_enabled", 0))
        sniper_btn_text = "⚡ شکارچی خودکار: 🟢 فعال و آماده" if is_sniper_on else "⚡ شکارچی خودکار: 🔴 خاموش (کلیک برای فعال‌سازی)"

        pct, _ = cls.calculate_profile_completion(user)
        profile_badge = "✅" if pct == 100 else f"({pct}%)"

        cur_portal = PORTALS.get(user.get("target_portal", "barez"), {}).get("title", "بارز").split("(")[0].strip()
        cur_size_code = user.get("target_tire_size", "185_65_14")
        cur_size_title = TIRE_SIZES.get(cur_size_code, "185/65R14").split("(")[0].strip()

        return {
            "inline_keyboard": [
                [
                    {"text": sniper_btn_text, "callback_data": "menu_sniper"}
                ],
                [
                    {"text": "📡 استعلام زنده موجودی انبار", "callback_data": "live_check_stock"},
                    {"text": "🔐 احراز هویت پیامکی در سایت", "callback_data": "auth_real_otp"}
                ],
                [
                    {"text": f"👤 مدارک و خودرو {profile_badge}", "callback_data": "menu_profile"},
                    {"text": f"🛞 سایز: {cur_size_title}", "callback_data": "menu_size"}
                ],
                [
                    {"text": f"🏢 سامانه: {cur_portal}", "callback_data": "menu_portal"},
                    {"text": "⏱ بنچمارک و پینگ", "callback_data": "test_speed"}
                ],
                [
                    {"text": "📊 شناسنامه نهایی من", "callback_data": "view_profile"},
                    {"text": "📖 راهنما و ساعات فروش", "callback_data": "menu_guide"}
                ]
            ]
        }

    async def handle_start(self, chat_id: int, username: str = ""):
        user = await get_user(chat_id)
        if not user:
            user = await upsert_user(chat_id, username=username)

        pct, progress_bar = self.calculate_profile_completion(user)
        sniper_st = "🟢 <b>آماده‌باش و بیدار</b>" if user.get("sniper_enabled", 0) else "⚪ <b>غیرفعال</b>"
        portal_name = PORTALS.get(user.get("target_portal", "barez"), {}).get("title", "بارز")
        size_name = TIRE_SIZES.get(user.get("target_tire_size", "185_65_14"), "185/65R14")

        text = (
            "🏎 <b>سامانه ثبت‌نام فوق‌سریع تایر دولتی</b>\n"
            "<i>موتور ابری اسنایپر | اتصال مستقیم به وب‌سرویس‌های رسمی</i>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📡 <b>وضعیت شکارچی:</b> {sniper_st}\n"
            f"🏢 <b>سامانه هدف:</b> <code>{portal_name}</code>\n"
            f"🛞 <b>سایز و تعداد:</b> <code>{size_name}</code> (<b>{user.get('tire_count', 2)} حلقه</b>)\n"
            f"📋 <b>تکمیل مدارک:</b> <code>{progress_bar}</code>\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>جهت تضمین ثبت‌نام در لحظه بازگشایی ظرفیت‌ها، ابتدا مدارک خود را تکمیل کرده و سپس شکارچی را روشن کنید.</i>\n\n"
            "👇 <b>یک گزینه را انتخاب کنید:</b>"
        )
        await self.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=self.get_main_keyboard(user)
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
            pct, progress_bar = self.calculate_profile_completion(user)
            sniper_st = "🟢 <b>آماده‌باش و بیدار</b>" if user.get("sniper_enabled", 0) else "⚪ <b>غیرفعال</b>"
            portal_name = PORTALS.get(user.get("target_portal", "barez"), {}).get("title", "بارز")
            size_name = TIRE_SIZES.get(user.get("target_tire_size", "185_65_14"), "185/65R14")

            text = (
                "🏎 <b>داشبورد اصلی سامانه تایر دولتی</b>\n"
                "<i>وضعیت لحظه‌ای سیستم و گزینه‌های مدیریت</i>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📡 <b>وضعیت شکارچی:</b> {sniper_st}\n"
                f"🏢 <b>سامانه هدف:</b> <code>{portal_name}</code>\n"
                f"🛞 <b>سایز انتخابی:</b> <code>{size_name}</code>\n"
                f"📋 <b>تکمیل مدارک:</b> <code>{progress_bar}</code>\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "👇 لطفاً بخش مورد نظر خود را انتخاب کنید:"
            )
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=self.get_main_keyboard(user)
            )

        elif data == "menu_profile":
            pct, progress_bar = self.calculate_profile_completion(user)

            n_icon = "✅" if user.get("national_id") else "⚠️"
            m_icon = "✅" if user.get("mobile") else "⚠️"
            p_icon = "✅" if user.get("car_plate") else "⚠️"
            v_icon = "✅" if user.get("car_vin") else "⚠️"
            c_icon = "✅" if user.get("chassis_no") else "⚠️"
            g_icon = "✅" if user.get("green_sheet_no") else "⚠️"

            text = (
                "👤 <b>مدیریت مدارک مالک و اطلاعات خودرو</b>\n"
                "<i>اطلاعات ذخیره‌شده جهت ثبت آنی در کسری از ثانیه</i>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 <b>وضعیت تکمیل:</b> <code>{progress_bar}</code>\n\n"
                f"▫️ <b>کد ملی:</b> <code>{user.get('national_id') or 'وارد نشده'}</code> {n_icon}\n"
                f"▫️ <b>شماره همراه:</b> <code>{user.get('mobile') or 'وارد نشده'}</code> {m_icon}\n"
                f"▫️ <b>شماره پلاک:</b> <code>{user.get('car_plate') or 'وارد نشده'}</code> {p_icon}\n"
                f"▫️ <b>کد VIN خودرو:</b> <code>{user.get('car_vin') or 'وارد نشده'}</code> {v_icon}\n"
                f"▫️ <b>شماره شاسی:</b> <code>{user.get('chassis_no') or 'وارد نشده'}</code> {c_icon}\n"
                f"▫️ <b>سریال برگ سبز:</b> <code>{user.get('green_sheet_no') or 'وارد نشده'}</code> {g_icon}\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "👇 جهت ثبت یا تغییر هر مورد، روی دکمه آن کلیک کنید:"
            )

            kb = {
                "inline_keyboard": [
                    [
                        {"text": f"کد ملی {n_icon}", "callback_data": "edit_national_id"},
                        {"text": f"تلفن همراه {m_icon}", "callback_data": "edit_mobile"}
                    ],
                    [
                        {"text": f"شماره پلاک {p_icon}", "callback_data": "edit_plate"},
                        {"text": f"کد VIN کارت {v_icon}", "callback_data": "edit_vin"}
                    ],
                    [
                        {"text": f"شماره شاسی {c_icon}", "callback_data": "edit_chassis"},
                        {"text": f"شماره برگ سبز {g_icon}", "callback_data": "edit_green"}
                    ],
                    [
                        {"text": "🔙 بازگشت به داشبورد اصلی", "callback_data": "main_menu"}
                    ]
                ]
            }
            await self.bot.edit_message_text(chat_id, message_id, text, reply_markup=kb)

        elif data.startswith("edit_"):
            field = data.replace("edit_", "")
            prompts = {
                "national_id": (
                    "AWAIT_NAT_ID",
                    "👤 <b>ورود کد ملی مالک خودرو</b>\n\n"
                    "لطفاً کد ملی ۱۰ رقمی (بدون خط تیره) را ارسال فرمایید:\n"
                    "<i>مثال: 0012345678</i>"
                ),
                "mobile": (
                    "AWAIT_MOBILE",
                    "📱 <b>ورود شماره تلفن همراه</b>\n\n"
                    "شماره همراه باید حتماً به نام شخص مالک باشد:\n"
                    "<i>مثال: 09123456789</i>"
                ),
                "plate": (
                    "AWAIT_PLATE",
                    "🚘 <b>ورود شماره پلاک خودرو</b>\n\n"
                    "شماره پلاک را مطابق کارت خودرو تایپ فرمایید:\n"
                    "<i>مثال: ۱۲ ب ۳۴۵ ایران ۲۲</i>"
                ),
                "vin": (
                    "AWAIT_VIN",
                    "🔑 <b>ورود کد هفده رقمی VIN</b>\n\n"
                    "کد VIN مندرج روی کارت ماشین (معمولاً با IR شروع می‌شود):\n"
                    "<i>مثال: IRNC1234567890123</i>"
                ),
                "chassis": (
                    "AWAIT_CHASSIS",
                    "⚙️ <b>ورود شماره شاسی خودرو</b>\n\n"
                    "شماره شاسی مندرج در شناسنامه مالکیت (برگ سبز):\n"
                    "<i>مثال: 98765432</i>"
                ),
                "green": (
                    "AWAIT_GREEN",
                    "📄 <b>ورود شماره سریال برگ سبز</b>\n\n"
                    "شماره سریال قرمز رنگ بالای برگ سبز خودرو را ارسال نمایید:"
                )
            }
            if field in prompts:
                st, msg = prompts[field]
                await set_state(chat_id, st)
                kb = {"inline_keyboard": [[{"text": "❌ انصراف و بازگشت", "callback_data": "menu_profile"}]]}
                await self.bot.edit_message_text(chat_id, message_id, msg, reply_markup=kb)

        elif data == "menu_size":
            current_size = user.get("target_tire_size", "185_65_14")
            count = user.get("tire_count", 2)
            
            rows = []
            for k, title in TIRE_SIZES.items():
                is_selected = (k == current_size)
                badge = "🔘 " if is_selected else "⚪ "
                rows.append([{"text": f"{badge}{title}", "callback_data": f"set_size_{k}"}])

            count_2_mark = "🔘 ۲ حلقه (سهمیه نیم‌فصل)" if count == 2 else "⚪ ۲ حلقه"
            count_4_mark = "🔘 ۴ حلقه (سهمیه کامل سالانه)" if count == 4 else "⚪ ۴ حلقه"
            rows.append([
                {"text": count_2_mark, "callback_data": "set_count_2"},
                {"text": count_4_mark, "callback_data": "set_count_4"}
            ])
            rows.append([{"text": "🔙 بازگشت به داشبورد اصلی", "callback_data": "main_menu"}])

            text = (
                "🛞 <b>انتخاب هوشمند سایز و تعداد تایر</b>\n"
                "<i>تایر مدنظر خود را مطابق استاندارد کارخانه خودرو انتخاب کنید</i>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"▫️ <b>سایز فعلی:</b> <code>{TIRE_SIZES.get(current_size, 'نامشخص')}</code>\n"
                f"▫️ <b>تعداد سهمیه:</b> <b>{count} حلقه</b>\n\n"
                "👇 جهت تغییر، روی گزینه مورد نظر کلیک نمایید:"
            )
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
            cur_p = user.get("target_portal", "barez")
            rows = []
            for k, info in PORTALS.items():
                is_sel = (k == cur_p)
                badge = "🔘 " if is_sel else "⚪ "
                hours = "، ".join(info.get("sale_hours", []))
                rows.append([{"text": f"{badge}{info['title']}", "callback_data": f"set_portal_{k}"}])

            rows.append([{"text": "🔙 بازگشت به داشبورد اصلی", "callback_data": "main_menu"}])

            text = (
                "🏢 <b>انتخاب سامانه هدف جهت شکار سهمیه</b>\n"
                "<i>ربات در لحظه آغاز فروش مستقیماً به API این سامانه متصل خواهد شد</i>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "🏭 <b>۱. گروه صنعتی بارز (پیشنهادی):</b>\n"
                "▫️ دارای سامانه خرید آنلاین با تحویل دکاپست و تحویل حضوری.\n"
                "▫️ ساعات معمول بازگشایی: <b>۰۹:۰۰ و ۱۰:۰۰ صبح</b>\n\n"
                "🏭 <b>۲. کویر تایر:</b>\n"
                "▫️ فروش مستقیم اینترنتی درب کارخانه با قیمت مصوب دولتی.\n"
                "▫️ ساعات معمول بازگشایی: <b>۰۹:۰۰ الی ۱۱:۰۰ صبح</b>\n\n"
                "🏛 <b>۳. سامانه جامع تجارت (تخصیص کالا):</b>\n"
                "▫️ سامانه ملی استعلام سهمیه و حواله تایر دولتی.\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "👇 لطفاً کارخانه یا سامانه مورد نظر را انتخاب نمایید:"
            )
            await self.bot.edit_message_text(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data.startswith("set_portal_"):
            p = data.replace("set_portal_", "")
            await upsert_user(chat_id, target_portal=p)
            await self.handle_callback_query({"id": callback_id, "message": {"chat": {"id": chat_id}, "message_id": message_id}, "data": "menu_portal"})

        elif data == "menu_sniper":
            is_active = user.get("sniper_enabled", 0)
            status_badge = "🟢 <b>روشن و آماده‌باش شلیک (Ready)</b>" if is_active else "🔴 <b>خاموش (Idle)</b>"
            btn_toggle = "🛑 غیرفعال‌سازی شکارچی" if is_active else "⚡ روشن کردن شکارچی خودکار"

            portal_name = PORTALS.get(user.get("target_portal", "barez"), {}).get("title", "بارز")
            size_name = TIRE_SIZES.get(user.get("target_tire_size", "185_65_14"), "185/65R14")

            text = (
                "⚡ <b>کاکپیت شکارچی خودکار (Auto-Sniper HUD)</b>\n"
                "<i>فناوری رهگیری ثانیه‌ای و شلیک بدون دخالت دست</i>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📡 <b>وضعیت کنونی:</b> {status_badge}\n"
                f"🎯 <b>هدف قفل‌شده:</b> <code>{portal_name}</code>\n"
                f"🛞 <b>محصول هدف:</b> <code>{size_name}</code>\n"
                f"📦 <b>تعداد رزرو:</b> <b>{user.get('tire_count', 2)} حلقه</b>\n\n"
                "⚙️ <b>عملکرد پشت صحنه اسنایپر:</b>\n"
                "▫️ پیش‌گرم‌سازی کانکشن با سوکت دائمی (TCP Keep-Alive)\n"
                "▫️ رصد لحظه‌ای باز شدن سهمیه‌ها با فرکانس ۲۰۰ میلی‌ثانیه\n"
                "▫️ حل کد امنیتی کپچا با الگوریتم‌های پردازش تصویر محلی\n"
                "▫️ شلیک پکیج ثبت‌نام در میلی‌ثانیه اول بازگشایی\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "👇 جهت تغییر وضعیت کلیک کنید:"
            )
            kb = {
                "inline_keyboard": [
                    [{"text": btn_toggle, "callback_data": "toggle_sniper"}],
                    [{"text": "🔙 بازگشت به داشبورد اصلی", "callback_data": "main_menu"}]
                ]
            }
            await self.bot.edit_message_text(chat_id, message_id, text, reply_markup=kb)

        elif data == "toggle_sniper":
            is_active = user.get("sniper_enabled", 0)
            if is_active:
                await self.sniper.stop_sniper_for_user(chat_id)
            else:
                if not user.get("national_id") or not user.get("mobile"):
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "⚠️ <b>اطلاعات ضروری ناقص است!</b>\n\n"
                            "برای فعال‌سازی شکارچی خودکار، حداقل باید <b>کد ملی</b> و <b>شماره تلفن</b> "
                            "خود را در بخش مدارک ثبت کنید تا در لحظه شلیک با خطای هویت مواجه نشوید."
                        )
                    )
                    return
                await upsert_user(chat_id, sniper_enabled=1)
                await self.sniper.start_sniper_for_user(chat_id)

            await self.handle_callback_query({"id": callback_id, "message": {"chat": {"id": chat_id}, "message_id": message_id}, "data": "menu_sniper"})

        elif data == "live_check_stock":
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="📡 <b>در حال برقراری ارتباط زنده با سرور کارخانه و استعلام موجودی انبار...</b>"
            )
            stock_info = await self.sniper.check_live_stock_now(chat_id)
            p_title = PORTALS.get(stock_info["portal"], {}).get("title", stock_info["portal"])
            s_title = TIRE_SIZES.get(stock_info["tire_size"], stock_info["tire_size"])

            if not stock_info["ok"]:
                msg = (
                    "⚠️ <b>خطای موقت در ارتباط با سامانه کارخانه</b>\n\n"
                    f"🏢 سامانه: <code>{p_title}</code>\n"
                    f"⏱ پینگ اتصال: <b>{stock_info['latency_ms']} میلی‌ثانیه</b>\n\n"
                    "علت: سرور کارخانه پاسخ نداد یا خارج از ساعات مجاز است."
                )
            elif stock_info["is_out_of_stock"]:
                msg = (
                    "🏭 <b>استعلام برخط و زنده موجودی انبار</b>\n"
                    "<i>گزارش مستقیم از دیتابیس کارخانه در همین ثانیه</i>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🏢 <b>کارخانه هدف:</b> <code>{p_title}</code>\n"
                    f"🛞 <b>سایز استعلام‌شده:</b> <code>{s_title}</code>\n"
                    f"⏱ <b>تاخیر پاسخگویی سرور:</b> <b>{stock_info['latency_ms']} میلی‌ثانیه</b>\n"
                    f"📦 <b>وضعیت کنونی:</b> 🔴 <b>{stock_info['status_desc']}</b>\n\n"
                    "💡 <i>ظرفیت‌های دولتی معمولاً رأس ساعت ۰۹:۰۰ یا ۱۰:۰۰ صبح باز می‌شوند. می‌توانید شکارچی را فعال بگذارید تا به محض باز شدن سهمیه، ثانیه‌ای ثبت کند.</i>"
                )
            else:
                items_cnt = len(stock_info.get("items", []))
                msg = (
                    "🎉 <b>فوری: سهمیه باز است و تایر موجود است!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🏢 <b>کارخانه:</b> <code>{p_title}</code>\n"
                    f"🛞 <b>سایز:</b> <code>{s_title}</code>\n"
                    f"📦 <b>تعداد اقلام آماده رزرو:</b> <b>{items_cnt} مدل</b>\n"
                    f"⏱ <b>تاخیر استعلام:</b> <b>{stock_info['latency_ms']} ms</b>\n\n"
                    "⚡ فوراً دکمه شکارچی خودکار را روشن کنید تا ثبت‌نام شما در چند میلی‌ثانیه انجام شود!"
                )
            kb = {
                "inline_keyboard": [
                    [{"text": "🔄 استعلام مجدد", "callback_data": "live_check_stock"}],
                    [{"text": "🔙 بازگشت به داشبورد اصلی", "callback_data": "main_menu"}]
                ]
            }
            await self.bot.send_message(chat_id=chat_id, text=msg, reply_markup=kb)

        elif data == "auth_real_otp":
            if not user.get("mobile"):
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ <b>شماره موبایل یافت نشد!</b>\n\nلطفاً ابتدا از بخش «👤 مدارک و خودرو» شماره همراه خود را وارد کنید."
                )
                return
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"📲 <b>در حال ارسال درخواست پیامک به سرور کارخانه برای شماره {user.get('mobile')}...</b>"
            )
            res = await self.sniper.request_real_otp(chat_id)
            if res.get("ok"):
                await set_state(chat_id, "AWAIT_REAL_OTP")
                msg = (
                    "📩 <b>کد تایید پیامکی از سوی سایت ارسال شد!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"سرور کارخانه کد احراز هویت را به شماره <code>{user.get('mobile')}</code> پیامک کرد.\n\n"
                    "👇 <b>لطفاً کد تایید ۵ رقمی دریافتی را در چت ارسال فرمایید:</b>"
                )
                kb = {"inline_keyboard": [[{"text": "❌ انصراف", "callback_data": "main_menu"}]]}
                await self.bot.send_message(chat_id=chat_id, text=msg, reply_markup=kb)
            else:
                msg = (
                    "❌ <b>خطا در ارسال پیامک احراز هویت:</b>\n\n"
                    f"<code>{res.get('message')}</code>\n\n"
                    "لطفاً مطمئن شوید شماره همراه معتبر است یا لحظاتی دیگر تلاش فرمایید."
                )
                kb = {"inline_keyboard": [[{"text": "🔙 بازگشت به منو", "callback_data": "main_menu"}]]}
                await self.bot.send_message(chat_id=chat_id, text=msg, reply_markup=kb)

        elif data == "test_speed":
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="⏳ <b>در حال اجرای تست بنچمارک سرعت و سنجش تاخیر شبکه...</b>"
            )
            benchmark = await self.sniper.simulate_ultra_fast_test(chat_id)
            portal_latencies = await self.sniper.measure_portal_latencies()

            lat_lines = "\n".join([f"▫️ {p}: <b>{lat} ms</b> ⚡" for p, lat in portal_latencies.items()])
            result_msg = (
                "🚀 <b>نتایج آزمون بنچمارک سرعت واقعی</b>\n"
                "<i>سنجش تاخیر میلی‌ثانیه‌ای سخت‌افزار و شبکه</i>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🏢 <b>سامانه تست‌شده:</b> <code>{benchmark['portal']}</code>\n"
                f"⚡ <b>تاخیر اتصال TCP:</b> <b>{benchmark['tcp_latency_ms']} میلی‌ثانیه</b>\n"
                f"🧩 <b>پردازش تصویر کپچا:</b> <b>{benchmark['captcha_processing_ms']} میلی‌ثانیه</b>\n"
                f"⏱ <b>کل زمان چرخه درخواست:</b> <b>{benchmark['total_benchmark_ms']} میلی‌ثانیه</b>\n"
                f"🏆 <b>رتبه عملکرد سیستم:</b> {benchmark['speed_rating']}\n\n"
                "🌐 <b>پینگ مستقیم به سرورهای توزیع:</b>\n"
                f"{lat_lines}\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "💡 <i>با این سرعت پردازش، بسته ثبت‌نام شما ثانیه‌ها جلوتر از کاربران عادی به سرور تحویل داده می‌شود.</i>"
            )
            kb = {"inline_keyboard": [[{"text": "🔙 بازگشت به داشبورد اصلی", "callback_data": "main_menu"}]]}
            await self.bot.send_message(chat_id=chat_id, text=result_msg, reply_markup=kb)

        elif data == "view_profile":
            p_name = PORTALS.get(user.get("target_portal", "barez"), {}).get("title", "نامشخص")
            s_name = TIRE_SIZES.get(user.get("target_tire_size", "185_65_14"), "نامشخص")
            sniper_st = "🟢 <b>روشن و فعال</b>" if user.get("sniper_enabled", 0) else "🔴 <b>خاموش</b>"
            pct, progress_bar = self.calculate_profile_completion(user)

            summary = (
                "📋 <b>شناسنامه و کارت وضعیت اسنایپر شما</b>\n"
                "<i>خلاصه کلیه پارامترهای آماده برای ثبت‌نام</i>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 <b>کد ملی:</b> <code>{user.get('national_id') or 'ثبت نشده'}</code>\n"
                f"📱 <b>تلفن همراه:</b> <code>{user.get('mobile') or 'ثبت نشده'}</code>\n"
                f"🚘 <b>شماره پلاک:</b> <code>{user.get('car_plate') or 'ثبت نشده'}</code>\n"
                f"🔑 <b>کد هفده‌رقمی VIN:</b> <code>{user.get('car_vin') or 'ثبت نشده'}</code>\n"
                f"⚙️ <b>شماره شاسی:</b> <code>{user.get('chassis_no') or 'ثبت نشده'}</code>\n"
                f"📄 <b>شماره برگ سبز:</b> <code>{user.get('green_sheet_no') or 'ثبت نشده'}</code>\n\n"
                f"🏢 <b>کارخانه هدف:</b> <code>{p_name}</code>\n"
                f"🛞 <b>سایز و مدل تایر:</b> <code>{s_name}</code>\n"
                f"📦 <b>تعداد درخواستی:</b> <b>{user.get('tire_count', 2)} حلقه</b>\n"
                f"⚡ <b>وضعیت شکارچی:</b> {sniper_st}\n"
                f"📊 <b>درصد آمادگی:</b> <code>{progress_bar}</code>\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
            )
            kb = {
                "inline_keyboard": [
                    [{"text": "✏️ ویرایش مدارک", "callback_data": "menu_profile"}],
                    [{"text": "🔙 بازگشت به داشبورد اصلی", "callback_data": "main_menu"}]
                ]
            }
            await self.bot.edit_message_text(chat_id, message_id, summary, reply_markup=kb)

        elif data == "menu_guide":
            guide_text = (
                "📖 <b>راهنمای طلایی ثبت‌نام تایر دولتی</b>\n"
                "<i>نکات کلیدی برای موفقیت ۱۰۰٪ در ثبت سهمیه</i>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "⏰ <b>۱. ساعات طلایی بازگشایی ظرفیت‌ها:</b>\n"
                "▫️ <b>بارز:</b> معمولاً روزهای زوج و فرد رأس ساعت <b>۰۹:۰۰</b> یا <b>۱۰:۰۰ صبح</b>\n"
                "▫️ <b>کویر تایر:</b> روزانه معمولاً بین ساعت <b>۰۹:۳۰</b> تا <b>۱۱:۰۰ صبح</b>\n\n"
                "📜 <b>۲. قوانین سهمیه دولتی:</b>\n"
                "▫️ به هر کد ملی و پلاک خودرو، <b>سالانه حداکثر ۴ حلقه</b> تایر تعلق می‌گیرد.\n"
                "▫️ شماره تلفن همراه باید حتماً به نام مالک خودرو و کد ملی ثبت‌شده باشد.\n"
                "▫️ تاریخ انقضای کارت ماشین نباید منقضی شده باشد.\n\n"
                "⚡ <b>۳. توصیه سرعت برای برنده شدن:</b>\n"
                "▫️ ۵ دقیقه قبل از ساعت بازگشایی، وارد ربات شده و شکارچی را در وضعیت 🟢 فعال بگذارید.\n"
                "▫️ ترجیحاً ربات را روی اینترنت با پینگ پایین فعال نگه دارید.\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
            )
            kb = {"inline_keyboard": [[{"text": "🔙 بازگشت به داشبورد اصلی", "callback_data": "main_menu"}]]}
            await self.bot.edit_message_text(chat_id, message_id, guide_text, reply_markup=kb)

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
                    text=f"✅ <b>کد ملی با موفقیت ثبت شد:</b> <code>{cleaned}</code>",
                    reply_markup=self.get_main_keyboard(await get_user(chat_id))
                )
            else:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="❌ <b>فرمت نامعتبر!</b>\nکد ملی باید دقیقاً ۱۰ رقم باشد. لطفاً مجدداً ارسال فرمایید:"
                )

        elif state == "AWAIT_MOBILE":
            cleaned = re.sub(r"\D", "", text)
            if len(cleaned) == 11 and cleaned.startswith("09"):
                await upsert_user(chat_id, mobile=cleaned, state="IDLE")
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ <b>شماره تلفن ذخیره شد:</b> <code>{cleaned}</code>",
                    reply_markup=self.get_main_keyboard(await get_user(chat_id))
                )
            else:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="❌ <b>شماره همراه نامعتبر!</b>\nفرمت صحیح: <code>09121234567</code>"
                )

        elif state == "AWAIT_PLATE":
            await upsert_user(chat_id, car_plate=text, state="IDLE")
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"✅ <b>شماره پلاک ثبت شد:</b> <code>{text}</code>",
                reply_markup=self.get_main_keyboard(await get_user(chat_id))
            )

        elif state == "AWAIT_VIN":
            vin_clean = text.strip().upper()
            await upsert_user(chat_id, car_vin=vin_clean, state="IDLE")
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"✅ <b>کد VIN کارت خودرو ذخیره شد:</b> <code>{vin_clean}</code>",
                reply_markup=self.get_main_keyboard(await get_user(chat_id))
            )

        elif state == "AWAIT_CHASSIS":
            await upsert_user(chat_id, chassis_no=text.strip().upper(), state="IDLE")
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"✅ <b>شماره شاسی ذخیره شد:</b> <code>{text}</code>",
                reply_markup=self.get_main_keyboard(await get_user(chat_id))
            )

        elif state == "AWAIT_GREEN":
            await upsert_user(chat_id, green_sheet_no=text.strip(), state="IDLE")
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"✅ <b>شماره سریال برگ سبز ثبت شد:</b> <code>{text}</code>",
                reply_markup=self.get_main_keyboard(await get_user(chat_id))
            )

        elif state == "AWAIT_REAL_OTP":
            otp_input = text.strip()
            await self.bot.send_message(
                chat_id=chat_id,
                text="⏳ <b>در حال اعتبارسنجی کد پیامکی در سرور کارخانه...</b>"
            )
            verify_res = await self.sniper.verify_real_otp(chat_id, otp_input)
            if verify_res.get("ok"):
                await set_state(chat_id, "IDLE")
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "🎉 <b>احراز هویت واقعی با موفقیت انجام شد!</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━\n\n"
                        "نشست شما در سایت به صورت رسمی فعال شد. اکنون ربات با هویت تایید شده شما می‌تواند در کسری از ثانیه لاستیک دولتی را برایتان شکار و رزرو کند."
                    ),
                    reply_markup=self.get_main_keyboard(await get_user(chat_id))
                )
            else:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ <b>{verify_res.get('message')}</b>\nلطفاً کد صحیح را مجدداً ارسال فرمایید یا جهت انصراف /start بزنید:"
                )
        else:
            await self.bot.send_message(
                chat_id=chat_id,
                text="دستور متوجه نشد. برای بازگشت به داشبورد از دکمه‌های زیر استفاده کنید:",
                reply_markup=self.get_main_keyboard(user)
            )
