import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import aiohttp
from config import DEFAULT_HEADERS
from tire_api.utils import clean_search_text, get_tehran_now, persian_to_english_digits

logger = logging.getLogger("OilPriceClient")

_COMMON_BULK_BAD = (
    "کارتن",
    "بسته 6",
    "بسته 12",
    "بسته 24",
    "6 عددی",
    "12 عددی",
    "24 عددی",
    "پک 6",
    "پک 12",
    "عمده",
    "بشکه",
    "208 لیتر",
)

_NON_GASOLINE_BAD = (
    "موتور سیکلت",
    "موتورسیکلت",
    "موتوربایک",
    "motorbike",
    "motorcycle",
    "اسکوتر",
    "scooter",
    "گیربکس",
    "دنده",
    "واسکازین",
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
    "بسته 4",
    "4 عددی",
)

_DK_OIL_BRANDS = ("behran", "iranol", "speedy", "caspian", "castrol", "total", "liqui-moly")

# نگاشت کامل کدهای ویژه غیر از گرانروی‌های ساده بنزینی
_SPECIAL_OIL_SPECS: Dict[str, Dict[str, Any]] = {
    "15W40-D": {
        "kind": "diesel",
        "grade": "15W40",
        "title_fa": "روغن موتور دیزلی 15W40 (کامیون و کشنده)",
        "vol_label": "گالن ۲۰ لیتری / دیزلی",
        "queries": ("روغن موتور دیزلی 15W40 20 لیتری", "روغن موتور 15W40 20 لیتری"),
        "dk_q": "روغن موتور 15W40",
    },
    "10W40-D": {
        "kind": "diesel",
        "grade": "10W40",
        "title_fa": "روغن موتور دیزلی 10W40 سنتتیک (یورو ۵/۶)",
        "vol_label": "گالن ۲۰ لیتری دیزلی",
        "queries": ("روغن موتور دیزلی 10W40 20 لیتری", "روغن دیزلی 10W40"),
        "dk_q": "روغن دیزلی 10W40",
    },
    "20W50-D": {
        "kind": "diesel",
        "grade": "20W50",
        "title_fa": "روغن موتور دیزلی 20W50 (مایلر، خاور، نیسان دیزل)",
        "vol_label": "گالن ۲۰ لیتری دیزلی",
        "queries": ("روغن موتور دیزلی 20W50 20 لیتری", "روغن موتور 20W50 20 لیتری"),
        "dk_q": "روغن موتور 20W50 20",
    },
    "SAE40-D": {
        "kind": "diesel_single",
        "grade": "SAE40",
        "title_fa": "روغن موتور تک‌درجه دیزلی SAE 40",
        "vol_label": "گالن ۲۰ لیتری دیزلی",
        "queries": ("روغن موتور دیزلی SAE 40 20 لیتری", "روغن موتور بهران توربو دیزل 40"),
        "dk_q": "روغن موتور 40",
    },
    "SAE50-D": {
        "kind": "diesel_single",
        "grade": "SAE50",
        "title_fa": "روغن موتور تک‌درجه دیزلی SAE 50",
        "vol_label": "گالن ۲۰ لیتری دیزلی",
        "queries": ("روغن موتور دیزلی SAE 50 20 لیتری", "روغن موتور بهران توربو دیزل 50"),
        "dk_q": "روغن موتور 50",
    },
    "75W80": {
        "kind": "gear_manual",
        "grade": "75W80",
        "title_fa": "روغن گیربکس دنده‌ای (واسکازین) 75W80",
        "vol_label": "بطری ۱ تا ۲ لیتری",
        "queries": ("روغن گیربکس 75W80", "واسکازین 75W80"),
        "dk_q": "روغن دنده 75W80",
    },
    "75W85": {
        "kind": "gear_manual",
        "grade": "75W85",
        "title_fa": "روغن گیربکس دنده‌ای (واسکازین) 75W85",
        "vol_label": "بطری ۱ تا ۲.۵ لیتری",
        "queries": ("روغن گیربکس 75W85", "واسکازین 75W85"),
        "dk_q": "روغن دنده 75W85",
    },
    "75W90": {
        "kind": "gear_manual",
        "grade": "75W90",
        "title_fa": "روغن گیربکس و دیفرانسیل 75W90",
        "vol_label": "بطری ۱ تا ۲.۵ لیتری",
        "queries": ("روغن گیربکس 75W90", "روغن دنده 75W90"),
        "dk_q": "روغن دنده 75W90",
    },
    "85W90": {
        "kind": "gear_manual",
        "grade": "85W90",
        "title_fa": "واسکازین دنده و دیفرانسیل 85W90",
        "vol_label": "بطری ۱ تا ۴ لیتری",
        "queries": ("روغن دنده 85W90", "واسکازین 85W90"),
        "dk_q": "روغن دنده 85W90",
    },
    "85W140": {
        "kind": "gear_manual",
        "grade": "85W140",
        "title_fa": "واسکازین سنگین دیفرانسیل 85W140",
        "vol_label": "گالن ۴ یا ۲۰ لیتری",
        "queries": ("روغن دنده 85W140", "واسکازین 85W140"),
        "dk_q": "روغن دنده 85W140",
    },
    "ATF-MULTI": {
        "kind": "gear_auto",
        "grade": "ATF",
        "title_fa": "روغن گیربکس اتوماتیک (ATF / AL4)",
        "vol_label": "بطری ۱ تا ۴ لیتری",
        "queries": ("روغن گیربکس اتوماتیک ATF", "روغن گیربکس اتوماتیک 1 لیتری"),
        "dk_q": "روغن گیربکس ATF",
    },
    "CVT": {
        "kind": "gear_auto",
        "grade": "CVT",
        "title_fa": "روغن گیربکس اتوماتیک CVT",
        "vol_label": "بطری ۱ تا ۴ لیتری",
        "queries": ("روغن گیربکس CVT", "روغن گیربکس اتوماتیک CVT"),
        "dk_q": "روغن گیربکس CVT",
    },
    "DCT": {
        "kind": "gear_auto",
        "grade": "DCT",
        "title_fa": "روغن گیربکس دوکلاچه (DCT / DSG)",
        "vol_label": "بطری ۱ تا ۴ لیتری",
        "queries": ("روغن گیربکس DCT", "روغن گیربکس دوکلاچه DCT"),
        "dk_q": "روغن گیربکس DCT",
    },
    "HYD-ATF": {
        "kind": "hydraulic",
        "grade": "HYD",
        "title_fa": "روغن هیدرولیک فرمان خودرو",
        "vol_label": "بطری ۱ لیتری",
        "queries": ("روغن هیدرولیک فرمان 1 لیتری", "روغن هیدرولیک فرمان بهران"),
        "dk_q": "روغن هیدرولیک",
    },
    "DOT4": {
        "kind": "brake",
        "grade": "DOT4",
        "title_fa": "روغن ترمز استاندارد DOT4",
        "vol_label": "بطری نیم یا ۱ لیتری",
        "queries": ("روغن ترمز DOT4", "روغن ترمز زرد DOT4"),
        "dk_q": "روغن ترمز DOT4",
    },
    "DOT3": {
        "kind": "brake",
        "grade": "DOT3",
        "title_fa": "روغن ترمز استاندارد DOT3",
        "vol_label": "بطری نیم یا ۱ لیتری",
        "queries": ("روغن ترمز DOT3", "روغن ترمز آبی DOT3"),
        "dk_q": "روغن ترمز DOT3",
    },
    "ANTIFREEZE": {
        "kind": "antifreeze",
        "grade": "ANTIFREEZE",
        "title_fa": "ضدیخ و ضدجوش رادیاتور خودرو",
        "vol_label": "بطری ۱ تا ۴ لیتری",
        "queries": ("ضد یخ خودرو 1 لیتری", "ضد یخ 4 لیتری بهران کاسپین"),
        "dk_q": "ضد یخ",
    },
    "MOTO-10W40": {
        "kind": "moto",
        "grade": "10W40",
        "title_fa": "روغن موتور سیکلت و اسکوتر 10W40",
        "vol_label": "بطری ۱ لیتری",
        "queries": ("روغن موتور سیکلت 10W40 1 لیتری", "روغن موتور اسکوتر 10W40"),
        "dk_q": "روغن موتور سیکلت 10W40",
    },
    "MOTO-20W50": {
        "kind": "moto",
        "grade": "20W50",
        "title_fa": "روغن موتور سیکلت 20W50",
        "vol_label": "بطری ۱ لیتری",
        "queries": ("روغن موتور سیکلت 20W50 1 لیتری", "روغن موتور هوندا 20W50"),
        "dk_q": "روغن موتور سیکلت 20W50",
    },
}


