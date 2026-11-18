import asyncio
import html
import re
import logging
from typing import Dict, Any, Optional, List
from database import get_user, upsert_user, set_state, log_action, get_previous_market_snapshot
from bale_api import BaleBotClient
from config import (
    PORTALS,
    CAR_HINT_FOR_SIZE,
    MARKET_TIRE_SIZES,
    TIRE_SIZE_CATEGORIES,
    CAR_TIRE_CATALOG,
    OIL_GRADES,
    OIL_CATEGORIES,
)
from tire_api.oil_price_client import normalize_oil_grade
from tire_api.sniper_engine import SniperEngine
from tire_api.utils import (
    detect_car_from_text,
    escape_html,
    format_short_million,
    format_toman,
    get_tehran_now,
    is_valid_iran_national_id,
    key_to_size,
    normalize_tire_size,
    persian_to_english_digits,
    size_to_key,
)

logger = logging.getLogger("BotHandlers")


class BaleBotHandlers:
    def __init__(self, bot: BaleBotClient, sniper: SniperEngine):
        self.bot = bot
        self.sniper = sniper

    @staticmethod
    def calculate_profile_completion(user: Dict[str, Any]) -> tuple[int, str]:
        fields = ["national_id", "mobile"]
        filled = sum(1 for f in fields if user.get(f))
        pct = int((filled / len(fields)) * 100)
        total_blocks = 10
        filled_blocks = int((filled / len(fields)) * total_blocks)
        bar = "█" * filled_blocks + "░" * (total_blocks - filled_blocks)
        return pct, f"[{bar}] {pct}%"

    @staticmethod
    def _format_size_label(size_key_or_str: str) -> str:
        norm = key_to_size(size_key_or_str)
        hint = CAR_HINT_FOR_SIZE.get(norm)
        return f"{norm} ({hint})" if hint else norm

    @classmethod
    def get_main_keyboard(cls, user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        user = user or {}
        is_sniper_on = bool(user.get("sniper_enabled", 0))
        sniper_btn = (
            "🟢 شکارچی خودکار: فعال و بیدار 🛰"
            if is_sniper_on
            else "⚡ فعال‌سازی شکارچی خودکار تایر دولتی"
        )

        pct, _ = cls.calculate_profile_completion(user)
        prof_badge = "✅" if pct == 100 else f"{pct}%"

        p_key = user.get("target_portal", "all")
        p_short = PORTALS.get(p_key, PORTALS["all"]).get("short", "همه شرکت‌ها")
        cur_size = key_to_size(user.get("target_tire_size", "185_65_14"))

        return {
            "inline_keyboard": [
                [{"text": sniper_btn, "callback_data": "menu_sniper"}],
                [
                    {"text": "📦 موجودی انبار دولتی", "callback_data": "live_check_stock"},
                    {"text": "💰 قیمت روز تایر آزاد", "callback_data": "menu_market_price"},
                ],
                [
                    {"text": "🛢 خرید و قیمت روغن موتور", "callback_data": "menu_oil_price"},
                    {"text": "⚖️ مقایسه دولتی و آزاد", "callback_data": "compare_gov_market"},
                ],
                [
                    {"text": "🚘 انتخاب با نام خودرو", "callback_data": "menu_car_picker"},
                    {"text": f"🛞 سایز ({cur_size})", "callback_data": "menu_size"},
                ],
                [
                    {"text": f"🏭 کارخانه‌ها ({p_short})", "callback_data": "menu_portal"},
                    {"text": f"👤 اطلاعات مالک ({prof_badge})", "callback_data": "menu_profile"},
                ],
                [
                    {"text": "🔐 ورود پیامکی کارخانه", "callback_data": "auth_real_otp"},
                    {"text": "📋 وضعیت و پروفایل من", "callback_data": "view_profile"},
                ],
                [
                    {"text": "📖 راهنمای جامع خرید تایر و روغن", "callback_data": "menu_guide"},
                ],
            ]
        }

    def _build_dashboard_text(self, user: Dict[str, Any], header: str) -> str:
        pct, progress_bar = self.calculate_profile_completion(user)
        sniper_st = "🟢 <b>روشن — در حال رصد لحظه‌ای سایت‌ها</b>" if user.get("sniper_enabled", 0) else "🔴 <b>خاموش (آماده فعال‌سازی)</b>"
        portal_name = PORTALS.get(user.get("target_portal", "all"), PORTALS["all"]).get("title", "همه کارخانه‌ها")
        size_label = self._format_size_label(user.get("target_tire_size", "185_65_14"))
        now_fa = get_tehran_now()["compact_fa"]
        ready_hint = "✅ <i>پروفایل شما تکمیل و آماده شکار است!</i>" if pct == 100 else "🔔 <i>برای فعال‌کردن شکارچی، فقط کد ملی و موبایل را در «اطلاعات مالک» ثبت کنید.</i>"

        return (
            f"✨ <b>{header}</b> ✨\n"
            f"🗓 <i>{now_fa}</i>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🛰 <b>شکارچی دولتی:</b> {sniper_st}\n"
            f"🏭 <b>کارخانه هدف:</b> <code>{escape_html(portal_name)}</code>\n"
            f"🛞 <b>سایز انتخابی:</b> <code>{escape_html(size_label)}</code>\n"
            f"📦 <b>تعداد درخواستی:</b> <b>{user.get('tire_count', 2)} حلقه</b>\n"
            f"👤 <b>اطلاعات مالک:</b> <code>{progress_bar}</code>\n\n"
            f"{ready_hint}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <b>ترفند هوشمند:</b> مستقیم در چت <b>نام خودرو</b> (مثل <code>پژو ۲۰۶</code>)، <b>سایز تایر</b> (<code>185/65R14</code>) یا <b>روغن موتور</b> (<code>10W40</code>) را بفرستید تا قیمت زنده و لینک خرید بگیرید!"
        )

    async def _safe_edit(self, chat_id: int, message_id: Optional[int], text: str, reply_markup: Optional[Dict[str, Any]] = None):
        if not message_id:
            await self.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
            return
        res = await self.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup)
        if not res.get("ok"):
            err = str(res.get("description") or res.get("error") or "").lower()
            if "not modified" not in err:
                logger.warning(f"editMessageText fallback send_message chat={chat_id}: {res}")
                send_res = await self.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
                if not send_res.get("ok"):
                    logger.error(f"sendMessage failed chat={chat_id}: {send_res}")

    @staticmethod
    def _profile_saved_keyboard() -> Dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "👤 برگشت به اطلاعات مالک", "callback_data": "menu_profile"},
                    {"text": "⚡ شکارچی خودکار", "callback_data": "menu_sniper"},
                ],
                [
                    {"text": "🔐 ورود پیامکی کارخانه", "callback_data": "auth_real_otp"},
                    {"text": "🏠 منوی اصلی", "callback_data": "main_menu"},
                ],
            ]
        }

    async def _send_car_recommendation(self, chat_id: int, car_key: str, edit_msg_id: Optional[int] = None):
        car = CAR_TIRE_CATALOG.get(car_key)
        if not car:
            return
        std_sz = car["standard"]
        wide_sz = car["wide"]
        std_key = size_to_key(std_sz)
        wide_key = size_to_key(wide_sz)
        oil_grade = car.get("oil_grade", "10W40")
        gear_oil = car.get("gear_oil", "75W80")
        oil_note = car.get("oil_note", oil_grade)

        text = (
            f"🚘 <b>راهنمای کامل تایر و روغن‌های {escape_html(car['name'])}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⭐ <b>سایز تایر استاندارد (فابریک):</b> <code>{std_sz}</code>\n"
            "   └ <i>بهترین انتخاب برای مصرف سوخت، نرمی فرمان و سهمیه دولتی</i>\n\n"
            f"🔥 <b>سایز تایر جایگزین / پهن‌تر:</b> <code>{wide_sz}</code>\n"
            "   └ <i>تعادل بیشتر در پیچ‌ها و کاربری متناسب با رینگ</i>\n\n"
            f"🛢 <b>روغن موتور و گیربکس پیشنهادی:</b>\n"
            f"   └ <i>{escape_html(oil_note)}</i>\n\n"
            "👇 با یک کلیک قیمت روز بگیرید، آنلاین بخرید یا برای شکارچی ثبت کنید:"
        )
        kb = {
            "inline_keyboard": [
                [
                    {"text": f"💰 قیمت تایر ({std_sz})", "callback_data": f"mkt_{std_key}"},
                    {"text": f"🎯 شکارچی ({std_sz})", "callback_data": f"set_size_{std_key}"},
                ],
                [
                    {"text": f"💰 قیمت تایر ({wide_sz})", "callback_data": f"mkt_{wide_key}"},
                    {"text": f"🎯 شکارچی ({wide_sz})", "callback_data": f"set_size_{wide_key}"},
                ],
                [
                    {"text": f"🛢 روغن موتور ({oil_grade})", "callback_data": f"oil_{oil_grade}"},
                    {"text": f"⚙️ روغن گیربکس ({gear_oil})", "callback_data": f"oil_{gear_oil}"},
                ],
                [
                    {"text": f"⚖️ مقایسه دولتی و آزاد ({std_sz})", "callback_data": f"cmp_{std_key}"},
                ],
                [
                    {"text": "🚘 انتخاب خودروی دیگر", "callback_data": "menu_car_picker"},
                    {"text": "🏠 منوی اصلی", "callback_data": "main_menu"},
                ],
            ]
        }
        if edit_msg_id:
            await self._safe_edit(chat_id, edit_msg_id, text, reply_markup=kb)
        else:
            await self.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)

    async def _send_oil_price_report(
        self, chat_id: int, raw_grade: str, edit_msg_id: Optional[int] = None, force_refresh: bool = False
    ):
        grade = normalize_oil_grade(raw_grade) or raw_grade.upper()
        loading_txt = (
            f"🛢 <b>در حال استعلام زنده قیمت و لینک خرید <code>{escape_html(grade)}</code>...</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🌐 اتصال هم‌زمان به فروشگاه‌های معتبر:\n"
            "▫️ <b>دیجی‌کالا</b> • <b>ترب</b> • <b>باسلام</b>\n\n"
            "⏳ <i>در حال تفکیک دقیق برندهای ایرانی و خارجی و یافتن ارزان‌ترین گزینه‌های اصل...</i>"
        )
        if edit_msg_id:
            await self._safe_edit(chat_id, edit_msg_id, loading_txt)
        else:
            await self.bot.send_message(chat_id=chat_id, text=loading_txt)

        report = await self.sniper.oil_client.fetch_live_oil_prices(grade, force_refresh=force_refresh)
        kb = {
            "inline_keyboard": [
                [
                    {"text": "🔄 بروزرسانی همین لحظه", "callback_data": f"oilrefresh_{grade}"},
                    {"text": "🛢 دسته‌بندی انواع روغن", "callback_data": "menu_oil_price"},
                ],
                [
                    {"text": "🚘 انتخاب با نام خودرو", "callback_data": "menu_car_picker"},
                    {"text": "🏠 منوی اصلی", "callback_data": "main_menu"},
                ],
            ]
        }

        if not report.get("ok") or report.get("total_found", 0) == 0:
            fail_txt = (
                f"⚠️ <b>نتیجه دقیقی برای <code>{escape_html(grade)}</code> پیدا نشد!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "💡 لطفاً از منوی دسته‌بندی انواع روغن انتخاب کنید یا کد صحیح (مثل <code>10W40</code>، <code>75W80</code>، <code>CVT</code>، <code>DOT4</code>) را بفرستید."
            )
            if edit_msg_id:
                await self._safe_edit(chat_id, edit_msg_id, fail_txt, reply_markup=kb)
            else:
                await self.bot.send_message(chat_id=chat_id, text=fail_txt, reply_markup=kb)
            return

        ts = report["timestamp"]
        sc = report["source_counts"]
        s_status = report.get("source_status", {})
        src_parts = []
        for s_name in ("دیجی‌کالا", "ترب", "باسلام"):
            cnt = sc.get(s_name, 0)
            st = s_status.get(s_name, "ok")
            if st == "rate_limited" and cnt == 0:
                src_parts.append(f"{s_name} (محدودیت موقت)")
            elif cnt > 0 or st == "ok":
                src_parts.append(f"{s_name} ({cnt})")
        src_line = " | ".join(src_parts)

        title_fa = report.get("title_fa") or f"روغن موتور {report['grade']}"
        lines: List[str] = [
            f"🛢 <b>قیمت روز و خرید آنلاین • {escape_html(title_fa)}</b>",
            f"📦 <b>حجم/بسته‌بندی:</b> {escape_html(report['target_volume_label'])}",
            f"🕒 <b>ساعت استعلام:</b> {ts['full_fa']}",
            f"📡 <b>منابع بررسی‌شده:</b> {src_line}",
            "━━━━━━━━━━━━━━━━━━━━\n",
        ]

        ir_sum = report.get("ir_summary")
        if ir_sum:
            lines.append("🇮🇷 <b>بازه قیمت روغن موتور ایرانی (اصلی):</b>")
            lines.append(
                f"  ▫️ کف تا سقف بازار: <b>{format_toman(ir_sum['min'])}</b> تا <b>{format_toman(ir_sum['max'])}</b> تومان"
            )
            lines.append(f"  ▫️ قیمت میانه بازار: <b>{format_toman(ir_sum['median'])}</b> تومان\n")

        imp_sum = report.get("imp_summary")
        if imp_sum:
            lines.append("🌍 <b>بازه قیمت روغن موتور خارجی / وارداتی:</b>")
            lines.append(
                f"  ▫️ کف تا سقف بازار: <b>{format_toman(imp_sum['min'])}</b> تا <b>{format_toman(imp_sum['max'])}</b> تومان\n"
            )

        def _fmt_oil(idx: int, o: Dict[str, Any]) -> str:
            br = escape_html(o["brand"])
            api = f" ({o['api_level']})" if o.get("api_level") else ""
            vol_val = o.get("volume")
            vol_txt = f"{int(vol_val) if vol_val and float(vol_val).is_integer() else vol_val} لیتر" if vol_val else "گالن استاندارد"
            pr = format_toman(o["price_toman"])
            shop = escape_html(o["shop_name"][:24])
            src = escape_html(o["source"])
            safe_u = html.escape(str(o.get("url") or ""), quote=True)
            return (
                f"  {idx}. <b>{br}{api}</b> ({vol_txt}) — <b>{pr}</b> تومان\n"
                f"     🛒 {src} | {shop} — <a href=\"{safe_u}\">خرید آنلاین ↗️</a>"
            )

        ir_offers = report.get("ir_offers", [])
        if ir_offers:
            lines.append("🏷 <b>ارزان‌ترین روغن‌های ایرانی آماده خرید:</b>")
            for i, off in enumerate(ir_offers[:5], 1):
                lines.append(_fmt_oil(i, off))
            lines.append("")

        imp_offers = report.get("imp_offers", [])
        if imp_offers:
            lines.append("✈️ <b>گزینه‌های خارجی موجود همین لحظه:</b>")
            for i, off in enumerate(imp_offers[:3], 1):
                lines.append(_fmt_oil(i, off))
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"⚡ <i>سرعت جمع‌آوری زنده: {report['latency_ms']} میلی‌ثانیه • برای خرید مستقیم روی «خرید آنلاین» هر مورد بزنید.</i>")

        msg_text = "\n".join(lines)
        if len(msg_text) > 3950:
            msg_text = msg_text[:3900] + "\n..."

        logger.info(
            f"[OIL_PRICE] chat={chat_id} grade={report['grade']} total={report['total_found']} "
            f"srcs={sc} latency={report['latency_ms']}ms"
        )
        await log_action(
            chat_id,
            "OIL_PRICE",
            "OK",
            f"grade={report['grade']} total={report['total_found']} srcs={sc}",
            report.get("latency_ms", 0.0),
        )
        if edit_msg_id:
            await self._safe_edit(chat_id, edit_msg_id, msg_text, reply_markup=kb)
        else:
            await self.bot.send_message(chat_id=chat_id, text=msg_text, reply_markup=kb)

    async def _send_gov_vs_market_comparison(
        self, chat_id: int, raw_size: str, tire_count: int = 2, edit_msg_id: Optional[int] = None
    ):
        norm = normalize_tire_size(raw_size) or key_to_size(raw_size)
        sk = size_to_key(norm)
        loading = (
            f"⚖️ <b>در حال مقایسه زنده نرخ دولتی و بازار آزاد برای <code>{escape_html(norm)}</code>...</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "⏳ <i>در حال استعلام هم‌زمان از انبار ۱۰ کارخانه دولتی و ۴ بازار آزاد کشور...</i>"
        )
        if edit_msg_id:
            await self._safe_edit(chat_id, edit_msg_id, loading)
        else:
            await self.bot.send_message(chat_id=chat_id, text=loading)

        scan, mkt = await asyncio.gather(
            self.sniper.scan_all_portals_live("all"),
            self.sniper.market_client.fetch_live_market_prices(norm),
        )
        now_fa = get_tehran_now()["compact_fa"]
        ir_sum = mkt.get("ir_summary") if mkt.get("ok") else None
        avail_bucket = scan.get("available_sizes", {}).get(sk)

        lines: List[str] = [
            f"⚖️ <b>مقایسه هوشمند قیمت دولتی و بازار آزاد</b>",
            f"🛞 <b>سایز:</b> <code>{escape_html(self._format_size_label(norm))}</code>  •  🕒 <i>{now_fa}</i>",
            "━━━━━━━━━━━━━━━━━━━━\n",
        ]

        if ir_sum:
            mkt_min = ir_sum["min_unit"]
            mkt_med = ir_sum["median_unit"]
            lines.append("💰 <b>بازار آزاد ایران (ایرانی تاییدشده — همین ساعت):</b>")
            lines.append(f"  ▫️ کف قیمت هر حلقه: <b>{format_toman(mkt_min)}</b> تومان")
            lines.append(f"  ▫️ میانه بازار هر حلقه: <b>{format_toman(mkt_med)}</b> تومان")
            lines.append(f"  ▫️ هزینه یک جفت (۲ حلقه): <b>{format_toman(mkt_min * 2)}</b> تا <b>{format_toman(mkt_med * 2)}</b> تومان\n")
        else:
            mkt_min = 0
            mkt_med = 0
            lines.append("💰 <b>بازار آزاد:</b> <i>در این لحظه پیشنهاد تاییدشده ایرانی یافت نشد.</i>\n")

        if avail_bucket and avail_bucket.get("min_price_toman"):
            gov_p = int(avail_bucket["min_price_toman"])
            portals_txt = "، ".join(avail_bucket.get("portals", []))
            lines.append(f"🏛 <b>انبار دولتی (🟢 هم‌اکنون موجود در {escape_html(portals_txt)}):</b>")
            lines.append(f"  ▫️ شروع قیمت دولتی: <b>{format_toman(gov_p)}</b> تومان\n")
            if mkt_med and gov_p < mkt_med:
                save_1 = mkt_med - gov_p
                lines.append("💎 <b>سود خالص شما با خرید دولتی همین الان:</b>")
                lines.append(f"  ▫️ هر حلقه: <b>{format_toman(save_1)}</b> تومان صرفه‌جویی!")
                lines.append(f"  ▫️ برای ۲ حلقه: <b>{format_toman(save_1 * 2)}</b> تومان صرفه‌جویی!")
                lines.append(f"  ▫️ برای ۴ حلقه: <b>{format_toman(save_1 * 4)}</b> تومان صرفه‌جویی! 🎉")
        else:
            lines.append("🏛 <b>انبار دولتی:</b> 🔴 <i>این سایز در این دقیقه ناموجود است.</i>")
            if mkt_med:
                est_gov = int(mkt_med * 0.62)
                est_save_pair = max(0, (mkt_med - est_gov) * 2)
                lines.append(
                    f"💡 <i>برآورد تقریبی: معمولاً خرید دولتی این سایز حدود <b>{format_toman(est_save_pair)}</b> تا <b>{format_toman(est_save_pair * 2)}</b> تومان (برای ۲ تا ۴ حلقه) ارزان‌تر از بازار آزاد تمام می‌شود!</i>"
                )
            lines.append("⚡ <i>با روشن کردن «شکارچی خودکار»، به محض شارژ دولتی اولین نفر خبردار می‌شوید.</i>")

        kb = {
            "inline_keyboard": [
                [
                    {"text": "📦 جزئیات خرید دولتی", "callback_data": "live_check_stock"},
                    {"text": "💰 لیست کامل بازار آزاد", "callback_data": f"mkt_{sk}"},
                ],
                [
                    {"text": "⚡ روشن‌کردن شکارچی", "callback_data": "menu_sniper"},
                    {"text": "🚘 انتخاب خودروی دیگر", "callback_data": "menu_car_picker"},
                ],
                [{"text": "🏠 بازگشت به منوی اصلی", "callback_data": "main_menu"}],
            ]
        }
        await log_action(chat_id, "COMPARE_GOV_MKT", "OK", f"size={norm} gov_avail={bool(avail_bucket)}", 0.0)
        if edit_msg_id:
            await self._safe_edit(chat_id, edit_msg_id, "\n".join(lines), reply_markup=kb)
        else:
            await self.bot.send_message(chat_id=chat_id, text="\n".join(lines), reply_markup=kb)

    async def handle_start(self, chat_id: int, username: str = ""):
        user = await get_user(chat_id)
        if not user:
            user = await upsert_user(chat_id, username=username)
        await set_state(chat_id, "IDLE")

        text = self._build_dashboard_text(user, "دستیار هوشمند تایر دولتی و قیمت روز")
        await self.bot.send_message(chat_id=chat_id, text=text, reply_markup=self.get_main_keyboard(user))

    async def _send_market_price_report(
        self, chat_id: int, raw_size: str, edit_msg_id: Optional[int] = None, force_refresh: bool = False
    ):
        norm = normalize_tire_size(raw_size) or raw_size
        loading_txt = (
            f"🔎 <b>در حال استعلام زنده قیمت روز تایر <code>{escape_html(norm)}</code>...</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🌐 اتصال هم‌زمان به ۴ مرجع بزرگ کشور:\n"
            "▫️ <b>دیجی‌کالا</b> • <b>ترب</b> • <b>باسلام</b> • <b>هایپرتایر</b>\n\n"
            "⏳ <i>در حال تفکیک دقیق تک‌حلقه و جفت، و حذف آگهی‌های متفرقه...</i>"
        )
        if edit_msg_id:
            await self._safe_edit(chat_id, edit_msg_id, loading_txt)
        else:
            await self.bot.send_message(chat_id=chat_id, text=loading_txt)

        report = await self.sniper.market_client.fetch_live_market_prices(norm, force_refresh=force_refresh)
        size_key = size_to_key(norm)
        kb = {
            "inline_keyboard": [
                [
                    {"text": "🔄 بروزرسانی همین لحظه", "callback_data": f"mktrefresh_{size_key}"},
                    {"text": "⚖️ مقایسه با دولتی", "callback_data": f"cmp_{size_key}"},
                ],
                [
                    {"text": "🎯 ثبت برای شکارچی", "callback_data": f"set_size_{size_key}"},
                    {"text": "🔍 استعلام سایز دیگر", "callback_data": "menu_market_price"},
                ],
                [{"text": "🏠 بازگشت به منوی اصلی", "callback_data": "main_menu"}],
            ]
        }

        if not report.get("ok") or report.get("total_found", 0) == 0:
            logger.warning(f"[MARKET_PRICE] chat={chat_id} size={norm} EMPTY/FAIL srcs={report.get('source_counts')} status={report.get('source_status')}")
            await log_action(chat_id, "MARKET_PRICE", "EMPTY", f"size={norm} srcs={report.get('source_counts')}", report.get("latency_ms", 0.0))
            fail_kb = {
                "inline_keyboard": [
                    [
                        {"text": "🔄 تلاش مجدد", "callback_data": f"mktrefresh_{size_key}"},
                        {"text": "🔍 انتخاب سایز دیگر", "callback_data": "menu_market_price"},
                    ],
                    [{"text": "🏠 بازگشت به منوی اصلی", "callback_data": "main_menu"}],
                ]
            }
            fail_txt = (
                f"⚠️ <b>نتیجه دقیقی برای سایز <code>{escape_html(norm)}</code> پیدا نشد!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "💡 لطفاً بررسی کنید سایز را درست وارد کرده باشید (مثل <code>185/65R14</code> یا <code>205/60R15</code>) و یک‌بار دیگر امتحان کنید."
            )
            if edit_msg_id:
                await self._safe_edit(chat_id, edit_msg_id, fail_txt, reply_markup=fail_kb)
            else:
                await self.bot.send_message(chat_id=chat_id, text=fail_txt, reply_markup=fail_kb)
            return

        ts = report["timestamp"]
        sc = report["source_counts"]
        s_status = report.get("source_status", {})
        src_parts = []
        for s_name in ("دیجی‌کالا", "باسلام", "هایپرتایر", "ترب"):
            cnt = sc.get(s_name, 0)
            st = s_status.get(s_name, "ok")
            if st == "rate_limited" and cnt == 0:
                src_parts.append(f"{s_name} (محدودیت موقت)")
            elif cnt > 0 or st == "ok":
                src_parts.append(f"{s_name} ({cnt})")
        src_summary_line = " | ".join(src_parts)

        car_hint = CAR_HINT_FOR_SIZE.get(report["size"])
        car_line = f"🚘 <b>مناسب خودروهای:</b> {escape_html(car_hint)}\n" if car_hint else ""

        lines: List[str] = [
            f"💰 <b>قیمت زنده بازار آزاد • سایز <code>{escape_html(report['size'])}</code></b>",
            f"🕒 <b>ساعت استعلام:</b> {ts['full_fa']}",
            f"📡 <b>فروشگاه‌های بررسی‌شده:</b> {src_summary_line}",
            car_line + "━━━━━━━━━━━━━━━━━━━━\n",
        ]

        ir_sum = report.get("ir_summary")
        if ir_sum:
            trend_line = ""
            prev_snap = await get_previous_market_snapshot(report["size"])
            if prev_snap and prev_snap.get("ir_median_unit"):
                diff = ir_sum["median_unit"] - int(prev_snap["ir_median_unit"])
                if diff <= -50_000:
                    trend_line = f"  📉 <i>روند بازار: <b>{format_toman(abs(diff))}</b> تومان ارزان‌تر نسبت به استعلام قبلی</i>\n"
                elif diff >= 50_000:
                    trend_line = f"  📈 <i>روند بازار: <b>{format_toman(diff)}</b> تومان گران‌تر نسبت به استعلام قبلی</i>\n"
                else:
                    trend_line = "  ➖ <i>روند بازار: قیمت ثابت نسبت به استعلام قبلی</i>\n"

            lines.append("🇮🇷 <b>بازه قیمت لاستیک ایرانی (تاییدشده):</b>")
            lines.append(
                f"  ▫️ هر حلقه: <b>{format_toman(ir_sum['min_unit'])}</b> تا <b>{format_toman(ir_sum['max_unit'])}</b> تومان\n"
                f"  ▫️ قیمت میانه بازار: <b>{format_toman(ir_sum['median_unit'])}</b> تومان"
            )
            lines.append(
                f"  ▫️ هر جفت (۲ حلقه): <b>{format_toman(ir_sum['min_pair'])}</b> تا <b>{format_toman(ir_sum['max_pair'])}</b> تومان\n"
                + trend_line
            )

        imp_sum = report.get("imp_summary")
        if imp_sum:
            lines.append("🌍 <b>بازه قیمت لاستیک خارجی / وارداتی:</b>")
            lines.append(
                f"  ▫️ هر حلقه: <b>{format_toman(imp_sum['min_unit'])}</b> تا <b>{format_toman(imp_sum['max_unit'])}</b> تومان"
            )
            lines.append(
                f"  ▫️ هر جفت (۲ حلقه): <b>{format_toman(imp_sum['min_pair'])}</b> تا <b>{format_toman(imp_sum['max_pair'])}</b> تومان\n"
            )

        def _fmt_offer(idx: int, o: Dict[str, Any]) -> str:
            brand = escape_html(o["brand"])
            yr = f" ({o['year']})" if o.get("year") else ""
            shop = escape_html(o["shop_name"][:24])
            src = escape_html(o["source"])
            pk = o.get("pack_count")
            unit_p = format_toman(o["unit_price_toman"])
            raw_p = format_toman(o["price_toman"])
            pack_note = f"حلقه‌ای <b>{unit_p}</b> ت (فروش جفتی: {raw_p})" if pk == 2 else (
                f"حلقه‌ای <b>{unit_p}</b> ت (بسته ۴تایی: {raw_p})" if pk == 4 else f"<b>{unit_p}</b> تومان (تک‌حلقه)"
            )
            safe_url = html.escape(str(o.get("url") or ""), quote=True)
            return f"  {idx}. <b>{brand}{yr}</b> — {pack_note}\n     🏬 {src} | {shop} — <a href=\"{safe_url}\">مشاهده آگهی ↗️</a>"

        ir_offers = report.get("ir_offers", [])
        if ir_offers:
            lines.append("🏷 <b>ارزان‌ترین گزینه‌های ایرانی همین الان:</b>")
            for i, off in enumerate(ir_offers[:5], 1):
                lines.append(_fmt_offer(i, off))
            lines.append("")

        imp_offers = report.get("imp_offers", [])
        if imp_offers:
            lines.append("✈️ <b>گزینه‌های خارجی موجود همین لحظه:</b>")
            for i, off in enumerate(imp_offers[:3], 1):
                lines.append(_fmt_offer(i, off))
            lines.append("")

        unspec = report.get("unspecified_offers", [])
        if unspec and (not ir_offers or unspec[0]["price_toman"] <= ir_offers[0]["unit_price_toman"] * 1.15):
            lines.append("⚠️ <i>فروشگاه‌هایی که تعداد حلقه را در عنوان ننوشته‌اند (حتماً در لینک بررسی کنید):</i>")
            for off in unspec[:2]:
                safe_u = html.escape(str(off.get("url") or ""), quote=True)
                lines.append(
                    f"  ▫️ <b>{escape_html(off['brand'])}</b> — درج‌شده: <b>{format_toman(off['price_toman'])}</b> ت | "
                    f"{escape_html(off['shop_name'][:20])} (<a href=\"{safe_u}\">لینک ↗️</a>)"
                )

        lines.append("\n━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"⚡ <i>زمان جمع‌آوری زنده: {report['latency_ms']} میلی‌ثانیه • قیمت‌ها بر اساس نرخ همین ساعت است.</i>")

        msg_text = "\n".join(lines)
        if len(msg_text) > 3950:
            msg_text = msg_text[:3900] + "\n..."

        logger.info(
            f"[MARKET_PRICE] chat={chat_id} size={report['size']} total={report['total_found']} "
            f"srcs={sc} latency={report['latency_ms']}ms cached={report.get('cached', False)}"
        )
        await log_action(
            chat_id,
            "MARKET_PRICE",
            "OK",
            f"size={report['size']} total={report['total_found']} srcs={sc}",
            report.get("latency_ms", 0.0),
        )

        if edit_msg_id:
            await self._safe_edit(chat_id, edit_msg_id, msg_text, reply_markup=kb)
        else:
            await self.bot.send_message(chat_id=chat_id, text=msg_text, reply_markup=kb)

    async def handle_callback_query(self, query: Dict[str, Any]):
        callback_id = query.get("id")
        chat_id = query.get("message", {}).get("chat", {}).get("id")
        message_id = query.get("message", {}).get("message_id")
        data = query.get("data", "")

        if callback_id:
            await self.bot.answer_callback_query(callback_id)

        await self._route_callback(chat_id, message_id, data)

    async def _route_callback(self, chat_id: int, message_id: Optional[int], data: str):
        user = await get_user(chat_id)
        if not user:
            user = await upsert_user(chat_id)

        # با زدن هر دکمه منو یا بازگشت، وضعیت انتظار تایپ قبلی به‌صورت خودکار پاک می‌شود
        if user.get("state", "IDLE") != "IDLE" and not (
            data.startswith("edit_")
            or data in ("ask_custom_market_size", "ask_custom_oil_grade")
            or data.startswith("otp_send_")
        ):
            await set_state(chat_id, "IDLE")
            user["state"] = "IDLE"

        if data == "main_menu":
            await set_state(chat_id, "IDLE")
            text = self._build_dashboard_text(user, "دستیار هوشمند تایر دولتی و قیمت روز")
            if message_id:
                await self._safe_edit(chat_id, message_id, text, reply_markup=self.get_main_keyboard(user))
            else:
                await self.bot.send_message(chat_id=chat_id, text=text, reply_markup=self.get_main_keyboard(user))

        elif data == "menu_profile":
            pct, progress_bar = self.calculate_profile_completion(user)
            n_icon = "✅" if user.get("national_id") else "⚠️"
            m_icon = "✅" if user.get("mobile") else "⚠️"

            text = (
                "👤 <b>اطلاعات مالک خودرو</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 <b>پیشرفت تکمیل:</b> <code>{progress_bar}</code>\n\n"
                f"🆔 <b>کد ملی مالک:</b> <code>{user.get('national_id') or 'ثبت نشده'}</code> {n_icon}\n"
                f"📱 <b>موبایل به نام مالک:</b> <code>{user.get('mobile') or 'ثبت نشده'}</code> {m_icon}\n\n"
                "🛡 <b>چرا فقط همین ۲ مورد را می‌خواهیم؟</b>\n"
                "▫️ برای ورود پیامکی و روشن‌کردن شکارچی خودکار، فقط همین ۲ مورد لازم است.\n"
                "▫️ بقیه مشخصات (مثل پلاک، کارت ماشین و آدرس) صرفاً موقع خرید نهایی در <b>خود سایت رسمی کارخانه</b> وارد می‌شود.\n\n"
                "👇 برای ثبت یا تغییر هر مورد روی دکمه‌اش بزنید:"
            )
            rows = [
                [
                    {"text": f"🆔 کد ملی مالک {n_icon}", "callback_data": "edit_national_id"},
                    {"text": f"📱 موبایل مالک {m_icon}", "callback_data": "edit_mobile"},
                ],
            ]
            if pct == 100:
                rows.append([
                    {"text": "⚡ شکارچی خودکار", "callback_data": "menu_sniper"},
                    {"text": "🔐 ورود پیامکی کارخانه", "callback_data": "auth_real_otp"},
                ])
            rows.append([{"text": "🏠 بازگشت به منوی اصلی", "callback_data": "main_menu"}])
            await self._safe_edit(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data.startswith("edit_"):
            field = data.replace("edit_", "")
            prompts = {
                "national_id": (
                    "AWAIT_NAT_ID",
                    "🆔 <b>ثبت کد ملی مالک خودرو</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    "لطفاً کد ملی <b>۱۰ رقمی</b> مالک خودرو را بدون خط تیره بفرستید:\n"
                    "📌 <i>مثال:</i> <code>0012345678</code>\n\n"
                    "💡 <i>نکته: سهمیه تایر دولتی فقط به کد ملی صاحب سند خودرو تعلق می‌گیرد.</i>",
                ),
                "mobile": (
                    "AWAIT_MOBILE",
                    "📱 <b>ثبت شماره موبایل مالک خودرو</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    "لطفاً شماره همراه <b>۱۱ رقمی</b> (حتماً به نام خود مالک) را بفرستید:\n"
                    "📌 <i>مثال:</i> <code>09123456789</code>\n\n"
                    "💡 <i>نکته: کد پیامکی ورود سایت‌های دولتی به همین شماره ارسال می‌شود.</i>",
                ),
            }
            if field in prompts:
                st, msg = prompts[field]
                await set_state(chat_id, st)
                kb = {"inline_keyboard": [[{"text": "🔙 انصراف و بازگشت", "callback_data": "menu_profile"}]]}
                await self._safe_edit(chat_id, message_id, msg, reply_markup=kb)

        elif data == "menu_portal":
            cur_p = user.get("target_portal", "all")
            rows: List[List[Dict[str, str]]] = [
                [{
                    "text": ("🟢 " if cur_p == "all" else "⚪ ") + "🌐 همه کارخانه‌ها با هم (هوشمند و پیشنهادی ⭐)",
                    "callback_data": "set_portal_all",
                }]
            ]
            # چیدمان متقارن ۲ ستونی برای تک‌تک شرکت‌های تایر دولتی
            factory_keys = ["hypertire", "barez", "kavir", "irantire", "yazd", "razi", "kian", "artawheel", "dena", "ntsw"]
            for i in range(0, len(factory_keys), 2):
                pair_btns = []
                for pk in factory_keys[i : i + 2]:
                    mark = "🟢 " if pk == cur_p else "⚪ "
                    pair_btns.append({"text": f"{mark}{PORTALS[pk]['short']}", "callback_data": f"set_portal_{pk}"})
                rows.append(pair_btns)

            rows.append([{"text": "📡 بررسی آنلاین وضعیت همه سایت‌ها", "callback_data": "live_portals_health"}])
            rows.append([{"text": "🏠 بازگشت به منوی اصلی", "callback_data": "main_menu"}])

            cur_info = PORTALS.get(cur_p, PORTALS["all"])
            hours_txt = " ، ".join(cur_info.get("sale_hours", []))
            text = (
                "🏭 <b>انتخاب کارخانه و سامانه فروش تایر دولتی</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🎯 <b>انتخاب فعلی شما:</b> <code>{escape_html(cur_info['title'])}</code>\n"
                f"⏰ <b>ساعات معمول شارژ:</b> <i>{escape_html(hours_txt)}</i>\n"
                f"ℹ️ <b>توضیحات:</b> <i>{escape_html(cur_info['desc'])}</i>\n\n"
                "⭐ <b>پیشنهاد طلایی:</b> گزینه <b>«همه کارخانه‌ها با هم»</b> را انتخاب کنید تا ربات هم‌زمان تمام ۱۰ سایت دولتی (بارز، هایپرتایر، کویر، ایران‌تایر، یزد، رازی، کیان، آرتاویل، دنا و سامانه تجارت) را زیر نظر بگیرد و شانس خریدتان چند برابر شود!\n\n"
                "👇 کارخانه یا سامانه مورد نظرتان را انتخاب کنید:"
            )
            await self._safe_edit(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data.startswith("set_portal_"):
            p = data.replace("set_portal_", "")
            if p in PORTALS:
                await upsert_user(chat_id, target_portal=p)
            await self._route_callback(chat_id, message_id, "menu_portal")

        elif data == "live_portals_health":
            await self._safe_edit(
                chat_id,
                message_id,
                "📡 <b>در حال بررسی آنلاین و زنده تمام ۱۰ کارخانه و سامانه دولتی...</b>\n\n⏳ <i>لطفاً چند ثانیه صبر کنید تا پاسخ همه سایت‌ها دریافت شود.</i>",
            )
            scan = await self.sniper.scan_all_portals_live("all")
            now_fa = get_tehran_now()["compact_fa"]
            lines = [
                f"🌐 <b>گزارش زنده وضعیت سایت‌های تایر دولتی</b>",
                f"🕒 <i>{now_fa}</i>",
                "━━━━━━━━━━━━━━━━━━━━\n",
            ]
            for st in scan["portals_status"]:
                cnt = len(st.get("in_stock_items", []))
                if cnt > 0:
                    icon = "🟢"
                elif st.get("anti_bot"):
                    icon = "🛡"
                elif st.get("vpn_blocked"):
                    icon = "📵"
                elif st.get("ok"):
                    icon = "🟡"
                else:
                    icon = "🔴"
                lines.append(
                    f"{icon} <b>{escape_html(st['title'])}</b> <i>({st['latency_ms']} ms)</i>\n"
                    f"   └ {escape_html(st['status_desc'])}"
                )
            lines.append("\n━━━━━━━━━━━━━━━━━━━━")
            lines.append("📌 <b>راهنمای رنگ‌ها:</b>\n🟢 موجود و آماده خرید | 🟡 آنلاین (فعلاً ناموجود) | 🛡 محافظ ضدربات | 📵 نیاز به آی‌پی ایران | 🔴 آفلاین")
            kb = {
                "inline_keyboard": [
                    [
                        {"text": "🔄 اسکن مجدد زنده", "callback_data": "live_portals_health"},
                        {"text": "🔙 لیست کارخانه‌ها", "callback_data": "menu_portal"},
                    ],
                    [{"text": "🏠 بازگشت به منوی اصلی", "callback_data": "main_menu"}],
                ]
            }
            ok_portals = [st["portal"] for st in scan["portals_status"] if st.get("ok")]
            in_stock_cnt = len(scan.get("all_in_stock_items", []))
            logger.info(f"[PORTALS_HEALTH] chat={chat_id} ok={len(ok_portals)}/10 in_stock={in_stock_cnt}")
            await log_action(chat_id, "PORTALS_HEALTH", "OK", f"online={len(ok_portals)}/10 in_stock={in_stock_cnt}", 0.0)
            await self._safe_edit(chat_id, message_id, "\n".join(lines), reply_markup=kb)

        elif data == "menu_oil_price":
            rows: List[List[Dict[str, str]]] = []
            cat_items = list(OIL_CATEGORIES.items())
            for i in range(0, len(cat_items), 2):
                pair = []
                for ck, info in cat_items[i : i + 2]:
                    pair.append({"text": info["short"], "callback_data": f"oilcat_{ck}"})
                rows.append(pair)
            rows.append([
                {"text": "🚘 انتخاب با نام خودرو", "callback_data": "menu_car_picker"},
                {"text": "✍️ تایپ کد یا گرانروی", "callback_data": "ask_custom_oil_grade"},
            ])
            rows.append([{"text": "🏠 بازگشت به منوی اصلی", "callback_data": "main_menu"}])

            now_fa = get_tehran_now()["full_fa"]
            text = (
                "🛢 <b>خرید آنلاین و قیمت روز تمامی انواع روغن خودرو</b>\n"
                f"🕒 <i>{now_fa}</i>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "🌐 اتصال زنده به <b>دیجی‌کالا، ترب و باسلام</b> برای بیش از <b>۲۹ نوع و گرانروی مختلف</b>:\n"
                "▫️ <b>روغن موتور بنزینی</b> (0W20 تا 20W50)\n"
                "▫️ <b>روغن موتور دیزلی</b> (کامیون، کشنده، خاور ۲۰ لیتری)\n"
                "▫️ <b>واسکازین و گیربکس دنده‌ای</b> (75W80 تا 85W140)\n"
                "▫️ <b>گیربکس اتوماتیک</b> (ATF، CVT و DCT دوکلاچه)\n"
                "▫️ <b>هیدرولیک فرمان، ترمز DOT3/DOT4 و ضدیخ</b>\n"
                "▫️ <b>روغن موتورسیکلت و اسکوتر</b>\n\n"
                "👇 دسته‌بندی مورد نظرتان را انتخاب کنید:"
            )
            await self._safe_edit(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data.startswith("oilcat_"):
            ck = data.replace("oilcat_", "")
            cat = OIL_CATEGORIES.get(ck)
            if not cat:
                await self._route_callback(chat_id, message_id, "menu_oil_price")
                return
            rows = []
            items = cat["items"]
            # اگر عنوان کوتاه است ۲ ستونی، وگرنه تک‌ستونی خوانا
            if len(items) >= 6:
                for i in range(0, len(items), 2):
                    pair = []
                    for code, hint in items[i : i + 2]:
                        short_h = hint.split("/")[0].strip()
                        pair.append({"text": f"🛢 {code} • {short_h}", "callback_data": f"oil_{code}"})
                    rows.append(pair)
            else:
                for code, hint in items:
                    rows.append([{"text": f"🛢 {code}  •  {hint}", "callback_data": f"oil_{code}"}])
            rows.append([
                {"text": "🔙 بازگشت به دسته‌های روغن", "callback_data": "menu_oil_price"},
                {"text": "🏠 منوی اصلی", "callback_data": "main_menu"},
            ])
            text = (
                f"<b>{escape_html(cat['title'])}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"ℹ️ <i>{escape_html(cat['desc'])}</i>\n\n"
                "👇 مدل یا گرانروی دقیق را انتخاب کنید تا ارزان‌ترین قیمت روز و لینک خرید مستقیم را بگیرید:"
            )
            await self._safe_edit(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data == "ask_custom_oil_grade":
            await set_state(chat_id, "AWAIT_OIL_GRADE")
            kb = {"inline_keyboard": [[{"text": "🔙 انصراف و بازگشت", "callback_data": "menu_oil_price"}]]}
            await self._safe_edit(
                chat_id,
                message_id,
                (
                    "✍️ <b>تایپ نوع روغن، گرانروی یا نام خودرو</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    "هر نوع روغنی که می‌خواهید تایپ کنید:\n"
                    "📌 <i>مثال‌ها:</i> <code>10W40</code> • <code>5W30</code> • <code>75W80</code> • <code>CVT</code> • <code>DCT</code> • <code>DOT4</code> • <code>هیدرولیک</code> • <code>ضدیخ</code> • <code>پژو ۲۰۶</code>"
                ),
                reply_markup=kb,
            )

        elif data.startswith("oilrefresh_"):
            gr = data.replace("oilrefresh_", "")
            await self._send_oil_price_report(chat_id, gr, edit_msg_id=message_id, force_refresh=True)

        elif data.startswith("oil_"):
            gr = data.replace("oil_", "")
            await self._send_oil_price_report(chat_id, gr, edit_msg_id=message_id)

        elif data == "menu_car_picker":
            rows: List[List[Dict[str, str]]] = []
            car_items = list(CAR_TIRE_CATALOG.items())
            for i in range(0, len(car_items), 2):
                pair = []
                for ck, info in car_items[i : i + 2]:
                    pair.append({"text": f"🚘 {info['short']}", "callback_data": f"car_{ck}"})
                rows.append(pair)
            rows.append([{"text": "✍️ تایپ سایز دلخواه", "callback_data": "ask_custom_market_size"}])
            rows.append([{"text": "🏠 بازگشت به منوی اصلی", "callback_data": "main_menu"}])
            text = (
                "🚘 <b>انتخاب هوشمند سایز تایر بر اساس نام خودرو</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "نیازی نیست سایز تایر خودروی خود را حفظ باشید!\n"
                "فقط روی مدل ماشینتان بزنید (یا اسمش را توی چت بنویسید) تا هم <b>سایز فابریک</b> و هم <b>سایز پهن مناسب</b> همراه با قیمت روز و شکارچی دولتی برایتان باز شود.\n\n"
                "👇 خودروی خود را انتخاب کنید:"
            )
            await self._safe_edit(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data.startswith("car_"):
            car_key = data.replace("car_", "")
            await self._send_car_recommendation(chat_id, car_key, edit_msg_id=message_id)

        elif data == "compare_gov_market":
            cur_sz = user.get("target_tire_size", "185_65_14")
            await self._send_gov_vs_market_comparison(
                chat_id, cur_sz, tire_count=user.get("tire_count", 2), edit_msg_id=message_id
            )

        elif data.startswith("cmp_"):
            sk = data.replace("cmp_", "")
            await self._send_gov_vs_market_comparison(
                chat_id, sk, tire_count=user.get("tire_count", 2), edit_msg_id=message_id
            )

        elif data in ("menu_size", "menu_size_catalog"):
            show_catalog = (data == "menu_size_catalog")
            cur_portal = user.get("target_portal", "all")
            current_size = user.get("target_tire_size", "185_65_14")
            count = user.get("tire_count", 2)

            await self._safe_edit(
                chat_id,
                message_id,
                "🛞 <b>در حال دریافت لیست زنده سایزها از انبار سایت‌های دولتی...</b>\n\n⏳ <i>فقط سایزهای واقعی موجود و کاتالوگ سایت‌ها بارگذاری می‌شوند.</i>",
            )
            scan = await self.sniper.scan_all_portals_live(cur_portal)
            avail = scan["available_sizes"]
            cat_sizes = scan["catalog_sizes"]

            rows: List[List[Dict[str, str]]] = []
            lines: List[str] = [
                "🛞 <b>انتخاب سایز تایر دولتی (فقط بر اساس موجودی سایت‌ها)</b>",
                f"🕒 <i>بروزرسانی زنده انبار: {get_tehran_now()['compact_fa']}</i>",
                "━━━━━━━━━━━━━━━━━━━━\n",
            ]

            if avail:
                lines.append("🟢 <b>سایزهای واقعاً موجود و آماده خرید در همین لحظه:</b>")
                sorted_avail = sorted(avail.values(), key=lambda x: x["size"])
                for item in sorted_avail:
                    sk = item["size_key"]
                    sz = item["size"]
                    pr = format_short_million(item["min_price_toman"]) if item["min_price_toman"] else "-"
                    p_str = "، ".join(item["portals"])
                    mark = "✅" if sk == current_size else "🟢"
                    lines.append(f"  ▫️ <code>{sz}</code> — {escape_html(p_str)} (از {format_toman(item['min_price_toman'])} ت | {item['count']} مدل)")
                    rows.append([{
                        "text": f"{mark} {sz}  •  {p_str} ({pr})",
                        "callback_data": f"set_size_{sk}",
                    }])
                lines.append("")
            else:
                lines.append(
                    "🔴 <b>در این لحظه هیچ سایزی در انبار دولتی باز نیست.</b>\n"
                    "💡 <i>نگران نباشید! از دکمه «سایزهای در صف شارژ» زیر، سایز خودروی خود را انتخاب کنید تا شکارچی به محض بازشدن آن را برای شما شکار کند.</i>\n"
                )

            if show_catalog and cat_sizes:
                lines.append("⏳ <b>سایزهای کاتالوگ سایت‌ها (در صف شارژ برای شکارچی خودکار):</b>")
                extra_btns: List[Dict[str, str]] = []
                for sz in cat_sizes:
                    sk = size_to_key(sz)
                    if sk in avail:
                        continue
                    mark = "🟢 " if sk == current_size else "⏳ "
                    extra_btns.append({"text": f"{mark}{sz}", "callback_data": f"set_size_{sk}"})
                for i in range(0, len(extra_btns), 2):
                    rows.append(extra_btns[i : i + 2])
            elif cat_sizes:
                rows.append([{"text": f"⏳ مشاهده سایر سایزهای کاتالوگ ({len(cat_sizes)} سایز)", "callback_data": "menu_size_catalog"}])

            c2 = "🟢 ۲ حلقه (یک جفت)" if count == 2 else "⚪ ۲ حلقه (یک جفت)"
            c4 = "🟢 ۴ حلقه (سهمیه کامل)" if count == 4 else "⚪ ۴ حلقه (سهمیه کامل)"
            rows.append([
                {"text": c2, "callback_data": "set_count_2"},
                {"text": c4, "callback_data": "set_count_4"},
            ])
            rows.append([
                {"text": "🔄 بروزرسانی موجودی", "callback_data": "menu_size"},
                {"text": "🏠 منوی اصلی", "callback_data": "main_menu"},
            ])

            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"🎯 <b>انتخاب فعلی شما:</b> <code>{escape_html(self._format_size_label(current_size))}</code> — <b>{count} حلقه</b>")
            lines.append("👇 سایز و تعداد حلقه مورد نظرتان را انتخاب کنید:")
            logger.info(f"[MENU_SIZE] chat={chat_id} portal={cur_portal} live_sizes={len(avail)} catalog_sizes={len(cat_sizes)}")
            await log_action(chat_id, "MENU_SIZE", "OK", f"portal={cur_portal} live_sizes={len(avail)} catalog={len(cat_sizes)}", 0.0)
            await self._safe_edit(chat_id, message_id, "\n".join(lines), reply_markup={"inline_keyboard": rows})

        elif data.startswith("set_size_"):
            new_size = data.replace("set_size_", "")
            await upsert_user(chat_id, target_tire_size=new_size)
            user = await get_user(chat_id)
            norm = key_to_size(new_size)
            kb = {
                "inline_keyboard": [
                    [
                        {"text": "📦 بررسی موجودی دولتی", "callback_data": "live_check_stock"},
                        {"text": "💰 قیمت آزاد این سایز", "callback_data": f"mkt_{new_size}"},
                    ],
                    [
                        {"text": "⚡ روشن‌کردن شکارچی", "callback_data": "menu_sniper"},
                        {"text": "🏠 منوی اصلی", "callback_data": "main_menu"},
                    ],
                ]
            }
            await self._safe_edit(
                chat_id,
                message_id,
                (
                    "✅ <b>سایز هدف شما با موفقیت ذخیره شد!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🛞 <b>سایز انتخابی:</b> <code>{escape_html(self._format_size_label(norm))}</code>\n"
                    f"📦 <b>تعداد درخواستی:</b> <b>{user.get('tire_count', 2)} حلقه</b>\n\n"
                    "👇 قدم بعدی را انتخاب کنید:"
                ),
                reply_markup=kb,
            )

        elif data.startswith("set_count_"):
            c = int(data.replace("set_count_", ""))
            await upsert_user(chat_id, tire_count=c)
            await self._route_callback(chat_id, message_id, "menu_size")

        elif data == "menu_market_price":
            rows: List[List[Dict[str, str]]] = []
            # ۸ دسته‌بندی کامل تمام سایزهای تایر (از رینگ ۱۳ تا ۲۰ + وانت/نیسان + کامیون/کشنده)
            cat_items = list(TIRE_SIZE_CATEGORIES.items())
            for i in range(0, len(cat_items), 2):
                pair = []
                for tk, info in cat_items[i : i + 2]:
                    pair.append({"text": info["short"], "callback_data": f"tirecat_{tk}"})
                rows.append(pair)
            rows.append([
                {"text": "🚘 انتخاب با نام خودرو", "callback_data": "menu_car_picker"},
                {"text": "✍️ تایپ سایز دلخواه", "callback_data": "ask_custom_market_size"},
            ])
            rows.append([{"text": "🏠 بازگشت به منوی اصلی", "callback_data": "main_menu"}])

            now_fa = get_tehran_now()["full_fa"]
            text = (
                "💰 <b>استعلام زنده قیمت روز تمامی سایزهای تایر آزاد</b>\n"
                f"🕒 <i>{now_fa}</i>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "🌐 اتصال هم‌زمان به <b>دیجی‌کالا، ترب، باسلام و هایپرتایر</b> برای بیش از <b>۶۰ سایز استاندارد و تخصصی</b>:\n"
                "▫️ <b>سواری:</b> رینگ ۱۳، ۱۴، ۱۵ و ۱۶ (فابریک و پهن اسپرت)\n"
                "▫️ <b>شاسی‌بلند و آفرود:</b> رینگ ۱۷، ۱۸، ۱۹ و ۲۰\n"
                "▫️ <b>وانت و باری سبک:</b> نیسان (حتی <code>7.50R16</code>)، مزدا، آریسان، ون\n"
                "▫️ <b>کامیون و کشنده:</b> ایسوزو، خاور، ولوو، اسکانیا، مایلر (<code>12.00R24</code>)\n\n"
                "👇 رینگ یا کلاس خودروی خود را انتخاب کنید:"
            )
            await self._safe_edit(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data.startswith("tirecat_"):
            tk = data.replace("tirecat_", "")
            cat = TIRE_SIZE_CATEGORIES.get(tk)
            if not cat:
                await self._route_callback(chat_id, message_id, "menu_market_price")
                return
            rows = []
            sz_list = cat["sizes"]
            for i in range(0, len(sz_list), 2):
                pair = []
                for sz, car_lbl in sz_list[i : i + 2]:
                    short_c = car_lbl.split("/")[0].strip()
                    pair.append({"text": f"🛞 {sz} • {short_c}", "callback_data": f"mkt_{size_to_key(sz)}"})
                rows.append(pair)
            rows.append([
                {"text": "🔙 بازگشت به دسته‌های تایر", "callback_data": "menu_market_price"},
                {"text": "🏠 منوی اصلی", "callback_data": "main_menu"},
            ])
            text = (
                f"<b>{escape_html(cat['title'])}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "👇 سایز دقیق روی دیواره لاستیک را انتخاب کنید تا قیمت زنده همین ساعت را از فروشگاه‌های کشور بگیرید:"
            )
            await self._safe_edit(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data == "ask_custom_market_size":
            await set_state(chat_id, "AWAIT_MARKET_SIZE")
            kb = {"inline_keyboard": [[{"text": "🔙 انصراف و بازگشت", "callback_data": "menu_market_price"}]]}
            await self._safe_edit(
                chat_id,
                message_id,
                (
                    "✍️ <b>تایپ سایز دلخواه تایر برای استعلام قیمت روز</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    "هر سایزی (سواری، شاسی‌بلند، وانت یا کامیون) را بفرستید:\n"
                    "📌 <i>مثال‌ها:</i> <code>185/65R14</code> • <code>225/65R17</code> • <code>7.50R16</code> • <code>295/80R22.5</code> • <code>12.00R24</code>\n\n"
                    "💡 <i>حتی با اعداد فارسی هم بنویسید ربات هوشمندانه تشخیص می‌دهد!</i>"
                ),
                reply_markup=kb,
            )

        elif data.startswith("mktrefresh_"):
            size_key = data.replace("mktrefresh_", "")
            await self._send_market_price_report(chat_id, key_to_size(size_key), edit_msg_id=message_id, force_refresh=True)

        elif data.startswith("mkt_"):
            size_key = data.replace("mkt_", "")
            await self._send_market_price_report(chat_id, key_to_size(size_key), edit_msg_id=message_id)

        elif data == "menu_sniper":
            is_active = user.get("sniper_enabled", 0)
            status_badge = "🟢 <b>فعال و در حال پایش زنده</b>" if is_active else "🔴 <b>خاموش</b>"
            btn_toggle = "🛑 خاموش کردن شکارچی خودکار" if is_active else "🚀 روشن کردن شکارچی خودکار"
            portal_name = PORTALS.get(user.get("target_portal", "all"), PORTALS["all"]).get("title", "")
            size_name = self._format_size_label(user.get("target_tire_size", "185_65_14"))

            text = (
                "⚡ <b>مرکز کنترل شکارچی خودکار تایر دولتی</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📡 <b>وضعیت فعلی:</b> {status_badge}\n"
                f"🏭 <b>کارخانه‌های زیر نظر:</b> <code>{escape_html(portal_name)}</code>\n"
                f"🛞 <b>سایز هدف شما:</b> <code>{escape_html(size_name)}</code>\n"
                f"📦 <b>تعداد درخواستی:</b> <b>{user.get('tire_count', 2)} حلقه</b>\n\n"
                "🤖 <b>شکارچی دقیقاً چطور کار می‌کند؟</b>\n"
                "▫️ شبانه‌روزی و هر چند ثانیه یک‌بار، انبار سایت‌های دولتی را به جای شما چک می‌کند.\n"
                "▫️ به محض باز شدن سایز مورد نظرتان، سریع پیام هشدار، قیمت مصوب و لینک مستقیم خرید/رزرو را همین‌جا برایتان می‌فرستد!\n\n"
                "👇 وضعیت شکارچی یا تنظیمات آن را مدیریت کنید:"
            )
            kb = {
                "inline_keyboard": [
                    [{"text": btn_toggle, "callback_data": "toggle_sniper"}],
                    [
                        {"text": "🏭 تغییر کارخانه هدف", "callback_data": "menu_portal"},
                        {"text": "🛞 تغییر سایز و تعداد", "callback_data": "menu_size"},
                    ],
                    [{"text": "🏠 بازگشت به منوی اصلی", "callback_data": "main_menu"}],
                ]
            }
            await self._safe_edit(chat_id, message_id, text, reply_markup=kb)

        elif data == "toggle_sniper":
            is_active = user.get("sniper_enabled", 0)
            if is_active:
                await self.sniper.stop_sniper_for_user(chat_id)
            else:
                if not user.get("national_id") or not user.get("mobile"):
                    miss_kb = {
                        "inline_keyboard": [
                            [{"text": "👤 ثبت سریع کد ملی و موبایل", "callback_data": "menu_profile"}],
                            [{"text": "🏠 بازگشت به منوی اصلی", "callback_data": "main_menu"}],
                        ]
                    }
                    await self._safe_edit(
                        chat_id,
                        message_id,
                        (
                            "⚠️ <b>اطلاعات مالک هنوز کامل نیست!</b>\n"
                            "━━━━━━━━━━━━━━━━━━━━\n\n"
                            "برای اینکه شکارچی خودکار بتواند برایتان فعال شود، لطفاً ابتدا فقط <b>کد ملی</b> و <b>شماره موبایل</b> مالک را ثبت کنید (کمتر از ۲۰ ثانیه وقت می‌برد)."
                        ),
                        reply_markup=miss_kb,
                    )
                    return
                await upsert_user(chat_id, sniper_enabled=1)
                await self.sniper.start_sniper_for_user(chat_id)
            await self._route_callback(chat_id, message_id, "menu_sniper")

        elif data == "live_check_stock":
            await self._safe_edit(
                chat_id,
                message_id,
                "📦 <b>در حال استعلام زنده و مستقیم از انبار کارخانه‌های دولتی...</b>\n\n⏳ <i>در حال بررسی لحظه‌ای موجودی و قیمت‌های مصوب...</i>",
            )
            stock_info = await self.sniper.check_live_stock_now(chat_id)
            p_title = PORTALS.get(stock_info["portal"], PORTALS["all"]).get("title", stock_info["portal"])
            matched = stock_info["matched_items"]
            all_avail = stock_info["available_sizes"]
            now_fa = get_tehran_now()["compact_fa"]

            lines = [
                f"📦 <b>گزارش زنده انبار تایر دولتی</b>",
                f"🕒 <i>{now_fa}</i>",
                "━━━━━━━━━━━━━━━━━━━━\n",
                f"🏭 <b>دامنه بررسی:</b> <code>{escape_html(p_title)}</code>",
                f"🎯 <b>سایز هدف شما:</b> <code>{escape_html(stock_info['tire_size_display'])}</code>\n",
            ]

            if matched:
                lines.append(f"🎉 <b>خبر عالی! {len(matched)} مدل از سایز شما همین الان موجود است:</b>")
                for it in matched[:5]:
                    safe_it_u = html.escape(str(it.get("url") or ""), quote=True)
                    lines.append(
                        f"  🟢 <b>{escape_html(it.get('brand', ''))} {escape_html(it.get('model', ''))}</b> — "
                        f"<b>{format_toman(it.get('price_toman', 0))}</b> ت | {escape_html(it.get('portal_title', ''))}\n"
                        f"     🔗 <a href=\"{safe_it_u}\">ورود و خرید مستقیم ↗️</a>"
                    )
                lines.append("\n⚡ <i>پیشنهاد: همین الان از لینک بالا خرید کنید یا شکارچی خودکار را روشن بگذارید.</i>")
            else:
                lines.append(
                    f"🔴 سایز انتخابی شما (<code>{escape_html(stock_info['tire_size_display'])}</code>) در این دقیقه موجود نیست.\n"
                    "💡 <i>اگر «شکارچی خودکار» را روشن کنید، به محض شارژ شدن به شما خبر می‌دهیم.</i>"
                )

            if all_avail:
                lines.append("\n🟢 <b>سایزهایی که همین الان در سایت‌های دولتی باز هستند:</b>")
                for bucket in sorted(all_avail.values(), key=lambda b: b["size"])[:8]:
                    pr_txt = f"— از <b>{format_toman(bucket['min_price_toman'])}</b> ت" if bucket["min_price_toman"] else ""
                    lines.append(f"  ▫️ <code>{bucket['size']}</code> ({'، '.join(bucket['portals'])}) {pr_txt}")

            kb = {
                "inline_keyboard": [
                    [
                        {"text": "🔄 استعلام مجدد انبار", "callback_data": "live_check_stock"},
                        {"text": "💰 قیمت آزاد این سایز", "callback_data": f"mkt_{stock_info['tire_size']}"},
                    ],
                    [
                        {"text": "⚡ شکارچی خودکار", "callback_data": "menu_sniper"},
                        {"text": "🛞 تغییر سایز هدف", "callback_data": "menu_size"},
                    ],
                    [
                        {"text": "🏭 تغییر کارخانه هدف", "callback_data": "menu_portal"},
                        {"text": "🏠 منوی اصلی", "callback_data": "main_menu"},
                    ],
                ]
            }
            logger.info(
                f"[STOCK_CHECK] chat={chat_id} portal={stock_info['portal']} size={stock_info['tire_size']} "
                f"matched={len(matched)} total_avail_sizes={len(all_avail)}"
            )
            await log_action(
                chat_id,
                "STOCK_CHECK",
                "IN_STOCK" if matched else "OUT_OF_STOCK",
                f"portal={stock_info['portal']} size={stock_info['tire_size']} matched={len(matched)} avail_sizes={len(all_avail)}",
                0.0,
            )
            await self._safe_edit(chat_id, message_id, "\n".join(lines), reply_markup=kb)

        elif data == "auth_real_otp":
            if not user.get("mobile"):
                miss_kb = {
                    "inline_keyboard": [
                        [{"text": "📱 ثبت شماره موبایل مالک", "callback_data": "menu_profile"}],
                        [{"text": "🏠 بازگشت به منوی اصلی", "callback_data": "main_menu"}],
                    ]
                }
                await self._safe_edit(
                    chat_id,
                    message_id,
                    (
                        "⚠️ <b>شماره موبایل هنوز ثبت نشده است!</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━\n\n"
                        "برای دریافت کد پیامکی ورود از سایت کارخانه، لطفاً ابتدا شماره همراه مالک خودرو را در بخش «👤 اطلاعات مالک» ثبت کنید."
                    ),
                    reply_markup=miss_kb,
                )
                return
            portal = user.get("target_portal", "all")
            if portal not in ("barez", "kavir"):
                kb = {
                    "inline_keyboard": [
                        [
                            {"text": "🏭 پیامک ورود بارز", "callback_data": "otp_send_barez"},
                            {"text": "🏭 پیامک ورود کویرتایر", "callback_data": "otp_send_kavir"},
                        ],
                        [{"text": "🏠 بازگشت به منوی اصلی", "callback_data": "main_menu"}],
                    ]
                }
                await self._safe_edit(
                    chat_id,
                    message_id,
                    (
                        "🔐 <b>ورود پیامکی مستقیم به حساب کارخانه</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"📱 <b>شماره ثبت‌شده شما:</b> <code>{user.get('mobile')}</code>\n\n"
                        "ℹ️ <b>این بخش چه کمکی می‌کند؟</b>\n"
                        "با تایید یک‌باره کد پیامکی رسمی، نشست (سشن) ورود شما در سایت کارخانه آماده می‌شود تا هنگام باز شدن ظرفیت، بدون معطلی وارد شوید.\n\n"
                        "👇 کد پیامکی از کدام کارخانه برایتان ارسال شود؟"
                    ),
                    reply_markup=kb,
                )
                return
            await self._route_callback(chat_id, message_id, f"otp_send_{portal}")

        elif data.startswith("otp_send_"):
            otp_portal = data.replace("otp_send_", "")
            p_short = PORTALS.get(otp_portal, {}).get("short", otp_portal)
            await self._safe_edit(
                chat_id,
                message_id,
                f"📲 <b>در حال ارسال درخواست کد پیامکی از {escape_html(p_short)} به شماره <code>{user.get('mobile')}</code>...</b>",
            )
            res = await self.sniper.request_real_otp(chat_id, portal_override=otp_portal)
            logger.info(f"[OTP_SEND] chat={chat_id} portal={otp_portal} ok={res.get('ok')} latency={res.get('latency_ms', 0)}ms")
            await log_action(
                chat_id,
                "OTP_SEND",
                "OK" if res.get("ok") else "FAIL",
                f"portal={otp_portal} msg={res.get('message', '')[:80]}",
                res.get("latency_ms", 0.0),
            )
            if res.get("ok"):
                await set_state(chat_id, f"AWAIT_REAL_OTP_{otp_portal.upper()}")
                kb = {"inline_keyboard": [[{"text": "🔙 انصراف و منوی اصلی", "callback_data": "main_menu"}]]}
                await self._safe_edit(
                    chat_id,
                    message_id,
                    (
                        "📩 <b>کد پیامکی با موفقیت ارسال شد!</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"لطفاً کد تاییدی که روی شماره <code>{user.get('mobile')}</code> دریافت کردید را همین‌جا تایپ و ارسال کنید:"
                    ),
                    reply_markup=kb,
                )
            else:
                kb = {
                    "inline_keyboard": [
                        [
                            {"text": "🔄 تلاش مجدد", "callback_data": f"otp_send_{otp_portal}"},
                            {"text": "🏠 منوی اصلی", "callback_data": "main_menu"},
                        ]
                    ]
                }
                await self._safe_edit(
                    chat_id,
                    message_id,
                    f"❌ <b>ارسال پیامک انجام نشد:</b>\n━━━━━━━━━━━━━━━━━━━━\n\n{escape_html(res.get('message', ''))}",
                    reply_markup=kb,
                )

        elif data == "view_profile":
            p_name = PORTALS.get(user.get("target_portal", "all"), PORTALS["all"]).get("title", "")
            s_name = self._format_size_label(user.get("target_tire_size", "185_65_14"))
            sniper_st = "🟢 <b>روشن و فعال</b>" if user.get("sniper_enabled", 0) else "🔴 <b>خاموش</b>"
            _, progress_bar = self.calculate_profile_completion(user)

            summary = (
                "📋 <b>وضعیت و پروفایل کاربری شما</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🆔 <b>کد ملی مالک:</b> <code>{user.get('national_id') or 'ثبت نشده'}</code>\n"
                f"📱 <b>موبایل مالک:</b> <code>{user.get('mobile') or 'ثبت نشده'}</code>\n\n"
                f"🏭 <b>کارخانه هدف:</b> <code>{escape_html(p_name)}</code>\n"
                f"🛞 <b>سایز انتخابی:</b> <code>{escape_html(s_name)}</code>\n"
                f"📦 <b>تعداد درخواستی:</b> <b>{user.get('tire_count', 2)} حلقه</b>\n"
                f"⚡ <b>وضعیت شکارچی:</b> {sniper_st}\n"
                f"📊 <b>میزان آمادگی:</b> <code>{progress_bar}</code>"
            )
            kb = {
                "inline_keyboard": [
                    [
                        {"text": "✏️ ویرایش اطلاعات مالک", "callback_data": "menu_profile"},
                        {"text": "⚡ تنظیمات شکارچی", "callback_data": "menu_sniper"},
                    ],
                    [{"text": "🏠 بازگشت به منوی اصلی", "callback_data": "main_menu"}],
                ]
            }
            await self._safe_edit(chat_id, message_id, summary, reply_markup=kb)

        elif data == "menu_guide":
            guide_text = (
                "📖 <b>راهنمای جامع خرید تایر دولتی و قیمت روز</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "1️⃣ <b>اطلاعات مالک (فقط ۲ مورد):</b>\n"
                "   در بخش «👤 اطلاعات مالک»، فقط <b>کد ملی</b> و <b>موبایل به نام مالک</b> را وارد کنید. بقیه اطلاعات خودرو موقع پرداخت نهایی در خود سایت کارخانه ثبت می‌شود.\n\n"
                "2️⃣ <b>انتخاب کارخانه و سایز:</b>\n"
                "   کارخانه هدف را روی <b>«همه کارخانه‌ها»</b> بگذارید و از بخش «🛞 سایز» اندازه تایر و تعداد حلقه (۲ یا ۴ حلقه) را مشخص کنید.\n\n"
                "3️⃣ <b>شکارچی خودکار (مهم‌ترین بخش):</b>\n"
                "   وقتی شکارچی را روشن کنید، ربات هر چند ثانیه انبار ۱۰ سایت دولتی را می‌گردد و به محض باز شدن سایزتان، فوری خبرتان می‌کند.\n\n"
                "4️⃣ <b>قیمت لحظه‌ای تایر آزاد و روغن موتور:</b>\n"
                "   از دکمه‌های منو یا تایپ مستقیم سایز تایر (<code>185/65R14</code>)، گرانروی روغن (<code>10W40</code>) یا نام ماشین (<code>پژو ۲۰۶</code>) نرخ دقیق همین ساعت و لینک خرید را بگیرید.\n\n"
                "⏰ <b>نکات طلایی سهمیه دولتی:</b>\n"
                "▫️ سهمیه هر خودرو <b>۴ حلقه در سال</b> به نام مالک رسمی است.\n"
                "▫️ بیشترین زمان شارژ سایت‌ها معمولاً صبح‌ها <b>۰۸:۳۰ تا ۱۱:۳۰</b> است.\n"
                "▫️ هنگام باز کردن لینک خرید کویرتایر و سامانه تجارت، فیلترشکن گوشی را خاموش کنید.\n\n"
                "⌨️ <b>دستورات سریع:</b>\n"
                "<code>/start</code> منوی اصلی • <code>/stock</code> انبار دولتی • <code>/price</code> تایر آزاد • <code>/oil</code> روغن موتور • <code>/car</code> نام خودرو • <code>/sniper</code> شکارچی"
            )
            kb = {
                "inline_keyboard": [
                    [
                        {"text": "👤 تکمیل اطلاعات مالک", "callback_data": "menu_profile"},
                        {"text": "⚡ شکارچی خودکار", "callback_data": "menu_sniper"},
                    ],
                    [
                        {"text": "💰 قیمت تایر آزاد", "callback_data": "menu_market_price"},
                        {"text": "🛢 خرید روغن موتور", "callback_data": "menu_oil_price"},
                    ],
                    [{"text": "🏠 بازگشت به منوی اصلی", "callback_data": "main_menu"}],
                ]
            }
            await self._safe_edit(chat_id, message_id, guide_text, reply_markup=kb)

    async def handle_text_message(self, message: Dict[str, Any]):
        chat_id = message.get("chat", {}).get("id")
        text = persian_to_english_digits(message.get("text", "").strip())
        username = message.get("from", {}).get("username", "")

        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            cmd = parts[0].split("@")[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""
            if cmd in ("/start", "/menu"):
                await self.handle_start(chat_id, username)
            elif cmd == "/price":
                sz = normalize_tire_size(arg) if arg else None
                if sz:
                    await set_state(chat_id, "IDLE")
                    await self._send_market_price_report(chat_id, sz)
                else:
                    await self._route_callback(chat_id, None, "menu_market_price")
            elif cmd == "/oil":
                gr = normalize_oil_grade(arg) if arg else None
                if gr:
                    await set_state(chat_id, "IDLE")
                    await self._send_oil_price_report(chat_id, gr)
                else:
                    await self._route_callback(chat_id, None, "menu_oil_price")
            elif cmd == "/stock":
                await self._route_callback(chat_id, None, "live_check_stock")
            elif cmd == "/sniper":
                await self._route_callback(chat_id, None, "menu_sniper")
            elif cmd == "/profile":
                await self._route_callback(chat_id, None, "menu_profile")
            elif cmd == "/car":
                await self._route_callback(chat_id, None, "menu_car_picker")
            elif cmd == "/compare":
                await self._route_callback(chat_id, None, "compare_gov_market")
            elif cmd == "/help":
                await self._route_callback(chat_id, None, "menu_guide")
            else:
                await self.handle_start(chat_id, username)
            return

        user = await get_user(chat_id)
        if not user:
            user = await upsert_user(chat_id, username=username)

        state = user.get("state", "IDLE")

        if state == "AWAIT_NAT_ID":
            cleaned = re.sub(r"\D", "", text)
            if is_valid_iran_national_id(cleaned):
                if not user.get("mobile"):
                    await upsert_user(chat_id, national_id=cleaned, state="AWAIT_MOBILE")
                    next_kb = {
                        "inline_keyboard": [
                            [
                                {"text": "👤 برگشت به اطلاعات مالک", "callback_data": "menu_profile"},
                                {"text": "🏠 منوی اصلی", "callback_data": "main_menu"},
                            ]
                        ]
                    }
                    await self.bot.send_message(
                        chat_id,
                        (
                            f"✅ <b>کد ملی با موفقیت تایید و ثبت شد!</b>\n🆔 <code>{cleaned}</code>\n\n"
                            "📱 <b>قدم دوم (آخرین مرحله):</b>\n"
                            "حالا شماره موبایل <b>۱۱ رقمی به نام مالک</b> را بفرستید تا پروفایل شما ۱۰۰٪ تکمیل شود:\n"
                            "📌 <i>مثال:</i> <code>09123456789</code>"
                        ),
                        reply_markup=next_kb,
                    )
                else:
                    await upsert_user(chat_id, national_id=cleaned, state="IDLE")
                    await self.bot.send_message(
                        chat_id,
                        f"🎉 <b>کد ملی ثبت شد و پروفایل شما ۱۰۰٪ کامل است!</b>\n🆔 <code>{cleaned}</code>\n\n👇 می‌توانید همین الان شکارچی خودکار را روشن کنید:",
                        reply_markup=self._profile_saved_keyboard(),
                    )
            else:
                cancel_kb = {"inline_keyboard": [[{"text": "🔙 انصراف و بازگشت", "callback_data": "menu_profile"}]]}
                await self.bot.send_message(
                    chat_id,
                    "❌ <b>کد ملی واردشده معتبر نیست!</b>\nلطفاً یک کد ملی واقعی <b>۱۰ رقمی</b> (بدون خط تیره و اشتباه تایپی) دوباره بفرستید:",
                    reply_markup=cancel_kb,
                )

        elif state == "AWAIT_MOBILE":
            cleaned = re.sub(r"\D", "", text)
            if len(cleaned) == 11 and cleaned.startswith("09"):
                updated_user = await upsert_user(chat_id, mobile=cleaned, state="IDLE")
                done_note = "🎉 <b>پروفایل شما ۱۰۰٪ تکمیل شد و آماده روشن‌کردن شکارچی است!</b>" if updated_user.get("national_id") else "✅ <b>شماره موبایل با موفقیت ذخیره شد!</b>"
                await self.bot.send_message(
                    chat_id,
                    f"{done_note}\n📱 <code>{cleaned}</code>\n\n👇 از دکمه‌های زیر ادامه دهید:",
                    reply_markup=self._profile_saved_keyboard(),
                )
            else:
                cancel_kb = {"inline_keyboard": [[{"text": "🔙 انصراف و بازگشت", "callback_data": "menu_profile"}]]}
                await self.bot.send_message(
                    chat_id,
                    "❌ <b>شماره موبایل نامعتبر است!</b>\nلطفاً شماره ۱۱ رقمی با شروع <code>09</code> بفرستید (مثلاً <code>09121234567</code>):",
                    reply_markup=cancel_kb,
                )

        elif state.startswith("AWAIT_REAL_OTP"):
            otp_portal = "barez" if "BAREZ" in state else ("kavir" if "KAVIR" in state else None)
            await self.bot.send_message(chat_id, "⏳ <b>در حال بررسی کد تایید در سرور رسمی کارخانه...</b>")
            verify_res = await self.sniper.verify_real_otp(chat_id, text.strip(), portal_override=otp_portal)
            if verify_res.get("ok"):
                await set_state(chat_id, "IDLE")
                await self.bot.send_message(chat_id, verify_res.get("message", "✅ ورود با موفقیت تایید شد!"), reply_markup=self.get_main_keyboard(await get_user(chat_id)))
            else:
                cancel_kb = {"inline_keyboard": [[{"text": "🏠 انصراف و منوی اصلی", "callback_data": "main_menu"}]]}
                await self.bot.send_message(chat_id, f"❌ {verify_res.get('message')}\nلطفاً کد صحیح پیامک‌شده را دوباره بفرستید:", reply_markup=cancel_kb)

        elif state == "AWAIT_MARKET_SIZE":
            norm = normalize_tire_size(text)
            if norm:
                await set_state(chat_id, "IDLE")
                await self._send_market_price_report(chat_id, norm)
            else:
                car_k = detect_car_from_text(text, CAR_TIRE_CATALOG)
                if car_k:
                    await set_state(chat_id, "IDLE")
                    await self._send_car_recommendation(chat_id, car_k)
                    return
                cancel_kb = {"inline_keyboard": [[{"text": "🔙 بازگشت به لیست سایزها", "callback_data": "menu_market_price"}]]}
                await self.bot.send_message(
                    chat_id,
                    "❌ <b>فرمت سایز تایر درست نیست!</b>\n📌 لطفاً سایز (مثل <code>185/65R14</code>) یا نام خودرو (مثل <code>پژو ۲۰۶</code>) را بفرستید:",
                    reply_markup=cancel_kb,
                )

        elif state == "AWAIT_OIL_GRADE":
            gr = normalize_oil_grade(text)
            if gr:
                await set_state(chat_id, "IDLE")
                await self._send_oil_price_report(chat_id, gr)
            else:
                car_k = detect_car_from_text(text, CAR_TIRE_CATALOG)
                if car_k:
                    await set_state(chat_id, "IDLE")
                    oil_g = CAR_TIRE_CATALOG[car_k].get("oil_grade", "10W40")
                    await self._send_oil_price_report(chat_id, oil_g)
                    return
                cancel_kb = {"inline_keyboard": [[{"text": "🔙 بازگشت به منوی روغن موتور", "callback_data": "menu_oil_price"}]]}
                await self.bot.send_message(
                    chat_id,
                    "❌ <b>گرانروی روغن موتور درست نیست!</b>\n📌 لطفاً گرانروی (مثل <code>10W40</code>، <code>20W50</code>، <code>5W30</code>) یا نام خودرو (مثل <code>پراید</code>) را بفرستید:",
                    reply_markup=cancel_kb,
                )

        else:
            # ۱. تشخیص مستقیم سایز تایر (مثل 185/65R14 یا ۱۸۵/۶۵/۱۴)
            detected_size = normalize_tire_size(text)
            if detected_size:
                await self._send_market_price_report(chat_id, detected_size)
                return

            # ۲. تشخیص مستقیم گرانروی روغن موتور (مثل 10W40 یا 5w30 یا 15W40)
            detected_oil = normalize_oil_grade(text)
            if detected_oil:
                await self._send_oil_price_report(chat_id, detected_oil)
                return

            # ۳. اگر کاربر بنویسد «روغن پراید» یا «واسکازین ۲۰۶» مستقیم روغن مناسب همان خودرو را استعلام می‌گیرد
            low = text.lower()
            detected_car = detect_car_from_text(text, CAR_TIRE_CATALOG)
            if detected_car and any(k in low for k in ("گیربکس", "واسکازین", "دنده", "دیفرانسیل")):
                g_oil = CAR_TIRE_CATALOG[detected_car].get("gear_oil", "75W80")
                await self._send_oil_price_report(chat_id, g_oil)
                return
            if detected_car and "روغن" in low:
                oil_g = CAR_TIRE_CATALOG[detected_car].get("oil_grade", "10W40")
                await self._send_oil_price_report(chat_id, oil_g)
                return

            # ۴. تشخیص هوشمند نام خودرو (مثل پژو ۲۰۶، پراید، دنا، نیسان، خاور، کامیون و...)
            if detected_car:
                await self._send_car_recommendation(chat_id, detected_car)
                return

            # ۵. درک هوشمند کلمات کلیدی فارسی پرکاربرد
            if any(k in low for k in ("واسکازین", "گیربکس", "دنده", "دیفرانسیل")):
                await self._route_callback(chat_id, None, "oilcat_gear_manual")
                return
            if any(k in low for k in ("روغن", "بهران", "ایرانول", "اسپیدی", "کاسترول", "لیکومولی")):
                await self._route_callback(chat_id, None, "menu_oil_price")
                return
            if any(k in low for k in ("موجودی", "انبار", "دولتی")):
                await self._route_callback(chat_id, None, "live_check_stock")
                return
            if any(k in low for k in ("مقایسه", "سود", "اختلاف")):
                await self._route_callback(chat_id, None, "compare_gov_market")
                return
            if any(k in low for k in ("شکارچی", "خودکار", "اسنایپر")):
                await self._route_callback(chat_id, None, "menu_sniper")
                return
            if any(k in low for k in ("قیمت", "آزاد", "نرخ")):
                await self._route_callback(chat_id, None, "menu_market_price")
                return
            if any(k in low for k in ("راهنما", "کمک", "چجوری", "چطوری")):
                await self._route_callback(chat_id, None, "menu_guide")
                return

            await self.bot.send_message(
                chat_id=chat_id,
                text="👇 لطفاً از منوی زیر انتخاب کنید — یا مستقیم <b>نام خودرو</b> (<code>دنا</code>)، <b>سایز تایر</b> (<code>185/65R14</code>) یا <b>روغن موتور</b> (<code>10W40</code>) را تایپ کنید:",
                reply_markup=self.get_main_keyboard(user),
            )
