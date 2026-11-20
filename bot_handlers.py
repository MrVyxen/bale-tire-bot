import asyncio
import html
import re
import logging
from typing import Dict, Any, Optional, List
from database import (
    get_user,
    upsert_user,
    set_state,
    log_action,
    get_previous_market_snapshot,
    create_support_ticket,
    get_user_tickets,
    get_ticket,
    reply_support_ticket,
)
from bale_api import BaleBotClient
from config import (
    PORTALS,
    CAR_HINT_FOR_SIZE,
    MARKET_TIRE_SIZES,
    TIRE_SIZE_CATEGORIES,
    CAR_TIRE_CATALOG,
    OIL_GRADES,
    OIL_CATEGORIES,
    ADMIN_CHAT_ID,
    SUPPORT_HANDLE,
    SUPPORT_PHONE,
    SUPPORT_HOURS,
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
        return pct, ("کامل و آماده ✅" if pct == 100 else f"تکمیل {pct}% ⚠️")

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
            "🟢 شکارچی خودکار: روشن و بیدار 🛰"
            if is_sniper_on
            else "⚡ روشن کردن شکارچی خودکار تایر"
        )

        pct, _ = cls.calculate_profile_completion(user)
        prof_badge = "✅" if pct == 100 else "⚠️"

        p_key = user.get("target_portal", "all")
        p_short = PORTALS.get(p_key, PORTALS["all"]).get("short", "همه کارخانه‌ها")
        cur_size = key_to_size(user.get("target_tire_size", "185_65_14"))

        return {
            "inline_keyboard": [
                [{"text": sniper_btn, "callback_data": "menu_sniper"}],
                [
                    {"text": "📦 موجودی لاستیک دولتی", "callback_data": "live_check_stock"},
                    {"text": "💰 قیمت روز لاستیک آزاد", "callback_data": "menu_market_price"},
                ],
                [
                    {"text": "🛢 خرید و قیمت انواع روغن", "callback_data": "menu_oil_price"},
                    {"text": "🚘 انتخاب با اسم ماشین", "callback_data": "menu_car_picker"},
                ],
                [
                    {"text": f"🛞 سایز تایر ({cur_size})", "callback_data": "menu_size"},
                    {"text": f"🏭 کارخانه‌ها ({p_short})", "callback_data": "menu_portal"},
                ],
                [
                    {"text": f"👤 مشخصات مالک ({prof_badge})", "callback_data": "menu_profile"},
                    {"text": "⚖️ چقدر سود می‌کنم؟", "callback_data": "compare_gov_market"},
                ],
                [
                    {"text": "🎧 ارتباط با پشتیبانی", "callback_data": "menu_support"},
                    {"text": "📖 راهنمای ساده خرید", "callback_data": "menu_guide"},
                ],
            ]
        }

    def _build_dashboard_text(self, user: Dict[str, Any], header: str) -> str:
        pct, status_text = self.calculate_profile_completion(user)
        sniper_st = "🟢 <b>روشن (در حال بررسی ۲۴ ساعته سایت‌ها)</b>" if user.get("sniper_enabled", 0) else "⚪ <b>خاموش (آماده فعال‌سازی)</b>"
        portal_name = PORTALS.get(user.get("target_portal", "all"), PORTALS["all"]).get("title", "همه کارخانه‌ها")
        size_label = self._format_size_label(user.get("target_tire_size", "185_65_14"))
        now_fa = get_tehran_now()["compact_fa"]

        ready_hint = (
            "✅ <i>مشخصاتت تکمیله و همه‌چیز آماده خریده!</i>"
            if pct == 100
            else "💡 <i>برای اینکه موقع اعلام موجودی معطل نشی، مشخصات مالک رو از دکمه زیر ثبت کن.</i>"
        )

        return (
            f"✨ <b>{header}</b> ✨\n"
            f"🗓 <i>امروز: {now_fa}</i>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🛰 <b>شکارچی تایر دولتی:</b> {sniper_st}\n"
            f"🛞 <b>سایز انتخابی:</b> <code>{escape_html(size_label)}</code>\n"
            f"🏭 <b>کارخانه‌های هدف:</b> <code>{escape_html(portal_name)}</code>\n"
            f"📦 <b>تعداد درخواستی:</b> <b>{user.get('tire_count', 2)} حلقه</b>\n"
            f"👤 <b>وضعیت مدارک مالک:</b> <b>{status_text}</b>\n\n"
            f"{ready_hint}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💬 <b>ترفند راحت:</b> می‌تونی همین الان اسم ماشینت (مثل <code>پژو ۲۰۶</code>)، سایز تایر (مثل <code>185/65R14</code>) یا روغن موتور (مثل <code>10W40</code>) رو مستقیم بفرستی تا فوری قیمتش رو بگیری!"
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

    # =========================================================================
    # استعلام و نمایش فوق‌دقیق قیمت لاستیک آزاد
    # =========================================================================
    async def _send_market_price_report(
        self, chat_id: int, raw_size: str, edit_msg_id: Optional[int] = None, force_refresh: bool = False
    ):
        norm = normalize_tire_size(raw_size) or raw_size
        loading_txt = (
            f"🔎 <b>در حال استعلام قیمت روز لاستیک <code>{escape_html(norm)}</code>...</b>\n\n"
            "⏳ <i>چند لحظه صبر کنید، دارم قیمت دقیق فروشگاه‌های معتبر کشور (دیجی‌کالا، ترب، باسلام) رو چک می‌کنم...</i>"
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
                    {"text": "🔄 بروزرسانی قیمت", "callback_data": f"mktrefresh_{size_key}"},
                    {"text": "⚖️ چقدر سود دولتی داره؟", "callback_data": f"cmp_{size_key}"},
                ],
                [
                    {"text": "🎯 ثبت برای شکارچی دولتی", "callback_data": f"set_size_{size_key}"},
                    {"text": "🔍 استعلام سایز دیگر", "callback_data": "menu_market_price"},
                ],
                [{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}],
            ]
        }

        if not report.get("ok") or report.get("total_found", 0) == 0:
            fail_kb = {
                "inline_keyboard": [
                    [
                        {"text": "🔄 تلاش مجدد", "callback_data": f"mktrefresh_{size_key}"},
                        {"text": "🔍 انتخاب از لیست سایزها", "callback_data": "menu_market_price"},
                    ],
                    [{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}],
                ]
            }
            fail_txt = (
                f"⚠️ <b>قیمتی برای سایز <code>{escape_html(norm)}</code> پیدا نشد!</b>\n\n"
                "💡 لطفاً مطمئن شو سایز رو درست نوشتی (مثل <code>185/65R14</code> یا <code>205/60R15</code>) یا از دکمه زیر یک سایز استاندارد انتخاب کن."
            )
            if edit_msg_id:
                await self._safe_edit(chat_id, edit_msg_id, fail_txt, reply_markup=fail_kb)
            else:
                await self.bot.send_message(chat_id=chat_id, text=fail_txt, reply_markup=fail_kb)
            return

        ts = report["timestamp"]
        car_hint = CAR_HINT_FOR_SIZE.get(report["size"])
        car_line = f"🚘 <b>مناسب خودروهای:</b> {escape_html(car_hint)}\n" if car_hint else ""

        lines: List[str] = [
            f"💰 <b>قیمت روز لاستیک • سایز <code>{escape_html(report['size'])}</code></b>",
            car_line,
            f"🕒 <b>استعلام زنده:</b> {ts['full_fa']}",
            "━━━━━━━━━━━━━━━━━━━━\n",
        ]

        # ۱. نمایش برندهای شاخص ایرانی (بارز، کویر، یزد، ایران‌تایر، گلدستون)
        featured = report.get("featured_ir_brands", {})
        if featured:
            lines.append("🇮🇷 <b>لاستیک‌های پرفروش ایرانی (تاییدشده):</b>\n")
            for b_name, off in featured.items():
                m_str = f" مدل <b>{escape_html(off['model'])}</b>" if off.get("model") else ""
                yr_str = f" (تولید {off['year']})" if off.get("year") else ""
                pair_p = format_toman(off["pair_price_toman"])
                unit_p = format_toman(off["unit_price_toman"])
                shop = escape_html(off["shop_name"][:20])
                src = escape_html(off["source"])
                safe_url = html.escape(str(off.get("url") or ""), quote=True)

                lines.append(
                    f"🔹 <b>{escape_html(b_name)}</b>{m_str}{yr_str}:\n"
                    f"  ▫️ قیمت جفت (۲ حلقه): <b>{pair_p}</b> تومان\n"
                    f"  ▫️ قیمت هر حلقه: <b>{unit_p}</b> تومان\n"
                    f"  🏬 {src} ({shop}) — <a href=\"{safe_url}\">مشاهده و خرید آنلاین ↗️</a>\n"
                )

        # ۲. نمایش برندهای معتبر خارجی / وارداتی
        imp_offers = report.get("imp_offers", [])
        if imp_offers:
            lines.append("🌍 <b>لاستیک‌های خارجی / وارداتی (کره، چین، ژاپن):</b>\n")
            # حداکثر ۳ مورد از برندهای برتر خارجی
            seen_foreign_brands = set()
            foreign_shown = 0
            for off in imp_offers:
                fb = off["brand"]
                if fb in seen_foreign_brands and foreign_shown >= 2:
                    continue
                seen_foreign_brands.add(fb)
                foreign_shown += 1
                yr_str = f" (تولید {off['year']})" if off.get("year") else ""
                pair_p = format_toman(off["pair_price_toman"])
                unit_p = format_toman(off["unit_price_toman"])
                shop = escape_html(off["shop_name"][:20])
                src = escape_html(off["source"])
                safe_url = html.escape(str(off.get("url") or ""), quote=True)

                lines.append(
                    f"🔹 <b>{escape_html(fb)}</b>{yr_str}:\n"
                    f"  ▫️ قیمت جفت (۲ حلقه): <b>{pair_p}</b> تومان\n"
                    f"  ▫️ قیمت هر حلقه: <b>{unit_p}</b> تومان\n"
                    f"  🏬 {src} ({shop}) — <a href=\"{safe_url}\">مشاهده و خرید آنلاین ↗️</a>\n"
                )
                if foreign_shown >= 3:
                    break

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("💡 <i>تمامی قیمت‌ها به صورت زنده از معتبرترین فروشگاه‌ها استخراج شده و قیمت قطعی جفت و تک‌حلقه کاملاً مشخص است.</i>")

        msg_text = "\n".join(lines)
        if len(msg_text) > 3950:
            msg_text = msg_text[:3900] + "\n..."

        if edit_msg_id:
            await self._safe_edit(chat_id, edit_msg_id, msg_text, reply_markup=kb)
        else:
            await self.bot.send_message(chat_id=chat_id, text=msg_text, reply_markup=kb)

    # =========================================================================
    # استعلام و نمایش فوق‌دقیق قیمت و خرید آنلاین انواع روغن موتور و گیربکس
    # =========================================================================
    async def _send_oil_price_report(
        self, chat_id: int, raw_grade: str, edit_msg_id: Optional[int] = None, force_refresh: bool = False
    ):
        grade = normalize_oil_grade(raw_grade) or raw_grade.upper()
        loading_txt = (
            f"🛢 <b>در حال استعلام قیمت و لینک خرید <code>{escape_html(grade)}</code>...</b>\n\n"
            "⏳ <i>دارم قیمت گالن‌های اصلی رو از دیجی‌کالا، ترب و باسلام استخراج می‌کنم...</i>"
        )
        if edit_msg_id:
            await self._safe_edit(chat_id, edit_msg_id, loading_txt)
        else:
            await self.bot.send_message(chat_id=chat_id, text=loading_txt)

        report = await self.sniper.oil_client.fetch_live_oil_prices(grade, force_refresh=force_refresh)
        kb = {
            "inline_keyboard": [
                [
                    {"text": "🔄 بروزرسانی قیمت", "callback_data": f"oilrefresh_{grade}"},
                    {"text": "🛢 دسته‌های روغن", "callback_data": "menu_oil_price"},
                ],
                [
                    {"text": "🚘 روغن مناسب خودروی من", "callback_data": "menu_car_picker"},
                    {"text": "🏠 منوی اصلی", "callback_data": "main_menu"},
                ],
            ]
        }

        if not report.get("ok") or report.get("total_found", 0) == 0:
            fail_txt = (
                f"⚠️ <b>پیشنهاد معتبری برای <code>{escape_html(grade)}</code> پیدا نشد!</b>\n\n"
                "💡 لطفاً از منوی زیر یکی از دسته‌ها رو انتخاب کن یا کد روغن (مثل <code>10W40</code> یا <code>20W50</code>) رو بفرست."
            )
            if edit_msg_id:
                await self._safe_edit(chat_id, edit_msg_id, fail_txt, reply_markup=kb)
            else:
                await self.bot.send_message(chat_id=chat_id, text=fail_txt, reply_markup=kb)
            return

        ts = report["timestamp"]
        title_fa = report.get("title_fa") or f"روغن موتور {report['grade']}"
        vol_label = report.get("target_volume_label") or "گالن استاندارد خودرو"

        lines: List[str] = [
            f"🛢 <b>قیمت روز و خرید آنلاین • {escape_html(title_fa)}</b>",
            f"📦 <b>بسته‌بندی:</b> <b>{escape_html(vol_label)}</b>",
            f"🕒 <b>استعلام لحظه‌ای:</b> {ts['full_fa']}",
            "━━━━━━━━━━━━━━━━━━━━\n",
        ]

        # ۱. برندهای شاخص ایرانی (بهران، ایرانول، اسپیدی، پارس، کاسپین)
        feat_ir = report.get("featured_ir_brands", {})
        if feat_ir:
            lines.append("🇮🇷 <b>روغن‌های باکیفیت و اصل ایرانی:</b>\n")
            for b_name, off in feat_ir.items():
                pr = format_toman(off["price_toman"])
                v_val = off.get("volume")
                v_txt = f"{int(v_val) if v_val and float(v_val).is_integer() else v_val} لیتری" if v_val else "۴ لیتری"
                src = escape_html(off["source"])
                shop = escape_html(off["shop_name"][:20])
                safe_u = html.escape(str(off.get("url") or ""), quote=True)
                title_clean = escape_html(off["title"][:55])

                lines.append(
                    f"🔹 <b>{escape_html(b_name)}</b> ({v_txt}):\n"
                    f"  ▫️ {title_clean}\n"
                    f"  💰 قیمت قطعی: <b>{pr}</b> تومان\n"
                    f"  🛒 {src} ({shop}) — <a href=\"{safe_u}\">خرید اینترنتی ↗️</a>\n"
                )

        # ۲. برندهای معتبر خارجی (کاسترول، توتال، لیکومولی، شل)
        feat_imp = report.get("featured_imp_brands", {})
        if feat_imp:
            lines.append("🌍 <b>برندهای معتبر خارجی / وارداتی (اصل):</b>\n")
            for b_name, off in feat_imp.items():
                pr = format_toman(off["price_toman"])
                v_val = off.get("volume")
                v_txt = f"{int(v_val) if v_val and float(v_val).is_integer() else v_val} لیتری" if v_val else "۴ لیتری"
                src = escape_html(off["source"])
                shop = escape_html(off["shop_name"][:20])
                safe_u = html.escape(str(off.get("url") or ""), quote=True)
                title_clean = escape_html(off["title"][:55])

                lines.append(
                    f"🔹 <b>{escape_html(b_name)}</b> ({v_txt}):\n"
                    f"  ▫️ {title_clean}\n"
                    f"  💰 قیمت: <b>{pr}</b> تومان\n"
                    f"  🛒 {src} ({shop}) — <a href=\"{safe_u}\">خرید اینترنتی ↗️</a>\n"
                )

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("🛍 <i>برای سفارش مستقیم هر روغن، روی دکمه «خرید اینترنتی» آن بزنید.</i>")

        msg_text = "\n".join(lines)
        if len(msg_text) > 3950:
            msg_text = msg_text[:3900] + "\n..."

        if edit_msg_id:
            await self._safe_edit(chat_id, edit_msg_id, msg_text, reply_markup=kb)
        else:
            await self.bot.send_message(chat_id=chat_id, text=msg_text, reply_markup=kb)

    # =========================================================================
    # مقایسه سود خرید دولتی نسبت به بازار آزاد
    # =========================================================================
    async def _send_gov_vs_market_comparison(
        self, chat_id: int, raw_size: str, tire_count: int = 2, edit_msg_id: Optional[int] = None
    ):
        norm = normalize_tire_size(raw_size) or key_to_size(raw_size)
        sk = size_to_key(norm)
        loading = (
            f"⚖️ <b>در حال محاسبه دقیق سود خرید دولتی برای <code>{escape_html(norm)}</code>...</b>\n\n"
            "⏳ <i>دارم نرخ مصوب دولتی رو با کف قیمت امروز بازار آزاد مقایسه می‌کنم...</i>"
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
            "⚖️ <b>مقایسه شفاف قیمت دولتی و بازار آزاد</b>",
            f"🛞 <b>سایز:</b> <code>{escape_html(self._format_size_label(norm))}</code>  •  🕒 <i>{now_fa}</i>",
            "━━━━━━━━━━━━━━━━━━━━\n",
        ]

        if ir_sum:
            mkt_min = ir_sum["min_unit"]
            lines.append("💰 <b>قیمت در بازار آزاد:</b>")
            lines.append(f"  ▫️ یک جفت (۲ حلقه): <b>{format_toman(mkt_min * 2)}</b> تومان")
            lines.append(f"  ▫️ هر یک حلقه: <b>{format_toman(mkt_min)}</b> تومان\n")
        else:
            mkt_min = 4_000_000
            lines.append("💰 <b>قیمت تقریبی بازار آزاد:</b> حدود ۸ تا ۱۰ میلیون تومان برای یک جفت\n")

        if avail_bucket and avail_bucket.get("min_price_toman"):
            gov_p = int(avail_bucket["min_price_toman"])
            portals_txt = "، ".join(avail_bucket.get("portals", []))
            lines.append(f"🏛 <b>قیمت کارخانه دولتی (هم‌اکنون موجود در {escape_html(portals_txt)}):</b>")
            lines.append(f"  ▫️ هر حلقه فقط: <b>{format_toman(gov_p)}</b> تومان\n")
            if mkt_min > gov_p:
                save_1 = mkt_min - gov_p
                lines.append("💎 <b>سود خالص شما با خرید دولتی:</b>")
                lines.append(f"  🎉 روی هر جفت (۲ حلقه): <b>{format_toman(save_1 * 2)}</b> تومان پس‌انداز می‌کنی!")
                lines.append(f"  🎉 روی ۴ حلقه: <b>{format_toman(save_1 * 4)}</b> تومان به نفعت تموم میشه!")
        else:
            lines.append("🏛 <b>انبار دولتی:</b> ⚪ <i>در این لحظه موجودی خالی است و منتظر شارژ روزانه هستیم.</i>\n")
            # برآورد تخمینی
            est_gov_pair = int((mkt_min * 2) * 0.45)
            est_profit = max(0, (mkt_min * 2) - est_gov_pair)
            lines.append(
                f"💡 <b>چقدر سود داره؟</b>\n"
                f"معمولاً تایر دولتی این سایز جفتی حدود <b>{format_toman(est_gov_pair)}</b> تومان پای شما میفته، یعنی با خرید دولتی حداقل <b>{format_toman(est_profit)}</b> تومان سود می‌کنی!"
            )
            lines.append("\n⚡ <i>اگر «شکارچی خودکار» رو روشن کنی، به محض شارژ اولین نفر باخبر میشی.</i>")

        kb = {
            "inline_keyboard": [
                [
                    {"text": "📦 موجودی انبار دولتی", "callback_data": "live_check_stock"},
                    {"text": "💰 لیست قیمت‌های بازار", "callback_data": f"mkt_{sk}"},
                ],
                [
                    {"text": "⚡ روشن کردن شکارچی", "callback_data": "menu_sniper"},
                    {"text": "🚘 ماشین دیگر", "callback_data": "menu_car_picker"},
                ],
                [{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}],
            ]
        }
        if edit_msg_id:
            await self._safe_edit(chat_id, edit_msg_id, "\n".join(lines), reply_markup=kb)
        else:
            await self.bot.send_message(chat_id=chat_id, text="\n".join(lines), reply_markup=kb)

    # =========================================================================
    # هندلر استارت
    # =========================================================================
    async def handle_start(self, chat_id: int, username: str = ""):
        user = await get_user(chat_id)
        if not user:
            user = await upsert_user(chat_id, username=username)
        await set_state(chat_id, "IDLE")

        text = self._build_dashboard_text(user, "دستیار هوشمند تایر دولتی و قیمت روز")
        await self.bot.send_message(chat_id=chat_id, text=text, reply_markup=self.get_main_keyboard(user))

    # =========================================================================
    # مسیریابی دکمه‌ها (Callback Queries)
    # =========================================================================
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

        # پاک‌سازی خودکار وضعیت تایپ قبلی در صورت زدن دکمه‌های منو
        if user.get("state", "IDLE") != "IDLE" and not (
            data.startswith("edit_")
            or data in ("ask_custom_market_size", "ask_custom_oil_grade", "ask_support_msg")
            or data.startswith("admin_reply_")
            or data.startswith("otp_send_")
        ):
            await set_state(chat_id, "IDLE")
            user["state"] = "IDLE"

        # ---------------------------------------------------------------------
        # منوی اصلی
        # ---------------------------------------------------------------------
        if data == "main_menu":
            await set_state(chat_id, "IDLE")
            text = self._build_dashboard_text(user, "دستیار هوشمند تایر دولتی و قیمت روز")
            await self._safe_edit(chat_id, message_id, text, reply_markup=self.get_main_keyboard(user))

        # ---------------------------------------------------------------------
        # منوی مشخصات مالک خودرو
        # ---------------------------------------------------------------------
        elif data == "menu_profile":
            pct, _ = self.calculate_profile_completion(user)
            n_val = user.get("national_id") or "ثبت نشده"
            m_val = user.get("mobile") or "ثبت نشده"
            n_ic = "✅" if user.get("national_id") else "⚠️"
            m_ic = "✅" if user.get("mobile") else "⚠️"

            text = (
                "👤 <b>اطلاعات مالک خودرو</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "برای دریافت لاستیک دولتی فقط داشتن همین ۲ مورد کافیه:\n\n"
                f"🆔 <b>کد ملی مالک:</b> <code>{n_val}</code> {n_ic}\n"
                f"📱 <b>موبایل مالک:</b> <code>{m_val}</code> {m_ic}\n\n"
                "💡 <i>چرا اطلاعات دیگه رو نمی‌پرسیم؟</i>\n"
                "چون برای ثبت‌نام اولیه فقط کد ملی و موبایل صاحب سند لازمه و بقیه اطلاعات (مثل کارت ماشین و آدرس) موقع نهایی شدن خرید در خود سایت کارخانه وارد میشه.\n\n"
                "👇 برای ثبت یا ویرایش روی دکمه‌های زیر بزن:"
            )
            rows = [
                [
                    {"text": f"🆔 ثبت کد ملی {n_ic}", "callback_data": "edit_national_id"},
                    {"text": f"📱 ثبت شماره موبایل {m_ic}", "callback_data": "edit_mobile"},
                ],
            ]
            if pct == 100:
                rows.append([{"text": "⚡ شکارچی خودکار تایر دولتی", "callback_data": "menu_sniper"}])
            rows.append([{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}])
            await self._safe_edit(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data.startswith("edit_"):
            field = data.replace("edit_", "")
            prompts = {
                "national_id": (
                    "AWAIT_NAT_ID",
                    "🆔 <b>ثبت کد ملی مالک خودرو</b>\n\n"
                    "لطفاً کد ملی <b>۱۰ رقمی</b> صاحب سند خودرو را بدون خط تیره بنویس و بفرست:\n"
                    "📌 <i>مثال:</i> <code>0012345678</code>",
                ),
                "mobile": (
                    "AWAIT_MOBILE",
                    "📱 <b>ثبت شماره موبایل مالک خودرو</b>\n\n"
                    "لطفاً شماره همراه <b>۱۱ رقمی</b> مالک را بفرستید (حتماً سیم‌کارت باید به نام دارنده کد ملی باشد):\n"
                    "📌 <i>مثال:</i> <code>09123456789</code>",
                ),
            }
            if field in prompts:
                st, msg = prompts[field]
                await set_state(chat_id, st)
                kb = {"inline_keyboard": [[{"text": "🔙 انصراف و بازگشت", "callback_data": "menu_profile"}]]}
                await self._safe_edit(chat_id, message_id, msg, reply_markup=kb)

        # ---------------------------------------------------------------------
        # منوی انتخاب کارخانه‌ها
        # ---------------------------------------------------------------------
        elif data == "menu_portal":
            cur_p = user.get("target_portal", "all")
            rows: List[List[Dict[str, str]]] = [
                [{
                    "text": ("🟢 " if cur_p == "all" else "⚪ ") + "🌐 همه کارخانه‌ها با هم (پیشنهادی ⭐)",
                    "callback_data": "set_portal_all",
                }]
            ]
            factory_keys = ["barez", "kavir", "yazd", "irantire", "hypertire", "razi", "dena", "artawheel"]
            for i in range(0, len(factory_keys), 2):
                pair_btns = []
                for pk in factory_keys[i : i + 2]:
                    mark = "🟢 " if pk == cur_p else "⚪ "
                    pair_btns.append({"text": f"{mark}{PORTALS[pk]['short']}", "callback_data": f"set_portal_{pk}"})
                rows.append(pair_btns)

            rows.append([{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}])
            cur_info = PORTALS.get(cur_p, PORTALS["all"])
            text = (
                "🏭 <b>انتخاب کارخانه فروش تایر دولتی</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🎯 <b>انتخاب فعلی شما:</b> <code>{escape_html(cur_info['title'])}</code>\n\n"
                "⭐ <b>پیشنهاد ما:</b> گزینه <b>«همه کارخانه‌ها با هم»</b> رو انتخاب کن تا ربات به محض شارژ شدن هر کدوم از شرکت‌های بارز، کویر، یزد، ایران‌تایر و هایپرتایر فوراً بهت خبر بده!\n\n"
                "👇 کارخانه مورد نظرت رو انتخاب کن:"
            )
            await self._safe_edit(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data.startswith("set_portal_"):
            p = data.replace("set_portal_", "")
            if p in PORTALS:
                await upsert_user(chat_id, target_portal=p)
            await self._route_callback(chat_id, message_id, "menu_portal")

        # ---------------------------------------------------------------------
        # منوی شکارچی خودکار
        # ---------------------------------------------------------------------
        elif data in ("menu_sniper", "toggle_sniper"):
            is_on = bool(user.get("sniper_enabled", 0))
            if data == "toggle_sniper":
                if is_on:
                    await upsert_user(chat_id, sniper_enabled=0)
                    user["sniper_enabled"] = 0
                else:
                    pct, _ = self.calculate_profile_completion(user)
                    if pct < 100:
                        kb = {
                            "inline_keyboard": [
                                [{"text": "👤 ثبت مشخصات مالک", "callback_data": "menu_profile"}],
                                [{"text": "🔙 بازگشت", "callback_data": "menu_sniper"}],
                            ]
                        }
                        await self._safe_edit(
                            chat_id,
                            message_id,
                            "⚠️ <b>ابتدا مشخصات مالک را ثبت کنید!</b>\n\nبرای اینکه هنگام شارژ تایر بتوانید سریع خرید کنید، ثبت کد ملی و شماره موبایل الزامی است.",
                            reply_markup=kb,
                        )
                        return
                    await upsert_user(chat_id, sniper_enabled=1)
                    user["sniper_enabled"] = 1
                is_on = bool(user.get("sniper_enabled", 0))

            cur_size = key_to_size(user.get("target_tire_size", "185_65_14"))
            pct, _ = self.calculate_profile_completion(user)

            if is_on:
                status_txt = "🟢 <b>شکارچی هم‌اکنون روشن و فعال است!</b>\nربات هر چند ثانیه سایت‌های تایر دولتی را اسکن می‌کند و به محض باز شدن سهمیه، مستقیماً به شما پیام می‌دهد."
                toggle_btn = {"text": "🔴 خاموش کردن شکارچی", "callback_data": "toggle_sniper_off"}
            else:
                status_txt = "⚪ <b>شکارچی در حال حاضر خاموش است.</b>\nاگر روشنش کنی، لازم نیست مدام به سایت‌ها سر بزنی؛ به محض موجود شدن لاستیک، ربات توی بله خبرت می‌کنه!"
                toggle_btn = {"text": "🟢 روشن کردن شکارچی خودکار ⚡", "callback_data": "toggle_sniper_on"}

            text = (
                "🛰 <b>شکارچی خودکار تایر دولتی</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{status_txt}\n\n"
                f"🛞 <b>سایز تحت رصد:</b> <code>{escape_html(cur_size)}</code>\n"
                f"📦 <b>تعداد درخواستی:</b> <b>{user.get('tire_count', 2)} حلقه</b>\n\n"
                "👇 با دکمه‌های زیر می‌تونی وضعیت شکارچی رو تغییر بدی:"
            )
            rows = [
                [toggle_btn],
                [
                    {"text": "🛞 تغییر سایز تایر", "callback_data": "menu_size"},
                    {"text": "📦 تغییر تعداد (۲ یا ۴ حلقه)", "callback_data": "menu_tire_count"},
                ],
                [{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}],
            ]
            await self._safe_edit(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data == "toggle_sniper_on":
            pct, _ = self.calculate_profile_completion(user)
            if pct < 100:
                kb = {
                    "inline_keyboard": [
                        [{"text": "👤 ثبت مشخصات مالک", "callback_data": "menu_profile"}],
                        [{"text": "🔙 بازگشت", "callback_data": "menu_sniper"}],
                    ]
                }
                await self._safe_edit(
                    chat_id,
                    message_id,
                    "⚠️ <b>ابتدا مشخصات مالک را ثبت کنید!</b>\n\nبرای اینکه هنگام شارژ تایر بتوانید سریع خرید کنید، ثبت کد ملی و شماره موبایل الزامی است.",
                    reply_markup=kb,
                )
                return
            await upsert_user(chat_id, sniper_enabled=1)
            await self._route_callback(chat_id, message_id, "menu_sniper")

        elif data == "toggle_sniper_off":
            await upsert_user(chat_id, sniper_enabled=0)
            await self._route_callback(chat_id, message_id, "menu_sniper")

        elif data == "menu_tire_count":
            cur_cnt = user.get("tire_count", 2)
            c2_mark = "🟢 " if cur_cnt == 2 else "⚪ "
            c4_mark = "🟢 " if cur_cnt == 4 else "⚪ "
            text = (
                "📦 <b>انتخاب تعداد حلقه درخواستی</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "سهمیه سالانه هر خودرو حداکثر ۴ حلقه تایر است:\n"
                "▫️ <b>۲ حلقه:</b> برای تعویض لاستیک‌های جلو یا عقب\n"
                "▫️ <b>۴ حلقه:</b> تعویض کامل زیربندی خودرو\n\n"
                "👇 تعداد مورد نظرتان را انتخاب کنید:"
            )
            kb = {
                "inline_keyboard": [
                    [
                        {"text": f"{c2_mark}۲ حلقه (یک جفت)", "callback_data": "set_count_2"},
                        {"text": f"{c4_mark}۴ حلقه (یک دست)", "callback_data": "set_count_4"},
                    ],
                    [{"text": "🔙 بازگشت به شکارچی", "callback_data": "menu_sniper"}],
                ]
            }
            await self._safe_edit(chat_id, message_id, text, reply_markup=kb)

        elif data in ("set_count_2", "set_count_4"):
            cnt = 2 if data == "set_count_2" else 4
            await upsert_user(chat_id, tire_count=cnt)
            await self._route_callback(chat_id, message_id, "menu_sniper")

        # ---------------------------------------------------------------------
        # بررسی زنده موجودی انبار دولتی
        # ---------------------------------------------------------------------
        elif data == "live_check_stock":
            cur_sz = user.get("target_tire_size", "185_65_14")
            norm = key_to_size(cur_sz)
            await self._safe_edit(
                chat_id,
                message_id,
                f"📦 <b>در حال بررسی انبار تمام کارخانه‌های دولتی برای سایز <code>{escape_html(norm)}</code>...</b>\n\n⏳ <i>لطفاً چند لحظه صبر کنید...</i>",
            )
            scan = await self.sniper.scan_all_portals_live("all")
            now_fa = get_tehran_now()["compact_fa"]
            avail_bucket = scan.get("available_sizes", {}).get(cur_sz)

            if avail_bucket and avail_bucket.get("in_stock_items"):
                items = avail_bucket["in_stock_items"]
                lines = [
                    f"🎉 <b>خبر خوب! لاستیک دولتی سایز <code>{escape_html(norm)}</code> هم‌اکنون موجود است!</b>",
                    f"🕒 <i>{now_fa}</i>",
                    "━━━━━━━━━━━━━━━━━━━━\n",
                ]
                for it in items[:4]:
                    pr_t = format_toman(it.get("price_toman", 0))
                    p_name = escape_html(it.get("portal_title", "کارخانه دولتی"))
                    safe_url = html.escape(str(it.get("url") or ""), quote=True)
                    lines.append(
                        f"🔹 <b>{escape_html(it.get('brand', 'تایر دولتی'))}</b> (تولید {it.get('year', '۱۴۰۴')}):\n"
                        f"  ▫️ قیمت دولتی: <b>{pr_t}</b> تومان\n"
                        f"  🏭 سامانه: <b>{p_name}</b> — <a href=\"{safe_url}\">ورود به صفحه خرید ↗️</a>\n"
                    )
                lines.append("⚡ <i>به دلیل محدودیت سهمیه، سریع‌تر برای ثبت سفارش اقدام کنید.</i>")
            else:
                lines = [
                    f"📦 <b>وضعیت انبار دولتی • سایز <code>{escape_html(norm)}</code></b>",
                    f"🕒 <i>{now_fa}</i>",
                    "━━━━━━━━━━━━━━━━━━━━\n",
                    "⚪ <b>در این لحظه سهمیه دولتی این سایز ناموجود است.</b>\n",
                    "⏰ <b>ساعات معمول شارژ سایت‌ها:</b>\n"
                    "▫️ بارز: شنبه تا چهارشنبه ساعت ۱۰:۰۰ صبح\n"
                    "▫️ کویر تایر: روزهای کاری ساعت ۱۱:۰۰\n"
                    "▫️ هایپرتایر: ساعات نامشخص در طول روز\n\n"
                    "💡 <b>پیشنهاد:</b> شکارچی خودکار را روشن بگذارید تا به محض باز شدن سهمیه، ربات به شما پیام دهد.",
                ]

            kb = {
                "inline_keyboard": [
                    [
                        {"text": "🔄 بررسی مجدد", "callback_data": "live_check_stock"},
                        {"text": "💰 دیدن قیمت‌های آزاد", "callback_data": f"mkt_{cur_sz}"},
                    ],
                    [
                        {"text": "⚡ روشن کردن شکارچی", "callback_data": "menu_sniper"},
                        {"text": "🛞 تغییر سایز", "callback_data": "menu_size"},
                    ],
                    [{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}],
                ]
            }
            await self._safe_edit(chat_id, message_id, "\n".join(lines), reply_markup=kb)

        # ---------------------------------------------------------------------
        # منوی انتخاب سایز تایر
        # ---------------------------------------------------------------------
        elif data == "menu_size":
            cur_sz = user.get("target_tire_size", "185_65_14")
            rows = []
            for cat_id, cat_info in TIRE_SIZE_CATEGORIES.items():
                rows.append([{"text": f"📁 {cat_info['title']}", "callback_data": f"cat_{cat_id}"}])
            rows.append([
                {"text": "🚘 انتخاب با اسم ماشین", "callback_data": "menu_car_picker"},
                {"text": "✍️ تایپ دستی سایز", "callback_data": "ask_custom_market_size"},
            ])
            rows.append([{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}])

            text = (
                "🛞 <b>انتخاب سایز لاستیک خودرو</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🎯 <b>سایز فعلی شما:</b> <code>{escape_html(self._format_size_label(cur_sz))}</code>\n\n"
                "سایز لاستیک روی دیواره چرخ نوشته شده (مثلاً <code>185/65R14</code>).\n"
                "👇 از دسته‌های زیر رینگ ماشینت رو انتخاب کن یا روی «انتخاب با اسم ماشین» بزن:"
            )
            await self._safe_edit(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data.startswith("cat_"):
            cid = data.replace("cat_", "")
            cat = TIRE_SIZE_CATEGORIES.get(cid)
            if not cat:
                await self._route_callback(chat_id, message_id, "menu_size")
                return
            rows = []
            cur_sz = user.get("target_tire_size", "185_65_14")
            for sk, s_label in cat["sizes"]:
                mark = "🟢 " if sk == cur_sz else "⚪ "
                hint = CAR_HINT_FOR_SIZE.get(s_label, "")
                hint_txt = f" • {hint}" if hint else ""
                rows.append([{"text": f"{mark}{s_label}{hint_txt}", "callback_data": f"set_size_{sk}"}])
            rows.append([
                {"text": "🔙 بازگشت به دسته‌ها", "callback_data": "menu_size"},
                {"text": "🏠 منوی اصلی", "callback_data": "main_menu"},
            ])
            text = (
                f"<b>{escape_html(cat['title'])}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "👇 سایز دقیق مورد نظرت رو لمس کن تا ثبت بشه:"
            )
            await self._safe_edit(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data.startswith("set_size_"):
            sk = data.replace("set_size_", "")
            norm = key_to_size(sk)
            await upsert_user(chat_id, target_tire_size=sk)
            user["target_tire_size"] = sk
            kb = {
                "inline_keyboard": [
                    [
                        {"text": "💰 دیدن قیمت روز بازار", "callback_data": f"mkt_{sk}"},
                        {"text": "📦 موجودی انبار دولتی", "callback_data": "live_check_stock"},
                    ],
                    [
                        {"text": "⚡ شکارچی خودکار", "callback_data": "menu_sniper"},
                        {"text": "🏠 منوی اصلی", "callback_data": "main_menu"},
                    ],
                ]
            }
            await self._safe_edit(
                chat_id,
                message_id,
                f"✅ <b>سایز با موفقیت به <code>{escape_html(norm)}</code> تغییر یافت!</b>\n\nحالا می‌تونی قیمت زنده بازار رو ببینی یا شکارچی دولتی رو روشن کنی.",
                reply_markup=kb,
            )

        elif data == "ask_custom_market_size":
            await set_state(chat_id, "AWAIT_TIRE_SIZE")
            kb = {"inline_keyboard": [[{"text": "🔙 انصراف و بازگشت", "callback_data": "menu_size"}]]}
            await self._safe_edit(
                chat_id,
                message_id,
                (
                    "✍️ <b>تایپ سایز لاستیک خودرو</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    "سایز چرخ ماشینت رو انگلیسی یا فارسی بنویس و بفرست:\n"
                    "📌 <i>مثال‌ها:</i>\n"
                    "▫️ <code>185/65R14</code> (پژو / رانا)\n"
                    "▫️ <code>165/65R13</code> (پراید)\n"
                    "▫️ <code>185/65R15</code> (سمند / ال۹۰)\n"
                    "▫️ <code>205/55R16</code> (دنا پلاس / مگان)"
                ),
                reply_markup=kb,
            )

        # ---------------------------------------------------------------------
        # منوی قیمت روز تایر
        # ---------------------------------------------------------------------
        elif data == "menu_market_price":
            rows = []
            for cat_id, cat_info in TIRE_SIZE_CATEGORIES.items():
                rows.append([{"text": f"📁 {cat_info['title']}", "callback_data": f"mktcat_{cat_id}"}])
            rows.append([
                {"text": "🚘 انتخاب با اسم ماشین", "callback_data": "menu_car_picker"},
                {"text": "✍️ تایپ سایز دلخواه", "callback_data": "ask_custom_market_size"},
            ])
            rows.append([{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}])
            text = (
                "💰 <b>استعلام زنده قیمت روز تایر در بازار آزاد</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "🌐 اتصال لحظه‌ای به دیجی‌کالا، ترب و باسلام برای تمام سایزها و برندها (بارز، کویر، یزد، ایران‌تایر و خارجی).\n\n"
                "👇 رینگ یا دسته مورد نظرت رو انتخاب کن:"
            )
            await self._safe_edit(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data.startswith("mktcat_"):
            cid = data.replace("mktcat_", "")
            cat = TIRE_SIZE_CATEGORIES.get(cid)
            if not cat:
                await self._route_callback(chat_id, message_id, "menu_market_price")
                return
            rows = []
            for sk, s_label in cat["sizes"]:
                hint = CAR_HINT_FOR_SIZE.get(s_label, "")
                h_txt = f" ({hint})" if hint else ""
                rows.append([{"text": f"🛞 {s_label}{h_txt}", "callback_data": f"mkt_{sk}"}])
            rows.append([
                {"text": "🔙 بازگشت به دسته‌ها", "callback_data": "menu_market_price"},
                {"text": "🏠 منوی اصلی", "callback_data": "main_menu"},
            ])
            text = (
                f"<b>{escape_html(cat['title'])}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "👇 سایز مورد نظرت رو انتخاب کن تا قیمت‌های لحظه‌ای رو ببینی:"
            )
            await self._safe_edit(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data.startswith("mktrefresh_"):
            sk = data.replace("mktrefresh_", "")
            await self._send_market_price_report(chat_id, key_to_size(sk), edit_msg_id=message_id, force_refresh=True)

        elif data.startswith("mkt_"):
            sk = data.replace("mkt_", "")
            await self._send_market_price_report(chat_id, key_to_size(sk), edit_msg_id=message_id)

        # ---------------------------------------------------------------------
        # منوی خرید و قیمت انواع روغن خودرو
        # ---------------------------------------------------------------------
        elif data == "menu_oil_price":
            rows = []
            cat_items = list(OIL_CATEGORIES.items())
            for i in range(0, len(cat_items), 2):
                pair = []
                for ck, info in cat_items[i : i + 2]:
                    pair.append({"text": info["short"], "callback_data": f"oilcat_{ck}"})
                rows.append(pair)
            rows.append([
                {"text": "🚘 روغن مناسب ماشین من", "callback_data": "menu_car_picker"},
                {"text": "✍️ تایپ کد روغن", "callback_data": "ask_custom_oil_grade"},
            ])
            rows.append([{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}])

            now_fa = get_tehran_now()["compact_fa"]
            text = (
                "🛢 <b>خرید آنلاین و استعلام قیمت انواع روغن خودرو</b>\n"
                f"🕒 <i>امروز: {now_fa}</i>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "🌐 اتصال لحظه‌ای به دیجی‌کالا، ترب و باسلام برای ۲۹ نوع روغن مختلف با بسته‌بندی استاندارد:\n"
                "▫️ <b>روغن موتور سواری</b> (10W40, 20W50, 5W30, 0W20)\n"
                "▫️ <b>روغن دیزلی سنگین</b> (کامیون و خاور ۲۰ لیتری)\n"
                "▫️ <b>واسکازین دنده‌ای</b> (75W80, 85W90, 85W140)\n"
                "▫️ <b>گیربکس اتوماتیک</b> (CVT, ATF, DCT دوکلاچه)\n"
                "▫️ <b>هیدرولیک، ترمز DOT4 و ضدیخ</b>\n\n"
                "👇 دسته مورد نظرتان را لمس کنید:"
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
                "👇 مدل یا گرانروی دقیق را لمس کنید تا قیمت‌های زنده و لینک خرید مستقیم برایتان باز شود:"
            )
            await self._safe_edit(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data.startswith("oilrefresh_"):
            gr = data.replace("oilrefresh_", "")
            await self._send_oil_price_report(chat_id, gr, edit_msg_id=message_id, force_refresh=True)

        elif data.startswith("oil_"):
            gr = data.replace("oil_", "")
            await self._send_oil_price_report(chat_id, gr, edit_msg_id=message_id)

        elif data == "ask_custom_oil_grade":
            await set_state(chat_id, "AWAIT_OIL_GRADE")
            kb = {"inline_keyboard": [[{"text": "🔙 انصراف و بازگشت", "callback_data": "menu_oil_price"}]]}
            await self._safe_edit(
                chat_id,
                message_id,
                (
                    "✍️ <b>تایپ نام یا گرانروی روغن</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    "نوع روغن ماشینت رو بنویس و بفرست:\n"
                    "📌 <i>مثال‌ها:</i> <code>10W40</code> • <code>20W50</code> • <code>5W30</code> • <code>CVT</code> • <code>DOT4</code> • <code>هیدرولیک</code> • <code>ضدیخ</code>"
                ),
                reply_markup=kb,
            )

        # ---------------------------------------------------------------------
        # انتخاب هوشمند بر اساس مدل خودرو
        # ---------------------------------------------------------------------
        elif data == "menu_car_picker":
            rows = []
            car_items = list(CAR_TIRE_CATALOG.items())
            for i in range(0, len(car_items), 2):
                pair = []
                for ck, info in car_items[i : i + 2]:
                    pair.append({"text": f"🚘 {info['short']}", "callback_data": f"car_{ck}"})
                rows.append(pair)
            rows.append([{"text": "✍️ تایپ مستقیم سایز", "callback_data": "ask_custom_market_size"}])
            rows.append([{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}])
            text = (
                "🚘 <b>انتخاب هوشمند تایر بر اساس نام خودرو</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "لازم نیست سایز تایر ماشینت رو حفظ باشی!\n"
                "کافیه مدل ماشینت رو از زیر انتخاب کنی تا هم <b>سایز فابریک</b> و هم <b>سایز پهن اسپرت</b> همراه با قیمت روز و وضعیت دولتی برات باز بشه.\n\n"
                "👇 ماشینت چیه؟"
            )
            await self._safe_edit(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data.startswith("car_"):
            car_key = data.replace("car_", "")
            await self._send_car_recommendation(chat_id, car_key, edit_msg_id=message_id)

        # ---------------------------------------------------------------------
        # مقایسه دولتی و آزاد
        # ---------------------------------------------------------------------
        elif data == "compare_gov_market":
            cur_sz = user.get("target_tire_size", "185_65_14")
            await self._send_gov_vs_market_comparison(
                chat_id, cur_sz, tire_count=user.get("tire_count", 2), edit_msg_id=message_id
            )

        elif data.startswith("cmp_"):
            sk = data.replace("cmp_", "")
            await self._send_gov_vs_market_comparison(
                chat_id, key_to_size(sk), tire_count=user.get("tire_count", 2), edit_msg_id=message_id
            )

        # ---------------------------------------------------------------------
        # راهنمای ساده خرید
        # ---------------------------------------------------------------------
        elif data == "menu_guide":
            text = (
                "📖 <b>راهنمای خیلی ساده خرید تایر دولتی</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "۱️⃣ <b>سهمیه من چقدره؟</b>\n"
                "هر خودرو سالی ۴ حلقه تایر با نرخ دولتی سهمیه داره.\n\n"
                "۲️⃣ <b>چه مدارکی لازمه؟</b>\n"
                "فقط کد ملی و شماره موبایلی که به نام صاحب سند خودرو باشه. بقیه اطلاعات موقع تکمیل خرید در سایت کارخانه وارد میشه.\n\n"
                "۳️⃣ <b>چطور لاستیک دولتی بخرم؟</b>\n"
                "بهترین راه اینه که دکمه «شکارچی خودکار» ربات رو روشن بذاری. به محض اینکه هر کدوم از کارخونه‌ها سایتشون رو باز کنن، ربات فوراً توی بله پیام میده و با زدن روی لینک خرید، سفارشت رو ثبت می‌کنی."
            )
            kb = {
                "inline_keyboard": [
                    [{"text": "⚡ روشن کردن شکارچی", "callback_data": "menu_sniper"}],
                    [{"text": "🏠 بازگشت به منوی اصلی", "callback_data": "main_menu"}],
                ]
            }
            await self._safe_edit(chat_id, message_id, text, reply_markup=kb)

        # ---------------------------------------------------------------------
        # سیستم پشتیبانی و ارسال تیکت
        # ---------------------------------------------------------------------
        elif data == "menu_support":
            user_tickets = await get_user_tickets(chat_id, limit=3)
            now_fa = get_tehran_now()["compact_fa"]
            lines = [
                "🎧 <b>مرکز پشتیبانی و ارتباط با همکاران</b>",
                f"🕒 <i>{now_fa}</i>",
                "━━━━━━━━━━━━━━━━━━━━\n",
                "سلام دوست من! ما همیشه کنارت هستیم ❤️\n",
                "هر سوالی در مورد <b>خرید تایر دولتی</b>، <b>استعلام قیمت‌ها</b>، <b>روغن موتور</b> داری یا نیاز به راهنمایی داری، کافیه پیام بذاری تا خیلی سریع پاسخت رو بدیم.\n",
            ]
            if user_tickets:
                lines.append("📋 <b>آخرین پیام‌های شما:</b>")
                for tk in user_tickets:
                    st_fa = "✅ پاسخ داده شد" if tk["status"] == "ANSWERED" else "⏳ در حال بررسی"
                    lines.append(f"▫️ تیکت #{tk['id']} ({tk['created_at'][:10]}): {st_fa}")
                lines.append("")

            lines.append("👇 برای ارسال پیام روی دکمه زیر بزن:")
            kb = {
                "inline_keyboard": [
                    [{"text": "✍️ ارسال پیام جدید به پشتیبانی", "callback_data": "ask_support_msg"}],
                    [{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}],
                ]
            }
            await self._safe_edit(chat_id, message_id, "\n".join(lines), reply_markup=kb)

        elif data == "ask_support_msg":
            await set_state(chat_id, "AWAIT_SUPPORT_MSG")
            kb = {"inline_keyboard": [[{"text": "🔙 انصراف و بازگشت", "callback_data": "menu_support"}]]}
            await self._safe_edit(
                chat_id,
                message_id,
                (
                    "✍️ <b>ارسال پیام به پشتیبانی</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    "پیام، سوال یا مشکل خود را به صورت کامل تایپ کنید و بفرستید.\n"
                    "پیام شما مستقیماً به تیم مدیریت ارسال شده و پاسخ در همین چت برایتان فرستاده می‌شود."
                ),
                reply_markup=kb,
            )

        elif data.startswith("admin_reply_"):
            ticket_id_str = data.replace("admin_reply_", "")
            if chat_id != ADMIN_CHAT_ID:
                return
            await set_state(chat_id, f"AWAIT_ADMIN_REPLY_{ticket_id_str}")
            kb = {"inline_keyboard": [[{"text": "🔙 انصراف", "callback_data": "main_menu"}]]}
            await self._safe_edit(
                chat_id,
                message_id,
                f"✍️ <b>پاسخ به تیکت #{ticket_id_str}:</b>\n\nمتن پاسخ خود را برای کاربر بفرستید:",
                reply_markup=kb,
            )

    # =========================================================================
    # نمایش پیشنهاد تایر بر اساس مدل خودرو
    # =========================================================================
    async def _send_car_recommendation(self, chat_id: int, car_key: str, edit_msg_id: Optional[int] = None):
        car_info = CAR_TIRE_CATALOG.get(car_key)
        if not car_info:
            await self._route_callback(chat_id, edit_msg_id, "menu_car_picker")
            return

        name = car_info["name"]
        std_sz = car_info.get("standard") or car_info.get("oem_size_label") or "185/65R14"
        wide_sz = car_info.get("wide") or car_info.get("wide_size_label")
        oil_gr = car_info.get("oil_grade")
        oil_note = car_info.get("oil_note")

        std_key = size_to_key(std_sz)
        wide_key = size_to_key(wide_sz) if wide_sz else None

        lines = [
            f"🚘 <b>مشخصات تایر و روغن مناسب برای {escape_html(name)}</b>",
            "━━━━━━━━━━━━━━━━━━━━\n",
            f"🛞 <b>سایز فابریک کارخانه:</b> <code>{escape_html(std_sz)}</code>",
        ]
        if wide_sz:
            lines.append(f"🛞 <b>سایز پهن و اسپرت:</b> <code>{escape_html(wide_sz)}</code> (چسبندگی و ترمز بهتر)")
        if oil_note:
            lines.append(f"\n🛢 <b>روغن موتور پیشنهادی:</b> <code>{escape_html(oil_note)}</code>")

        lines.append("\n👇 برای دیدن قیمت لحظه‌ای و خرید، روی گزینه مورد نظرت بزن:")
        rows = [[{"text": f"🛞 قیمت سایز فابریک ({std_sz})", "callback_data": f"mkt_{std_key}"}]]
        if wide_sz and wide_key:
            rows.append([{"text": f"🛞 قیمت سایز پهن ({wide_sz})", "callback_data": f"mkt_{wide_key}"}])
        if oil_gr:
            rows.append([{"text": f"🛢 قیمت روغن موتور ({oil_gr})", "callback_data": f"oil_{oil_gr}"}])
        rows.append([
            {"text": "🔙 انتخاب خودروی دیگر", "callback_data": "menu_car_picker"},
            {"text": "🏠 منوی اصلی", "callback_data": "main_menu"},
        ])
        if edit_msg_id:
            await self._safe_edit(chat_id, edit_msg_id, "\n".join(lines), reply_markup={"inline_keyboard": rows})
        else:
            await self.bot.send_message(chat_id=chat_id, text="\n".join(lines), reply_markup={"inline_keyboard": rows})

    # =========================================================================
    # هندلر پیام‌های متنی کاربر
    # =========================================================================
    async def handle_message(self, message: Dict[str, Any]):
        chat_id = message.get("chat", {}).get("id")
        text = (message.get("text") or "").strip()
        username = message.get("from", {}).get("username", "")

        if not chat_id or not text:
            return

        user = await get_user(chat_id)
        if not user:
            user = await upsert_user(chat_id, username=username)

        # دستورات اصلی
        if text == "/start":
            await self.handle_start(chat_id, username)
            return
        if text in ("/help", "راهنما"):
            await self._route_callback(chat_id, None, "menu_guide")
            return
        if text in ("/menu", "منو"):
            await self._route_callback(chat_id, None, "main_menu")
            return
        if text == "/sniper":
            await self._route_callback(chat_id, None, "menu_sniper")
            return
        if text == "/profile":
            await self._route_callback(chat_id, None, "menu_profile")
            return
        if text == "/car":
            await self._route_callback(chat_id, None, "menu_car_picker")
            return
        if text == "/oil":
            await self._route_callback(chat_id, None, "menu_oil_price")
            return
        if text == "/support":
            await self._route_callback(chat_id, None, "menu_support")
            return
        if text in ("/compare", "/cmp"):
            await self._route_callback(chat_id, None, "compare_gov_market")
            return

        state = user.get("state", "IDLE")

        # ثبت کد ملی
        if state == "AWAIT_NAT_ID":
            cleaned = re.sub(r"\D", "", persian_to_english_digits(text))
            if is_valid_iran_national_id(cleaned):
                await upsert_user(chat_id, national_id=cleaned)
                await set_state(chat_id, "AWAIT_MOBILE")
                kb = {"inline_keyboard": [[{"text": "👤 بازگشت به مشخصات مالک", "callback_data": "menu_profile"}]]}
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"✅ <b>کد ملی <code>{cleaned}</code> با موفقیت ثبت شد!</b>\n\n"
                        "📱 حالا لطفاً <b>شماره موبایل</b> مالک خودرو (۱۱ رقمی به نام صاحب کد ملی) را بفرستید:\n"
                        "📌 <i>مثال:</i> <code>09123456789</code>"
                    ),
                    reply_markup=kb,
                )
            else:
                kb = {"inline_keyboard": [[{"text": "🔙 انصراف", "callback_data": "menu_profile"}]]}
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="❌ <b>کد ملی وارد شده نامعتبر است!</b>\n\nلطفاً یک کد ملی ۱۰ رقمی صحیح و بدون خط تیره بفرستید.",
                    reply_markup=kb,
                )
            return

        # ثبت موبایل
        if state == "AWAIT_MOBILE":
            cleaned = re.sub(r"\D", "", persian_to_english_digits(text))
            if len(cleaned) == 11 and cleaned.startswith("09"):
                await upsert_user(chat_id, mobile=cleaned)
                await set_state(chat_id, "IDLE")
                kb = {"inline_keyboard": [[{"text": "👤 بازگشت به مشخصات مالک", "callback_data": "menu_profile"}]]}
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ <b>شماره موبایل <code>{cleaned}</code> با موفقیت ثبت شد!</b>",
                    reply_markup=kb,
                )
            else:
                kb = {"inline_keyboard": [[{"text": "🔙 انصراف", "callback_data": "menu_profile"}]]}
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="❌ <b>شماره موبایل نامعتبر است!</b>\n\nشماره باید ۱۱ رقمی و با ۰۹ شروع شود (مثل <code>09123456789</code>).",
                    reply_markup=kb,
                )
            return

        # ارسال پیام به پشتیبانی
        if state == "AWAIT_SUPPORT_MSG":
            await set_state(chat_id, "IDLE")
            ticket_id = await create_support_ticket(
                chat_id,
                username or "",
                user.get("national_id") or "",
                user.get("mobile") or "",
                text,
            )
            kb = {"inline_keyboard": [[{"text": "🏠 بازگشت به منوی اصلی", "callback_data": "main_menu"}]]}
            await self.bot.send_message(
                chat_id=chat_id,
                text=f"✅ <b>پیام شما دریافت شد (تیکت #{ticket_id})</b>\n\nتیم پشتیبانی به زودی پیام شما را بررسی کرده و پاسخ در همین چت برایتان ارسال می‌شود. با تشکر از شکیبایی شما ❤️",
                reply_markup=kb,
            )
            # فوروارد به ادمین
            if ADMIN_CHAT_ID:
                try:
                    admin_kb = {
                        "inline_keyboard": [
                            [{"text": f"✍️ پاسخ به کاربر", "callback_data": f"admin_reply_{ticket_id}"}]
                        ]
                    }
                    admin_txt = (
                        f"📩 <b>تیکت جدید پشتیبانی #{ticket_id}</b>\n"
                        f"👤 <b>کاربر:</b> @{username} (شناسه: <code>{chat_id}</code>)\n"
                        f"💬 <b>پیام:</b>\n{escape_html(text)}"
                    )
                    await self.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_txt, reply_markup=admin_kb)
                except Exception as e:
                    logger.warning(f"Admin notify error: {e}")
            return

        # پاسخ ادمین به تیکت
        if state.startswith("AWAIT_ADMIN_REPLY_"):
            ticket_id_str = state.replace("AWAIT_ADMIN_REPLY_", "")
            await set_state(chat_id, "IDLE")
            try:
                ticket_id = int(ticket_id_str)
                tk = await get_ticket(ticket_id)
                if tk:
                    await reply_support_ticket(ticket_id, text)
                    u_chat = tk.get("chat_id") or tk.get("user_chat_id")
                    user_reply_txt = (
                        f"💌 <b>پاسخ جدید از پشتیبانی (تیکت #{ticket_id})</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"{escape_html(text)}\n\n"
                        "<i>اگر سوال دیگری دارید، خوشحال می‌شویم در بخش پشتیبانی مطرح کنید.</i>"
                    )
                    await self.bot.send_message(chat_id=u_chat, text=user_reply_txt)
                    await self.bot.send_message(chat_id=chat_id, text=f"✅ پاسخ با موفقیت برای کاربر ارسال شد.")
            except Exception as e:
                logger.error(f"Error sending admin reply: {e}")
                await self.bot.send_message(chat_id=chat_id, text=f"❌ خطا در ارسال پاسخ: {e}")
            return

        # تایپ دستی سایز یا روغن یا نام خودرو در چت آزاد
        # ۱. بررسی سایز تایر
        parsed_size = normalize_tire_size(text)
        if parsed_size:
            await set_state(chat_id, "IDLE")
            await self._send_market_price_report(chat_id, parsed_size)
            return

        # ۲. بررسی روغن موتور
        parsed_oil = normalize_oil_grade(text)
        if parsed_oil:
            await set_state(chat_id, "IDLE")
            await self._send_oil_price_report(chat_id, parsed_oil)
            return

        # ۳. بررسی نام خودرو
        car_key = detect_car_from_text(text, CAR_TIRE_CATALOG)
        if car_key:
            await set_state(chat_id, "IDLE")
            await self._send_car_recommendation(chat_id, car_key)
            return

        # در غیر این صورت منوی اصلی با راهنمایی
        await set_state(chat_id, "IDLE")
        unknown_txt = (
            "متوجه پیامت نشدم دوست من! 😊\n\n"
            "می‌تونی از دکمه‌های زیر استفاده کنی یا مستقیماً:\n"
            "▫️ <b>اسم ماشینت</b> رو بنویسی (مثل <code>پژو ۲۰۶</code> یا <code>پراید</code>)\n"
            "▫️ <b>سایز لاستیک</b> رو بنویسی (مثل <code>185/65R14</code>)\n"
            "▫️ یا <b>کد روغن</b> رو بفرستی (مثل <code>10W40</code>)"
        )
        await self.bot.send_message(chat_id=chat_id, text=unknown_txt, reply_markup=self.get_main_keyboard(user))

    # الیاس سازگاری با تست‌ها و نسخه‌های قدیمی
    async def handle_text_message(self, message: Dict[str, Any]):
        return await self.handle_message(message)