def normalize_oil_grade(raw: str) -> Optional[str]:
    """
    تبدیل هر ورودی روغن (گرانروی بنزینی، دیزلی، واسکازین گیربکس، اتوماتیک، هیدرولیک، ترمز، ضدیخ و موتورسیکلت)
    به کد استاندارد یکتا
    """
    if not raw:
        return None
    cleaned = clean_search_text(raw)
    u = cleaned.upper().strip()

    if u in _SPECIAL_OIL_SPECS:
        return u

    low = cleaned.lower()

    # تشخیص روغن موتورسیکلت در متن آزاد
    if any(k in low for k in ("موتورسیکلت", "موتور سیکلت", "اسکوتر", "هوندا")):
        m_m = re.search(r"(?<!\d)(10|20)\s*[Ww/\-]\s*(40|50)(?!\d)", u)
        if m_m:
            cand = f"MOTO-{m_m.group(1)}W{m_m.group(2)}"
            if cand in _SPECIAL_OIL_SPECS:
                return cand
        return "MOTO-10W40"

    # تشخیص گیربکس اتوماتیک، هیدرولیک، ترمز، ضدیخ
    if "dct" in low or "dsg" in low or "دوکلاچه" in low or "دو کلاچه" in low:
        return "DCT"
    if "cvt" in low:
        return "CVT"
    if "dot4" in low or "dot 4" in low or "دات 4" in low or "دات4" in low:
        return "DOT4"
    if "dot3" in low or "dot 3" in low or "دات 3" in low or "دات3" in low:
        return "DOT3"
    if "ترمز" in low:
        return "DOT4"
    if "هیدرولیک" in low or "فرمان" in low:
        return "HYD-ATF"
    if "ضدیخ" in low or "ضد یخ" in low or "ضدجوش" in low or "antifreeze" in low:
        return "ANTIFREEZE"
    if "atf" in low or ("گیربکس" in low and "اتومات" in low):
        return "ATF-MULTI"

    # تشخیص تک‌درجه دیزلی SAE 40 / SAE 50
    if re.search(r"SAE\s*40|تک\s*درجه\s*40", u):
        return "SAE40-D"
    if re.search(r"SAE\s*50|تک\s*درجه\s*50", u):
        return "SAE50-D"

    # تشخیص واسکازین / گیربکس دنده‌ای (75W80, 75W85, 75W90, 85W90, 85W140)
    m_gear = re.search(r"(?<!\d)(75|80|85)\s*[Ww/\-]\s*(80|85|90|140)(?!\d)", u)
    if m_gear:
        g_code = f"{m_gear.group(1)}W{m_gear.group(2)}"
        if g_code == "80W90":
            return "85W90"
        if g_code in _SPECIAL_OIL_SPECS:
            return g_code

    # تشخیص گرانروی موتور (0W20, 0W30, 0W40, 5W20, 5W30, 5W40, 10W30, 10W40, 15W40, 20W50)
    m = re.search(r"(?<!\d)(0|5|10|15|20)\s*[Ww/\-]\s*(20|30|40|50|60)(?!\d)", u)
    if m:
        base_g = f"{m.group(1)}W{m.group(2)}"
        if any(k in low for k in ("دیزل", "دیزلی", "کامیون", "کشنده", "20 لیتر", "بیست لیتر")):
            d_code = f"{base_g}-D"
            if d_code in _SPECIAL_OIL_SPECS:
                return d_code
        return base_g

    return None


