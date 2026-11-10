import html
import re
import logging
from typing import Dict, Any, Optional, List
from database import get_user, upsert_user, set_state, log_action
from bale_api import BaleBotClient
from config import PORTALS, CAR_HINT_FOR_SIZE, MARKET_TIRE_SIZES
from tire_api.sniper_engine import SniperEngine
from tire_api.utils import (
    escape_html,
    format_short_million,
    format_toman,
    get_tehran_now,
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
        fields = ["national_id", "mobile", "car_plate", "car_vin", "chassis_no", "green_sheet_no"]
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
            "🟢 شکارچی خودکار: روشن (آماده شلیک)"
            if is_sniper_on
            else "🔴 شکارچی خودکار: خاموش (کلیک برای روشن)"
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
                    {"text": f"🏭 شرکت‌ها ({p_short})", "callback_data": "menu_portal"},
                    {"text": f"🛞 سایز: {cur_size}", "callback_data": "menu_size"},
                ],
                [
                    {"text": f"👤 مدارک و خودرو ({prof_badge})", "callback_data": "menu_profile"},
                    {"text": "🔐 ورود پیامکی سایت", "callback_data": "auth_real_otp"},
                ],
                [
                    {"text": "📋 شناسنامه من", "callback_data": "view_profile"},
                    {"text": "📖 راهنما و ساعات", "callback_data": "menu_guide"},
                ],
            ]
        }

    def _build_dashboard_text(self, user: Dict[str, Any], header: str) -> str:
        _, progress_bar = self.calculate_profile_completion(user)
        sniper_st = "🟢 <b>فعال و در حال رصد لحظه‌ای</b>" if user.get("sniper_enabled", 0) else "🔴 <b>خاموش</b>"
        portal_name = PORTALS.get(user.get("target_portal", "all"), PORTALS["all"]).get("title", "همه کارخانه‌ها")
        size_label = self._format_size_label(user.get("target_tire_size", "185_65_14"))
        now_fa = get_tehran_now()["compact_fa"]

        return (
            f"🏎 <b>{header}</b>\n"
            f"🕒 <i>{now_fa}</i>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⚡ <b>شکارچی دولتی:</b> {sniper_st}\n"
            f"🏭 <b>شرکت هدف:</b> <code>{escape_html(portal_name)}</code>\n"
            f"🛞 <b>سایز هدف:</b> <code>{escape_html(size_label)}</code> (<b>{user.get('tire_count', 2)} حلقه</b>)\n"
            f"📋 <b>تکمیل مدارک:</b> <code>{progress_bar}</code>\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>نکته هوشمند: می‌توانید هر سایز دلخواهی مثل <code>185/65R14</code> را همین‌جا تایپ کنید تا قیمت لحظه‌ای بازار آزاد را بگیرید.</i>"
        )

    async def _safe_edit(self, chat_id: int, message_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None):
        res = await self.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup)
        if not res.get("ok"):
            err = str(res.get("description") or res.get("error") or "").lower()
            if "not modified" not in err:
                logger.warning(f"editMessageText fallback send_message chat={chat_id}: {res}")
                send_res = await self.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
                if not send_res.get("ok"):
                    logger.error(f"sendMessage failed chat={chat_id}: {send_res}")

    async def handle_start(self, chat_id: int, username: str = ""):
        user = await get_user(chat_id)
        if not user:
            user = await upsert_user(chat_id, username=username)
        await set_state(chat_id, "IDLE")

        text = self._build_dashboard_text(user, "سامانه هوشمند تایر دولتی و قیمت روز")
        await self.bot.send_message(chat_id=chat_id, text=text, reply_markup=self.get_main_keyboard(user))

    async def _send_market_price_report(
        self, chat_id: int, raw_size: str, edit_msg_id: Optional[int] = None, force_refresh: bool = False
    ):
        norm = normalize_tire_size(raw_size) or raw_size
        loading_txt = (
            f"🔎 <b>در حال استعلام زنده قیمت روز تایر <code>{escape_html(norm)}</code>...</b>\n\n"
            "⏳ اتصال هم‌زمان به فروشگاه‌های دیجی‌کالا، باسلام، ترب و هایپرتایر\n"
            "<i>در حال تفکیک دقیق تک‌حلقه، جفت و حذف اقلام متفرقه...</i>"
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
                    {"text": "🔄 به‌روزرسانی همین ساعت", "callback_data": f"mktrefresh_{size_key}"},
                    {"text": "🔍 سایز دیگر", "callback_data": "menu_market_price"},
                ],
                [{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}],
            ]
        }

        if not report.get("ok") or report.get("total_found", 0) == 0:
            logger.warning(f"[MARKET_PRICE] chat={chat_id} size={norm} EMPTY/FAIL srcs={report.get('source_counts')} status={report.get('source_status')}")
            await log_action(chat_id, "MARKET_PRICE", "EMPTY", f"size={norm} srcs={report.get('source_counts')}", report.get("latency_ms", 0.0))
            fail_txt = (
                f"⚠️ <b>نتیجه دقیقی برای سایز <code>{escape_html(norm)}</code> یافت نشد!</b>\n\n"
                "لطفاً مطمئن شوید سایز را صحیح وارد کرده‌اید (مثلاً <code>185/65R14</code> یا <code>205/60R15</code>) و دوباره تلاش کنید."
            )
            await self.bot.send_message(chat_id=chat_id, text=fail_txt, reply_markup=kb)
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

        lines: List[str] = [
            f"💰 <b>قیمت روز لاستیک آزاد • سایز <code>{escape_html(report['size'])}</code></b>",
            f"🕒 <b>زمان دقیق:</b> {ts['full_fa']}",
            f"📡 <b>منابع بررسی‌شده:</b> {src_summary_line}",
            "━━━━━━━━━━━━━━━━━━━━\n",
        ]

        ir_sum = report.get("ir_summary")
        if ir_sum:
            lines.append("🇮🇷 <b>بازه قیمت لاستیک ایرانی (تاییدشده):</b>")
            lines.append(
                f"▫️ هر حلقه: <b>{format_toman(ir_sum['min_unit'])}</b> تا <b>{format_toman(ir_sum['max_unit'])}</b> تومان "
                f"(میانه: <b>{format_toman(ir_sum['median_unit'])}</b>)"
            )
            lines.append(
                f"▫️ یک جفت (۲ حلقه): <b>{format_toman(ir_sum['min_pair'])}</b> تا <b>{format_toman(ir_sum['max_pair'])}</b> تومان\n"
            )

        imp_sum = report.get("imp_summary")
        if imp_sum:
            lines.append("🌍 <b>بازه قیمت لاستیک خارجی/وارداتی (تاییدشده):</b>")
            lines.append(
                f"▫️ هر حلقه: <b>{format_toman(imp_sum['min_unit'])}</b> تا <b>{format_toman(imp_sum['max_unit'])}</b> تومان"
            )
            lines.append(
                f"▫️ یک جفت (۲ حلقه): <b>{format_toman(imp_sum['min_pair'])}</b> تا <b>{format_toman(imp_sum['max_pair'])}</b> تومان\n"
            )

        def _fmt_offer(idx: int, o: Dict[str, Any]) -> str:
            brand = escape_html(o["brand"])
            yr = f" ({o['year']})" if o.get("year") else ""
            shop = escape_html(o["shop_name"][:24])
            src = escape_html(o["source"])
            pk = o.get("pack_count")
            unit_p = format_toman(o["unit_price_toman"])
            raw_p = format_toman(o["price_toman"])
            pack_note = f"حلقه <b>{unit_p}</b> ت (فروش جفتی: {raw_p})" if pk == 2 else (
                f"حلقه <b>{unit_p}</b> ت (بسته ۴تایی: {raw_p})" if pk == 4 else f"<b>{unit_p}</b> تومان (تک)"
            )
            safe_url = html.escape(str(o.get("url") or ""), quote=True)
            return f"{idx}. <b>{brand}{yr}</b> — {pack_note}\n   🏬 {src} | {shop} — <a href=\"{safe_url}\">مشاهده آگهی</a>"

        ir_offers = report.get("ir_offers", [])
        if ir_offers:
            lines.append("🏷 <b>ارزان‌ترین گزینه‌های ایرانی همین الان:</b>")
            for i, off in enumerate(ir_offers[:5], 1):
                lines.append(_fmt_offer(i, off))
            lines.append("")

        imp_offers = report.get("imp_offers", [])
        if imp_offers:
            lines.append("✈️ <b>گزینه‌های خارجی موجود در همین لحظه:</b>")
            for i, off in enumerate(imp_offers[:3], 1):
                lines.append(_fmt_offer(i, off))
            lines.append("")

        unspec = report.get("unspecified_offers", [])
        if unspec and (not ir_offers or unspec[0]["price_toman"] <= ir_offers[0]["unit_price_toman"] * 1.15):
            lines.append("⚠️ <i>فروشگاه بدون ذکر تک/جفت در عنوان (قبل از خرید تعداد را در لینک چک کنید):</i>")
            for off in unspec[:2]:
                safe_u = html.escape(str(off.get("url") or ""), quote=True)
                lines.append(
                    f"▫️ <b>{escape_html(off['brand'])}</b> — قیمت درج‌شده: <b>{format_toman(off['price_toman'])}</b> ت | "
                    f"{escape_html(off['shop_name'][:20])} (<a href=\"{safe_u}\">لینک</a>)"
                )

        lines.append("\n━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"⚡ <i>سرعت جمع‌آوری زنده: {report['latency_ms']} میلی‌ثانیه</i>")

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

        await self.bot.answer_callback_query(callback_id)

        user = await get_user(chat_id)
        if not user:
            user = await upsert_user(chat_id)

        if data == "main_menu":
            await set_state(chat_id, "IDLE")
            text = self._build_dashboard_text(user, "داشبورد اصلی مدیریت تایر")
            await self._safe_edit(chat_id, message_id, text, reply_markup=self.get_main_keyboard(user))

        elif data == "menu_profile":
            _, progress_bar = self.calculate_profile_completion(user)
            n_icon = "✅" if user.get("national_id") else "⚠️"
            m_icon = "✅" if user.get("mobile") else "⚠️"
            p_icon = "✅" if user.get("car_plate") else "⚠️"
            v_icon = "✅" if user.get("car_vin") else "⚠️"
            c_icon = "✅" if user.get("chassis_no") else "⚠️"
            g_icon = "✅" if user.get("green_sheet_no") else "⚠️"

            text = (
                "👤 <b>مدارک مالک و اطلاعات خودرو</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 <b>وضعیت تکمیل:</b> <code>{progress_bar}</code>\n\n"
                f"▫️ <b>کد ملی:</b> <code>{user.get('national_id') or 'ثبت نشده'}</code> {n_icon}\n"
                f"▫️ <b>موبایل:</b> <code>{user.get('mobile') or 'ثبت نشده'}</code> {m_icon}\n"
                f"▫️ <b>پلاک خودرو:</b> <code>{user.get('car_plate') or 'ثبت نشده'}</code> {p_icon}\n"
                f"▫️ <b>کد VIN:</b> <code>{user.get('car_vin') or 'ثبت نشده'}</code> {v_icon}\n"
                f"▫️ <b>شماره شاسی:</b> <code>{user.get('chassis_no') or 'ثبت نشده'}</code> {c_icon}\n"
                f"▫️ <b>سریال برگ سبز:</b> <code>{user.get('green_sheet_no') or 'ثبت نشده'}</code> {g_icon}\n\n"
                "👇 برای ثبت یا ویرایش هر مورد کلیک کنید:"
            )
            kb = {
                "inline_keyboard": [
                    [
                        {"text": f"کد ملی {n_icon}", "callback_data": "edit_national_id"},
                        {"text": f"موبایل {m_icon}", "callback_data": "edit_mobile"},
                    ],
                    [
                        {"text": f"شماره پلاک {p_icon}", "callback_data": "edit_plate"},
                        {"text": f"کد VIN {v_icon}", "callback_data": "edit_vin"},
                    ],
                    [
                        {"text": f"شماره شاسی {c_icon}", "callback_data": "edit_chassis"},
                        {"text": f"برگ سبز {g_icon}", "callback_data": "edit_green"},
                    ],
                    [{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}],
                ]
            }
            await self._safe_edit(chat_id, message_id, text, reply_markup=kb)

        elif data.startswith("edit_"):
            field = data.replace("edit_", "")
            prompts = {
                "national_id": ("AWAIT_NAT_ID", "👤 <b>کد ملی ۱۰ رقمی مالک را ارسال کنید:</b>\n<i>مثال: 0012345678</i>"),
                "mobile": ("AWAIT_MOBILE", "📱 <b>شماره موبایل ۱۱ رقمی به نام مالک را ارسال کنید:</b>\n<i>مثال: 09123456789</i>"),
                "plate": ("AWAIT_PLATE", "🚘 <b>شماره پلاک کامل خودرو را ارسال کنید:</b>\n<i>مثال: ۱۲ ب ۳۴۵ ایران ۲۲</i>"),
                "vin": ("AWAIT_VIN", "🔑 <b>کد ۱۷ رقمی VIN روی کارت ماشین را ارسال کنید:</b>\n<i>مثال: IRNC1234567890123</i>"),
                "chassis": ("AWAIT_CHASSIS", "⚙️ <b>شماره شاسی خودرو را ارسال کنید:</b>"),
                "green": ("AWAIT_GREEN", "📄 <b>شماره سریال قرمز رنگ برگ سبز را ارسال کنید:</b>"),
            }
            if field in prompts:
                st, msg = prompts[field]
                await set_state(chat_id, st)
                kb = {"inline_keyboard": [[{"text": "❌ انصراف و بازگشت", "callback_data": "menu_profile"}]]}
                await self._safe_edit(chat_id, message_id, msg, reply_markup=kb)

        elif data == "menu_portal":
            cur_p = user.get("target_portal", "all")
            rows: List[List[Dict[str, str]]] = [
                [{
                    "text": ("🔘 " if cur_p == "all" else "⚪ ") + "🌐 همه شرکت‌ها (اسکن خودکار سراسری — پیشنهادی)",
                    "callback_data": "set_portal_all",
                }]
            ]
            # چیدمان متقارن ۲ ستونی برای تک‌تک شرکت‌های تایر دولتی
            factory_keys = ["hypertire", "barez", "kavir", "irantire", "yazd", "razi", "kian", "artawheel", "dena", "ntsw"]
            for i in range(0, len(factory_keys), 2):
                pair_btns = []
                for pk in factory_keys[i : i + 2]:
                    mark = "🔘 " if pk == cur_p else "⚪ "
                    pair_btns.append({"text": f"{mark}{PORTALS[pk]['short']}", "callback_data": f"set_portal_{pk}"})
                rows.append(pair_btns)

            rows.append([{"text": "📡 تست زنده وضعیت همه شرکت‌ها", "callback_data": "live_portals_health"}])
            rows.append([{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}])

            cur_info = PORTALS.get(cur_p, PORTALS["all"])
            text = (
                "🏭 <b>انتخاب کارخانه یا سامانه فروش تایر دولتی</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"✅ <b>انتخاب فعلی:</b> <code>{escape_html(cur_info['title'])}</code>\n"
                f"ℹ️ <i>{escape_html(cur_info['desc'])}</i>\n\n"
                "💡 <b>پیشنهاد هوشمند:</b> گزینه «همه شرکت‌ها» را انتخاب کنید تا ربات به‌صورت خودکار تمام سایت‌های باز مثل <b>بارز، هایپرتایر، کویر، ایران‌تایر، یزد، رازی، کیان، آرتاویل، دنا و سامانه تجارت</b> را با هم رصد کند.\n\n"
                "👇 گزینه دلخواه را انتخاب کنید:"
            )
            await self._safe_edit(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data.startswith("set_portal_"):
            p = data.replace("set_portal_", "")
            if p in PORTALS:
                await upsert_user(chat_id, target_portal=p)
            await self.handle_callback_query({"id": callback_id, "message": {"chat": {"id": chat_id}, "message_id": message_id}, "data": "menu_portal"})

        elif data == "live_portals_health":
            await self._safe_edit(chat_id, message_id, "📡 <b>در حال بررسی اتصال زنده تمام ۱۰ کارخانه و درگاه دولتی...</b>")
            scan = await self.sniper.scan_all_portals_live("all")
            now_fa = get_tehran_now()["compact_fa"]
            lines = [
                f"🌐 <b>وضعیت برخط سایت‌های تایر دولتی ({now_fa})</b>",
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
                    f"{icon} <b>{escape_html(st['title'])}</b> ({st['latency_ms']} ms)\n"
                    f"   └ {escape_html(st['status_desc'])}"
                )
            lines.append("\n━━━━━━━━━━━━━━━━━━━━")
            lines.append("🟢 موجود و باز | 🟡 آنلاین (ناموجود) | 📵 نیازمند قطع فیلترشکن")
            kb = {
                "inline_keyboard": [
                    [{"text": "🔄 اسکن مجدد", "callback_data": "live_portals_health"}],
                    [{"text": "🔙 بازگشت به لیست شرکت‌ها", "callback_data": "menu_portal"}],
                ]
            }
            ok_portals = [st["portal"] for st in scan["portals_status"] if st.get("ok")]
            in_stock_cnt = len(scan.get("all_in_stock_items", []))
            logger.info(f"[PORTALS_HEALTH] chat={chat_id} ok={len(ok_portals)}/10 in_stock={in_stock_cnt}")
            await log_action(chat_id, "PORTALS_HEALTH", "OK", f"online={len(ok_portals)}/10 in_stock={in_stock_cnt}", 0.0)
            await self._safe_edit(chat_id, message_id, "\n".join(lines), reply_markup=kb)

        elif data in ("menu_size", "menu_size_catalog"):
            show_catalog = (data == "menu_size_catalog")
            cur_portal = user.get("target_portal", "all")
            current_size = user.get("target_tire_size", "185_65_14")
            count = user.get("tire_count", 2)

            await self._safe_edit(
                chat_id,
                message_id,
                "⏳ <b>در حال دریافت لیست زنده سایزها از موجودی سایت‌های دولتی...</b>",
            )
            scan = await self.sniper.scan_all_portals_live(cur_portal)
            avail = scan["available_sizes"]
            cat_sizes = scan["catalog_sizes"]

            rows: List[List[Dict[str, str]]] = []
            lines: List[str] = [
                "🛞 <b>سایزهای تایر دولتی (فقط بر اساس موجودی سایت‌ها)</b>",
                f"🕒 <i>به‌روزرسانی لحظه‌ای: {get_tehran_now()['compact_fa']}</i>",
                "━━━━━━━━━━━━━━━━━━━━\n",
            ]

            if avail:
                lines.append("🟢 <b>سایزهای واقعاً موجود در این لحظه:</b>")
                sorted_avail = sorted(avail.values(), key=lambda x: x["size"])
                for item in sorted_avail:
                    sk = item["size_key"]
                    sz = item["size"]
                    pr = format_short_million(item["min_price_toman"]) if item["min_price_toman"] else "-"
                    p_str = "، ".join(item["portals"])
                    mark = "✅" if sk == current_size else "🟢"
                    lines.append(f"▫️ <code>{sz}</code> — {escape_html(p_str)} (از {format_toman(item['min_price_toman'])} ت | {item['count']} مدل)")
                    rows.append([{
                        "text": f"{mark} {sz} • {p_str} ({pr})",
                        "callback_data": f"set_size_{sk}",
                    }])
                lines.append("")
            else:
                lines.append("🔴 <b>در این دقیقه هیچ سایزی در انبار دولتی باز نیست.</b>\n")

            if show_catalog and cat_sizes:
                lines.append("📋 <b>سایزهای ثبت‌شده در کاتالوگ سایت‌ها (در صف شارژ برای شکارچی):</b>")
                # چیدمان تمیز ۲ ستونی
                extra_btns: List[Dict[str, str]] = []
                for sz in cat_sizes:
                    sk = size_to_key(sz)
                    if sk in avail:
                        continue
                    mark = "🔘 " if sk == current_size else "⏳ "
                    extra_btns.append({"text": f"{mark}{sz}", "callback_data": f"set_size_{sk}"})
                for i in range(0, len(extra_btns), 2):
                    rows.append(extra_btns[i : i + 2])
            elif cat_sizes:
                rows.append([{"text": f"⏳ سایر سایزهای کاتالوگ سایت‌ها ({len(cat_sizes)} سایز)", "callback_data": "menu_size_catalog"}])

            c2 = "🔘 ۲ حلقه" if count == 2 else "⚪ ۲ حلقه"
            c4 = "🔘 ۴ حلقه" if count == 4 else "⚪ ۴ حلقه"
            rows.append([
                {"text": c2, "callback_data": "set_count_2"},
                {"text": c4, "callback_data": "set_count_4"},
            ])
            rows.append([
                {"text": "🔄 رفرش موجودی", "callback_data": "menu_size"},
                {"text": "🏠 منوی اصلی", "callback_data": "main_menu"},
            ])

            lines.append(f"🎯 <b>سایز فعلی شما:</b> <code>{escape_html(self._format_size_label(current_size))}</code> (<b>{count} حلقه</b>)")
            lines.append("👇 برای انتخاب روی سایز کلیک کنید:")
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
                        {"text": "📦 بررسی جزئیات خرید همین سایز", "callback_data": "live_check_stock"},
                        {"text": "💰 قیمت آزاد همین سایز", "callback_data": f"mkt_{new_size}"},
                    ],
                    [
                        {"text": "⚡ روشن‌کردن شکارچی برای این سایز", "callback_data": "menu_sniper"},
                        {"text": "🏠 منوی اصلی", "callback_data": "main_menu"},
                    ],
                ]
            }
            await self._safe_edit(
                chat_id,
                message_id,
                f"✅ <b>سایز هدف شما با موفقیت تنظیم شد:</b>\n\n🛞 <code>{escape_html(self._format_size_label(norm))}</code>",
                reply_markup=kb,
            )

        elif data.startswith("set_count_"):
            c = int(data.replace("set_count_", ""))
            await upsert_user(chat_id, tire_count=c)
            await self.handle_callback_query({"id": callback_id, "message": {"chat": {"id": chat_id}, "message_id": message_id}, "data": "menu_size"})

        elif data == "menu_market_price":
            rows: List[List[Dict[str, str]]] = []
            for i in range(0, len(MARKET_TIRE_SIZES), 2):
                pair = []
                for sz, car in MARKET_TIRE_SIZES[i : i + 2]:
                    pair.append({"text": f"🛞 {sz} ({car})", "callback_data": f"mkt_{size_to_key(sz)}"})
                rows.append(pair)
            rows.append([{"text": "✍️ تایپ سایز دلخواه (مثلاً 225/55R19)", "callback_data": "ask_custom_market_size"}])
            rows.append([{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}])

            now_fa = get_tehran_now()["full_fa"]
            text = (
                "💰 <b>استعلام زنده قیمت روز لاستیک آزاد</b>\n"
                f"🕒 <i>{now_fa}</i>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "ربات هم‌زمان به فروشگاه‌های سراسر کشور متصل می‌شود و دقیق‌ترین نرخ این ساعت را با تفکیک <b>تک حلقه</b> و <b>جفت</b> محاسبه می‌کند.\n\n"
                "👇 سایز خودروی خود را انتخاب کنید یا دستی تایپ کنید:"
            )
            await self._safe_edit(chat_id, message_id, text, reply_markup={"inline_keyboard": rows})

        elif data == "ask_custom_market_size":
            await set_state(chat_id, "AWAIT_MARKET_SIZE")
            kb = {"inline_keyboard": [[{"text": "❌ انصراف و بازگشت", "callback_data": "menu_market_price"}]]}
            await self._safe_edit(
                chat_id,
                message_id,
                "✍️ <b>سایز تایر مورد نظر را بفرستید:</b>\n\nمثال: <code>185/65R14</code> یا <code>205/60/15</code> یا <code>225/55R19</code>",
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
            btn_toggle = "🛑 خاموش کردن شکارچی" if is_active else "⚡ روشن کردن شکارچی خودکار"
            portal_name = PORTALS.get(user.get("target_portal", "all"), PORTALS["all"]).get("title", "")
            size_name = self._format_size_label(user.get("target_tire_size", "185_65_14"))

            text = (
                "⚡ <b>مدیریت شکارچی خودکار تایر دولتی</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📡 <b>وضعیت کنونی:</b> {status_badge}\n"
                f"🏭 <b>شرکت‌های تحت نظر:</b> <code>{escape_html(portal_name)}</code>\n"
                f"🛞 <b>سایز انتخابی:</b> <code>{escape_html(size_name)}</code>\n"
                f"📦 <b>تعداد درخواستی:</b> <b>{user.get('tire_count', 2)} حلقه</b>\n\n"
                "⚙️ <i>ربات هر چند ثانیه موجودی واقعی تمام سایت‌های هدف را چک می‌کند و به محض بازشدن، رزرو و لینک پرداخت را ارسال می‌نماید.</i>"
            )
            kb = {
                "inline_keyboard": [
                    [{"text": btn_toggle, "callback_data": "toggle_sniper"}],
                    [
                        {"text": "🏭 تغییر شرکت هدف", "callback_data": "menu_portal"},
                        {"text": "🛞 تغییر سایز موجود", "callback_data": "menu_size"},
                    ],
                    [{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}],
                ]
            }
            await self._safe_edit(chat_id, message_id, text, reply_markup=kb)

        elif data == "toggle_sniper":
            is_active = user.get("sniper_enabled", 0)
            if is_active:
                await self.sniper.stop_sniper_for_user(chat_id)
            else:
                if not user.get("national_id") or not user.get("mobile"):
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text="⚠️ <b>اطلاعات ناقص است!</b>\nلطفاً ابتدا در بخش «👤 مدارک و خودرو»، حداقل <b>کد ملی</b> و <b>شماره موبایل</b> را ثبت کنید.",
                    )
                    return
                await upsert_user(chat_id, sniper_enabled=1)
                await self.sniper.start_sniper_for_user(chat_id)
            await self.handle_callback_query({"id": callback_id, "message": {"chat": {"id": chat_id}, "message_id": message_id}, "data": "menu_sniper"})

        elif data == "live_check_stock":
            await self._safe_edit(chat_id, message_id, "📡 <b>در حال استعلام زنده و مستقیم موجودی از سایت‌های دولتی...</b>")
            stock_info = await self.sniper.check_live_stock_now(chat_id)
            p_title = PORTALS.get(stock_info["portal"], PORTALS["all"]).get("title", stock_info["portal"])
            matched = stock_info["matched_items"]
            all_avail = stock_info["available_sizes"]
            now_fa = get_tehran_now()["compact_fa"]

            lines = [
                f"📦 <b>گزارش زنده انبار دولتی ({now_fa})</b>",
                "━━━━━━━━━━━━━━━━━━━━\n",
                f"🏭 <b>دامنه بررسی:</b> <code>{escape_html(p_title)}</code>",
                f"🎯 <b>سایز هدف شما:</b> <code>{escape_html(stock_info['tire_size_display'])}</code>\n",
            ]

            if matched:
                lines.append(f"🎉 <b>فوری: {len(matched)} مدل از سایز شما همین الان موجود است!</b>")
                for it in matched[:5]:
                    safe_it_u = html.escape(str(it.get("url") or ""), quote=True)
                    lines.append(
                        f"🟢 <b>{escape_html(it.get('brand', ''))} {escape_html(it.get('model', ''))}</b> — "
                        f"<b>{format_toman(it.get('price_toman', 0))}</b> ت | {escape_html(it.get('portal_title', ''))}\n"
                        f"   🔗 <a href=\"{safe_it_u}\">مشاهده و خرید مستقیم</a>"
                    )
                lines.append("\n⚡ برای رزرو سریع دکمه «⚡ شکارچی خودکار» را بزنید یا مستقیم از لینک بالا بخرید.")
            else:
                lines.append(f"🔴 سایز انتخابی شما (<code>{escape_html(stock_info['tire_size_display'])}</code>) در این دقیقه موجود نیست.")

            if all_avail:
                lines.append("\n🟢 <b>سایزهایی که همین الان در سایت‌ها موجود هستند:</b>")
                for bucket in sorted(all_avail.values(), key=lambda b: b["size"])[:8]:
                    pr_txt = f"{format_toman(bucket['min_price_toman'])} ت" if bucket["min_price_toman"] else ""
                    lines.append(f"▫️ <code>{bucket['size']}</code> ({'، '.join(bucket['portals'])}) {pr_txt}")

            kb = {
                "inline_keyboard": [
                    [
                        {"text": "🔄 استعلام مجدد", "callback_data": "live_check_stock"},
                        {"text": "🛞 انتخاب از سایزهای موجود", "callback_data": "menu_size"},
                    ],
                    [{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}],
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
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ <b>شماره موبایل یافت نشد!</b>\nلطفاً ابتدا در بخش «👤 مدارک و خودرو» شماره همراه مالک را ثبت کنید.",
                )
                return
            portal = user.get("target_portal", "all")
            if portal not in ("barez", "kavir"):
                kb = {
                    "inline_keyboard": [
                        [
                            {"text": "🏭 ارسال پیامک سایت بارز", "callback_data": "otp_send_barez"},
                            {"text": "🏭 ارسال پیامک کویرتایر", "callback_data": "otp_send_kavir"},
                        ],
                        [{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}],
                    ]
                }
                await self._safe_edit(
                    chat_id,
                    message_id,
                    "🔐 <b>ورود پیامکی مستقیم به حساب کارخانه</b>\n\nبرای کدام سایت می‌خواهید کد پیامکی احراز هویت دریافت کنید؟",
                    reply_markup=kb,
                )
                return
            await self.handle_callback_query({"id": callback_id, "message": {"chat": {"id": chat_id}, "message_id": message_id}, "data": f"otp_send_{portal}"})

        elif data.startswith("otp_send_"):
            otp_portal = data.replace("otp_send_", "")
            await self._safe_edit(
                chat_id,
                message_id,
                f"📲 <b>در حال ارسال درخواست پیامک از {PORTALS.get(otp_portal, {}).get('short', otp_portal)} به {user.get('mobile')}...</b>",
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
                kb = {"inline_keyboard": [[{"text": "❌ انصراف", "callback_data": "main_menu"}]]}
                await self._safe_edit(
                    chat_id,
                    message_id,
                    f"📩 <b>کد پیامکی ارسال شد!</b>\n\nلطفاً کد تایید دریافتی روی شماره <code>{user.get('mobile')}</code> را اینجا بفرستید:",
                    reply_markup=kb,
                )
            else:
                kb = {"inline_keyboard": [[{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}]]}
                await self._safe_edit(chat_id, message_id, f"❌ <b>عدم موفقیت در ارسال پیامک:</b>\n\n{escape_html(res.get('message', ''))}", reply_markup=kb)

        elif data == "view_profile":
            p_name = PORTALS.get(user.get("target_portal", "all"), PORTALS["all"]).get("title", "")
            s_name = self._format_size_label(user.get("target_tire_size", "185_65_14"))
            sniper_st = "🟢 <b>روشن</b>" if user.get("sniper_enabled", 0) else "🔴 <b>خاموش</b>"
            _, progress_bar = self.calculate_profile_completion(user)

            summary = (
                "📋 <b>شناسنامه و تنظیمات شما</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 <b>کد ملی:</b> <code>{user.get('national_id') or 'ثبت نشده'}</code>\n"
                f"📱 <b>موبایل:</b> <code>{user.get('mobile') or 'ثبت نشده'}</code>\n"
                f"🚘 <b>پلاک:</b> <code>{user.get('car_plate') or 'ثبت نشده'}</code>\n"
                f"🔑 <b>کد VIN:</b> <code>{user.get('car_vin') or 'ثبت نشده'}</code>\n"
                f"⚙️ <b>شاسی:</b> <code>{user.get('chassis_no') or 'ثبت نشده'}</code>\n"
                f"📄 <b>برگ سبز:</b> <code>{user.get('green_sheet_no') or 'ثبت نشده'}</code>\n\n"
                f"🏭 <b>شرکت هدف:</b> <code>{escape_html(p_name)}</code>\n"
                f"🛞 <b>سایز هدف:</b> <code>{escape_html(s_name)}</code> (<b>{user.get('tire_count', 2)} حلقه</b>)\n"
                f"⚡ <b>شکارچی:</b> {sniper_st}\n"
                f"📊 <b>آمادگی:</b> <code>{progress_bar}</code>"
            )
            kb = {
                "inline_keyboard": [
                    [{"text": "✏️ ویرایش مدارک", "callback_data": "menu_profile"}],
                    [{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}],
                ]
            }
            await self._safe_edit(chat_id, message_id, summary, reply_markup=kb)

        elif data == "menu_guide":
            guide_text = (
                "📖 <b>راهنمای استفاده سریع از ربات</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "1️⃣ <b>مدارک:</b> از بخش «👤 مدارک و خودرو» کد ملی، موبایل (به نام مالک) و اطلاعات کارت خودرو را ثبت کنید.\n"
                "2️⃣ <b>موجودی دولتی:</b> دکمه «🛞 سایزها» فقط بر اساس موجودی لحظه‌ای سایت‌ها به شما نمایش می‌دهد چه سایزی باز است.\n"
                "3️⃣ <b>شکارچی خودکار:</b> روی «همه شرکت‌ها» بگذارید و روشن کنید تا تمام سایت‌های دولتی هم‌زمان رصد شوند.\n"
                "4️⃣ <b>قیمت روز تایر آزاد:</b> با زدن «💰 قیمت روز تایر آزاد» یا تایپ مستقیم سایز (مثلاً <code>185/65R14</code>) نرخ همان ساعت را از فروشگاه‌های کشور بگیرید.\n\n"
                "⏰ <b>نکته مهم برای کویرتایر و سامانه تجارت:</b> هنگام استفاده از بخش دولتی این دو سایت، حتماً فیلترشکن دستگاه/سرور خاموش باشد."
            )
            kb = {"inline_keyboard": [[{"text": "🏠 منوی اصلی", "callback_data": "main_menu"}]]}
            await self._safe_edit(chat_id, message_id, guide_text, reply_markup=kb)

    async def handle_text_message(self, message: Dict[str, Any]):
        chat_id = message.get("chat", {}).get("id")
        text = persian_to_english_digits(message.get("text", "").strip())

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
                await self.bot.send_message(chat_id, f"✅ <b>کد ملی ثبت شد:</b> <code>{cleaned}</code>", reply_markup=self.get_main_keyboard(await get_user(chat_id)))
            else:
                await self.bot.send_message(chat_id, "❌ کد ملی باید ۱۰ رقم باشد. دوباره بفرستید:")

        elif state == "AWAIT_MOBILE":
            cleaned = re.sub(r"\D", "", text)
            if len(cleaned) == 11 and cleaned.startswith("09"):
                await upsert_user(chat_id, mobile=cleaned, state="IDLE")
                await self.bot.send_message(chat_id, f"✅ <b>موبایل ذخیره شد:</b> <code>{cleaned}</code>", reply_markup=self.get_main_keyboard(await get_user(chat_id)))
            else:
                await self.bot.send_message(chat_id, "❌ شماره موبایل نامعتبر است (مثال: <code>09121234567</code>):")

        elif state == "AWAIT_PLATE":
            await upsert_user(chat_id, car_plate=message.get("text", "").strip(), state="IDLE")
            await self.bot.send_message(chat_id, f"✅ <b>پلاک ثبت شد:</b> <code>{escape_html(message.get('text', '').strip())}</code>", reply_markup=self.get_main_keyboard(await get_user(chat_id)))

        elif state == "AWAIT_VIN":
            vin_clean = text.strip().upper()
            await upsert_user(chat_id, car_vin=vin_clean, state="IDLE")
            await self.bot.send_message(chat_id, f"✅ <b>کد VIN ذخیره شد:</b> <code>{escape_html(vin_clean)}</code>", reply_markup=self.get_main_keyboard(await get_user(chat_id)))

        elif state == "AWAIT_CHASSIS":
            val = text.strip().upper()
            await upsert_user(chat_id, chassis_no=val, state="IDLE")
            await self.bot.send_message(chat_id, f"✅ <b>شماره شاسی ذخیره شد:</b> <code>{escape_html(val)}</code>", reply_markup=self.get_main_keyboard(await get_user(chat_id)))

        elif state == "AWAIT_GREEN":
            val = text.strip()
            await upsert_user(chat_id, green_sheet_no=val, state="IDLE")
            await self.bot.send_message(chat_id, f"✅ <b>برگ سبز ثبت شد:</b> <code>{escape_html(val)}</code>", reply_markup=self.get_main_keyboard(await get_user(chat_id)))

        elif state.startswith("AWAIT_REAL_OTP"):
            otp_portal = "barez" if "BAREZ" in state else ("kavir" if "KAVIR" in state else None)
            await self.bot.send_message(chat_id, "⏳ <b>در حال بررسی کد تایید در سرور...</b>")
            verify_res = await self.sniper.verify_real_otp(chat_id, text.strip(), portal_override=otp_portal)
            if verify_res.get("ok"):
                await set_state(chat_id, "IDLE")
                await self.bot.send_message(chat_id, verify_res.get("message", "✅ تایید شد"), reply_markup=self.get_main_keyboard(await get_user(chat_id)))
            else:
                await self.bot.send_message(chat_id, f"{verify_res.get('message')}\nکد صحیح را دوباره بفرستید یا /start بزنید:")

        elif state == "AWAIT_MARKET_SIZE":
            norm = normalize_tire_size(text)
            if norm:
                await set_state(chat_id, "IDLE")
                await self._send_market_price_report(chat_id, norm)
            else:
                await self.bot.send_message(chat_id, "❌ فرمت سایز درست نیست! مثال: <code>185/65R14</code> یا <code>205/60/15</code>")

        else:
            # هوشمندی: اگر کاربر بدون رفتن به منو مستقیم سایز لاستیک (مثلاً 185/65R14) بفرستد، همان لحظه قیمت روز را استعلام می‌گیرد!
            detected_size = normalize_tire_size(text)
            if detected_size:
                await self._send_market_price_report(chat_id, detected_size)
                return

            await self.bot.send_message(
                chat_id=chat_id,
                text="👇 لطفاً از منوی زیر گزینه دلخواه خود را انتخاب کنید (یا مستقیم سایز تایر مثل <code>185/65R14</code> را بفرستید):",
                reply_markup=self.get_main_keyboard(user),
            )