def resolve_oil_spec(code: str) -> Dict[str, Any]:
    """برگرداندن مشخصات جستجو و فیلترینگ برای هر کد روغن"""
    if code in _SPECIAL_OIL_SPECS:
        return {"code": code, **_SPECIAL_OIL_SPECS[code]}
    return {
        "code": code,
        "kind": "gasoline",
        "grade": code,
        "title_fa": f"روغن موتور بنزینی {code}",
        "vol_label": "گالن ۴ تا ۵ لیتری",
        "queries": (f"روغن موتور {code} 4 لیتری", f"روغن موتور خودرو {code}"),
        "dk_q": f"روغن موتور {code}",
    }


def matches_oil_spec(title: str, spec: Dict[str, Any]) -> bool:
    """تطبیق سخت‌گیرانه عنوان محصول با نوع و گرانروی انتخابی"""
    t_up = clean_search_text(title).upper()
    t_low = t_up.lower()
    kind = spec["kind"]
    grade = spec["grade"]

    if any(b in t_low for b in _COMMON_BULK_BAD):
        return False

    if kind == "gasoline":
        if "روغن" not in t_low and "oil" not in t_low:
            return False
        if any(b in t_low for b in _NON_GASOLINE_BAD):
            return False
        if "دیزلی" in t_low or "دیزل" in t_low or "20 لیتر" in t_low:
            return False
        m_g = re.match(r"^(\d+)W(\d+)$", grade)
        if not m_g:
            return False
        return bool(re.search(rf"(?<!\d){m_g.group(1)}\s*W\s*[\-/\s]?\s*{m_g.group(2)}(?!\d)", t_up))

    if kind == "diesel":
        if "روغن" not in t_low and "oil" not in t_low:
            return False
        if any(k in t_low for k in ("موتورسیکلت", "موتور سیکلت", "گیربکس", "هیدرولیک", "ترمز", "ضد یخ", "فیلتر")):
            return False
        m_g = re.match(r"^(\d+)W(\d+)$", grade)
        if not m_g:
            return False
        if not re.search(rf"(?<!\d){m_g.group(1)}\s*W\s*[\-/\s]?\s*{m_g.group(2)}(?!\d)", t_up):
            return False
        return any(k in t_low for k in ("دیزل", "20 لیتر", "20لیتر", "بیست لیتر", "ci-4", "ch-4", "e7", "سنگین", "کامیون"))

    if kind == "diesel_single":
        num = "40" if "40" in grade else "50"
        if "روغن" not in t_low or any(k in t_low for k in ("گیربکس", "هیدرولیک", "ترمز", "ضد یخ", "موتورسیکلت")):
            return False
        return bool(re.search(rf"(?:SAE\s*|تک\s*درجه\s*|دیزل\s*){num}(?!\d)", t_up))

    if kind == "gear_manual":
        if any(k in t_low for k in ("روغن موتور", "موتورسیکلت", "ترمز", "ضد یخ", "هیدرولیک", "گریس")):
            return False
        m_g = re.match(r"^(\d+)W(\d+)$", grade)
        if not m_g:
            return False
        return bool(re.search(rf"(?<!\d){m_g.group(1)}\s*W\s*[\-/\s]?\s*{m_g.group(2)}(?!\d)", t_up))

    if kind == "gear_auto":
        if "روغن" not in t_low and "oil" not in t_low and "atf" not in t_low and "cvt" not in t_low and "dct" not in t_low:
            return False
        if any(k in t_low for k in ("روغن موتور", "ترمز", "ضد یخ", "گریس", "فیلتر", "کیت", "صافی")):
            return False
        if grade == "CVT":
            return "CVT" in t_up
        if grade == "DCT":
            return any(k in t_up for k in ("DCT", "DSG", "دوکلاچه", "دو کلاچه"))
        return any(k in t_up for k in ("ATF", "AL4", "اتومات")) and "هیدرولیک" not in t_low

    if kind == "hydraulic":
        return "هیدرولیک" in t_low and ("روغن" in t_low or "فرمان" in t_low) and "فیلتر" not in t_low and "پمپ" not in t_low

    if kind == "brake":
        if "ترمز" not in t_low or any(k in t_low for k in ("لنت", "دیسک", "پمپ", "شیلنگ", "کاسه")):
            return False
        num = "4" if grade == "DOT4" else "3"
        return bool(re.search(rf"DOT\s*{num}|دات\s*{num}", t_up))

    if kind == "antifreeze":
        return ("ضد یخ" in t_low or "ضدیخ" in t_low) and not any(k in t_low for k in ("شیشه شور", "اسپری", "مکمل سوخت"))

    if kind == "moto":
        if not any(k in t_low for k in ("موتورسیکلت", "موتور سیکلت", "موتوربایک", "اسکوتر", "هوندا", "motorbike", "4t")):
            return False
        m_g = re.match(r"^(\d+)W(\d+)$", grade)
        if not m_g:
            return False
        return bool(re.search(rf"(?<!\d){m_g.group(1)}\s*W\s*[\-/\s]?\s*{m_g.group(2)}(?!\d)", t_up))

    return False


def detect_oil_volume(title: str) -> Optional[float]:
    """تشخیص دقیق حجم مایع به لیتر"""
    t = clean_search_text(title).lower()
    if re.search(r"(?<!\d)20\s*(?:لیتر|ليتر|لیتری|ليتری|l\b|lit)", t):
        return 20.0
    for pat, val in (
        (r"(?<!\d)4[./]5\s*(?:لیتر|ليتر|لیتری|ليتری|l\b|lit)", 4.5),
        (r"(?<!\d)3[./]5\s*(?:لیتر|ليتر|لیتری|ليتری|l\b|lit)", 3.5),
        (r"(?<!\d)2[./]5\s*(?:لیتر|ليتر|لیتری|ليتری|l\b|lit)", 2.5),
        (r"(?<!\d)5\s*(?:لیتر|ليتر|لیتری|ليتری|l\b|lit)", 5.0),
        (r"(?<!\d)4\s*(?:لیتر|ليتر|لیتری|ليتری|l\b|lit)", 4.0),
        (r"(?<!\d)2\s*(?:لیتر|ليتر|لیتری|ليتری|l\b|lit)", 2.0),
        (r"(?<!\d)1\s*(?:لیتر|ليتر|لیتری|ليتری|l\b|lit)", 1.0),
        (r"(?<!\d)(?:0[./]5|500\s*(?:میلی|ml|سی\s*سی))", 0.5),
        (r"(?:چهار|۴)\s*(?:لیتر|ليتر|لیتری)", 4.0),
        (r"(?:پنج|۵)\s*(?:لیتر|ليتر|لیتری)", 5.0),
        (r"(?:دو|۲)\s*(?:لیتر|ليتر|لیتری)", 2.0),
        (r"(?:یک|۱)\s*(?:لیتر|ليتر|لیتری)", 1.0),
        (r"(?:بیست|۲۰)\s*(?:لیتر|ليتر|لیتری)", 20.0),
    ):
        if re.search(pat, t):
            return val
    return None


def detect_oil_api_level(title: str) -> str:
    """تشخیص سطح کیفیت API / استاندارد محصول"""
    t = clean_search_text(title).upper()
    for lvl in ("CI-4", "CH-4", "CK-4", "GL-5", "GL-4", "DOT4", "DOT3", "DEXRON VI", "DEXRON III", "SP", "SN PLUS", "SN", "SM", "SL", "SJ", "SG"):
        if re.search(rf"(?<![A-Z0-9]){re.escape(lvl)}(?![A-Z0-9])", t):
            return lvl
    return ""


def detect_oil_brand(title: str) -> Tuple[str, str]:
    """تشخیص برند روغن و تفکیک ایرانی (IR) از خارجی/وارداتی (IMP)"""
    t = clean_search_text(title).lower()
    iranian = (
        ("بهران", ("بهران", "behran", "رانا", "سوپرپیشتاز", "سوپر پیشتاز", "پیشتاز", "تکتاز", "سمند", "توربو دیزل")),
        ("ایرانول", ("ایرانول", "iranol", "رونیا", "ریسینگ")),
        ("اسپیدی", ("اسپیدی", "speedy", "پلاتینیوم", "سوپرپاور")),
        ("نفت پارس", ("پارس", "pars", "سوپرپایا", "سوپر پایا", "سوپرپیشرو", "سوپر پیشرو", "پایا")),
        ("کاسپین", ("کاسپین", "caspian")),
        ("بهتام", ("بهتام", "behtam", "کوانتیک")),
        ("فلومکس", ("فلومکس", "flomax", "فلو مکس")),
        ("سپاهان", ("سپاهان", "sepahan")),
        ("پترونول", ("پترونول", "petronol")),
        ("اپتیمکس", ("اپتیمکس", "optimax")),
        ("فومن شیمی", ("فومن شیمی", "fuman")),
        ("آیساکو / سایپا", ("ایساکو", "آیساکو", "سایپا", "پارس خودرو")),
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
        ("هیوندای اکستیر", ("اکستیر", "xteer", "هیوندای", "موبیس")),
        ("کیکس", ("کیکس", "kixx")),
        ("زیگ", ("زیگ", "zic")),
        ("مگل", ("مگل", "megol", "مگوین")),
        ("فوسر", ("فوسر", "fosser")),
        ("مانول / موتول", ("مانول", "موتول", "mannol", "motul")),
        ("پتروکانادا / کانادا", ("کانادا", "canada")),
        ("پونته میلانو", ("پونته", "میلانو", "ponte")),
        ("والوالین", ("والوالین", "valvoline")),
        ("آیسین / میتاسو", ("آیسین", "ایسین", "aisin", "میتاسو", "mitasu")),
        ("تویوتا / لکسوس", ("تویوتا", "toyota", "لکسوس")),
        ("فوکس / پنتوسین", ("فوکس", "fuchs", "پنتوسین")),
    )
    for name, kws in foreign:
        for kw in kws:
            if kw in t:
                return name, "IMP"

    return "سایر برندها", "IR"


def is_valid_oil_price(price_toman: int, kind: str, volume: Optional[float]) -> bool:
    """اعتبارسنجی بازه قیمت واقعی هر دسته روغن"""
    if kind in ("diesel", "diesel_single"):
        if volume == 20.0:
            return 2_500_000 <= price_toman <= 140_000_000
        return 400_000 <= price_toman <= 140_000_000
    if kind == "gasoline":
        if volume == 1.0:
            return 120_000 <= price_toman <= 5_000_000
        return 450_000 <= price_toman <= 30_000_000
    if kind in ("gear_manual", "gear_auto"):
        return 120_000 <= price_toman <= 40_000_000
    if kind in ("hydraulic", "antifreeze"):
        return 80_000 <= price_toman <= 8_000_000
    if kind == "brake":
        return 60_000 <= price_toman <= 5_000_000
    if kind == "moto":
        return 90_000 <= price_toman <= 4_500_000
    return 80_000 <= price_toman <= 50_000_000


class OilPriceClient:
    """
    موتور جامع استعلام زنده قیمت و خرید آنلاین انواع روغن خودرو (موتور بنزینی، دیزلی،
    گیربکس دنده‌ای/اتوماتیک، هیدرولیک، ترمز، ضدیخ و موتورسیکلت) از دیجی‌کالا، ترب و باسلام
    """

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._torob_blocked_until: float = 0.0

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(limit=30, ssl=False)
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

    async def _fetch_digikala_oils(self, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
        session = await self.get_session()
        offers: List[Dict[str, Any]] = []
        seen_ids = set()
        dk_q = spec["dk_q"]
        kind = spec["kind"]

        async def _query_brand(brand_slug: str):
            try:
                async with session.get(
                    f"https://api.digikala.com/v1/brands/{brand_slug}/search/",
                    params={"q": dk_q, "page": 1},
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
                if not matches_oil_spec(full_t, spec):
                    continue
                dv = p.get("default_variant") or {}
                price_rial = (dv.get("price") or {}).get("selling_price")
                if not price_rial:
                    continue
                price_toman = int(price_rial) // 10
                vol = detect_oil_volume(full_t)
                if not is_valid_oil_price(price_toman, kind, vol):
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

    async def _fetch_torob_oils(self, spec: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
        if time.monotonic() < self._torob_blocked_until:
            return [], "rate_limited"
        session = await self.get_session()
        offers: List[Dict[str, Any]] = []
        seen_keys = set()
        rate_limited = False
        kind = spec["kind"]

        for q in spec["queries"]:
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
                        if not matches_oil_spec(title, spec):
                            continue
                        price_toman = int(item.get("price") or 0)
                        vol = detect_oil_volume(title)
                        if not is_valid_oil_price(price_toman, kind, vol):
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

    async def _fetch_basalam_oils(self, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
        session = await self.get_session()
        offers: List[Dict[str, Any]] = []
        seen_ids = set()
        kind = spec["kind"]

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

        responses = await asyncio.gather(*[_query(q) for q in spec["queries"]])
        for data in responses:
            for p in data.get("products") or []:
                pid = p.get("id")
                if not pid or pid in seen_ids or p.get("stock", 1) == 0:
                    continue
                title = clean_search_text(p.get("name") or "")
                if not matches_oil_spec(title, spec):
                    continue
                price_rial = int(p.get("price") or 0)
                price_toman = price_rial // 10 if price_rial > 400_000 else price_rial
                vol = detect_oil_volume(title)
                if not is_valid_oil_price(price_toman, kind, vol):
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
        """استعلام زنده و دقیق قیمت روز هر نوع روغن خودرو"""
        code = normalize_oil_grade(raw_grade)
        if not code:
            return {"ok": False, "error": "نوع یا گرانروی روغن نامعتبر است."}

        spec = resolve_oil_spec(code)
        now_info = get_tehran_now()
        if not force_refresh and code in self._cache:
            exp_ts, cached_res = self._cache[code]
            if time.monotonic() < exp_ts:
                cp = dict(cached_res)
                cp["timestamp"] = now_info
                cp["cached"] = True
                return cp

        t0 = time.perf_counter()
        dk_res, torob_res, bs_res = await asyncio.gather(
            self._fetch_digikala_oils(spec),
            self._fetch_torob_oils(spec),
            self._fetch_basalam_oils(spec),
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
        deduped: List[Dict[str, Any]] = []
        seen_sig = set()
        for off in combined:
            sig = (off["source"], off["shop_name"], off["brand"], off["price_toman"], off["volume"])
            if sig not in seen_sig:
                seen_sig.add(sig)
                deduped.append(off)

        kind = spec["kind"]
        target_vol_label = spec["vol_label"]
        if kind in ("diesel", "diesel_single"):
            main_pool = [o for o in deduped if o["volume"] == 20.0]
            if len(main_pool) < 2:
                main_pool = deduped
            else:
                target_vol_label = "گالن ۲۰ لیتری (دیزلی)"
        elif kind == "gasoline":
            main_pool = [o for o in deduped if o["volume"] in (3.5, 4.0, 4.5, 5.0)]
            if len(main_pool) < 3:
                main_pool = [o for o in deduped if o["volume"] != 1.0] or deduped
        else:
            main_pool = deduped

        ir_offers = sorted([o for o in main_pool if o["origin"] == "IR"], key=lambda x: x["price_toman"])
        imp_offers = sorted([o for o in main_pool if o["origin"] != "IR"], key=lambda x: x["price_toman"])

        def _drop_outliers(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            if len(items) < 4:
                return items
            med = items[len(items) // 2]["price_toman"]
            return [x for x in items if int(med * 0.4) <= x["price_toman"] <= int(med * 2.5)]

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
            "grade": code,
            "title_fa": spec["title_fa"],
            "kind": kind,
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
            self._cache[code] = (time.monotonic() + 60.0, result)
        return result
