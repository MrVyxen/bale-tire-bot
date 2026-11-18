import html
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_WEEKDAYS_FA = [
    "دوشنبه",
    "سه‌شنبه",
    "چهارشنبه",
    "پنج‌شنبه",
    "جمعه",
    "شنبه",
    "یکشنبه",
]
_MONTHS_FA = [
    "",
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
]


def persian_to_english_digits(text: str) -> str:
    if not text:
        return ""
    return text.translate(_PERSIAN_DIGITS)


def escape_html(text: str) -> str:
    return html.escape(str(text or ""), quote=False)


def format_toman(amount: int | float) -> str:
    try:
        return f"{int(round(float(amount))):,}"
    except Exception:
        return "0"


def format_short_million(amount: int | float) -> str:
    try:
        m = float(amount) / 1_000_000
        return f"{m:.1f}م" if m < 100 else f"{int(round(m))}م"
    except Exception:
        return "-"


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> Tuple[int, int, int]:
    """تبدیل دقیق تاریخ میلادی به شمسی (بدون نیاز به کتابخانه خارجی)"""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666
        + (365 * gy)
        + ((gy2 + 3) // 4)
        - ((gy2 + 99) // 100)
        + ((gy2 + 399) // 400)
        + gd
        + g_d_m[gm - 1]
    )
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def get_tehran_now() -> dict:
    """زمان و تاریخ دقیق لحظه‌ای به وقت رسمی تهران (UTC+03:30)"""
    now = datetime.now(timezone.utc).astimezone(TEHRAN_TZ)
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    weekday = _WEEKDAYS_FA[now.weekday()]
    date_num = f"{jy:04d}/{jm:02d}/{jd:02d}"
    date_words = f"{jd} {_MONTHS_FA[jm]} {jy}"
    time_hm = now.strftime("%H:%M")
    time_hms = now.strftime("%H:%M:%S")
    return {
        "date_num": date_num,
        "date_words": date_words,
        "weekday": weekday,
        "time_hm": time_hm,
        "time_hms": time_hms,
        "full_fa": f"{weekday} {date_words} — ساعت {time_hms}",
        "compact_fa": f"{date_num} | ساعت {time_hm}",
    }


def clean_search_text(text: str) -> str:
    """نرمال‌سازی اعداد فارسی/عربی و کاراکترهای نیم‌فاصله برای تطبیق دقیق متنی"""
    t = persian_to_english_digits(text or "")
    t = t.replace("\u200c", " ").replace("\u200f", " ").replace("\u202b", " ").replace("\u202c", " ")
    t = t.replace("ي", "ی").replace("ك", "ک")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def parse_size_parts(raw: str) -> Optional[Tuple[str, str, str]]:
    """
    استخراج دقیق سه‌گانه سایز تایر (متریک و اینچی باری/کامیونی):
    - متریک: 185/65R14 , 185_65_14 , 295/80R22.5 -> ('185', '65', '14')
    - اینچی باری/سنگین: 7.50R16 , 8.25-16 , 12.00R24 -> ('7.50', 'INCH', '16')
    """
    if not raw:
        return None
    s = clean_search_text(raw).upper()
    m = re.search(
        r"(?<!\d)(\d{3})\s*[/_\-\s]\s*(\d{2})\s*[Rr/\-_\s]*\s*(\d{2}(?:\.\d)?)(?!\d)",
        s,
    )
    if m:
        w, a, r = m.group(1), m.group(2), m.group(3)
        if 135 <= int(w) <= 450 and 25 <= int(a) <= 95:
            try:
                rim_f = float(r)
                if 10 <= rim_f <= 26:
                    return w, a, r
            except ValueError:
                pass

    # الگوی سایزهای اینچی باری، نیسان، خاور و کامیون (مثل 7.50R16، 8.25R16، 12.00R24)
    m_inch = re.search(
        r"(?<!\d)(\d{1,2}\.\d{2})\s*(?:_?R_?|[Rr/\-\s]+)\s*(\d{2}(?:\.\d)?)(?!\d)",
        s,
    )
    if m_inch:
        w_in, r_in = m_inch.group(1), m_inch.group(2)
        try:
            wf, rf = float(w_in), float(r_in)
            if 5.5 <= wf <= 14.5 and 12 <= rf <= 26:
                return w_in, "INCH", r_in
        except ValueError:
            pass
    return None


def normalize_tire_size(raw: str) -> Optional[str]:
    """تبدیل هر فرمت ورودی تایر به فرمت استاندارد 185/65R14 یا 7.50R16"""
    parts = parse_size_parts(raw)
    if not parts:
        return None
    w, a, r = parts
    if a == "INCH":
        return f"{w}R{r}"
    return f"{w}/{a}R{r}"


def size_to_key(raw: str) -> str:
    """تبدیل 185/65R14 به 185_65_14 و 7.50R16 به 7.50_R_16"""
    parts = parse_size_parts(raw)
    if parts:
        if parts[1] == "INCH":
            return f"{parts[0]}_R_{parts[2]}"
        return f"{parts[0]}_{parts[1]}_{parts[2]}"
    return re.sub(r"[^0-9A-Za-z._]", "_", clean_search_text(raw))


def key_to_size(key: str) -> str:
    """تبدیل کلید دیتابیس 185_65_14 به 185/65R14 یا 7.50_R_16 به 7.50R16"""
    norm = normalize_tire_size(key)
    if norm:
        return norm
    if "_" in key and len(key.split("_")) == 2:
        return key.replace("_", "-")
    return key


def matches_exact_tire_size(text: str, width: str, aspect: str, rim: str) -> bool:
    """
    تطبیق سخت‌گیرانه سایز تایر در عنوان محصول برای جلوگیری از تداخل سایزهای مشابه
    پشتیبانی از هر دو فرمت متریک (185/65R14) و اینچی باری (7.50R16, 12.00R24)
    """
    t = clean_search_text(text).upper()
    if aspect == "INCH":
        w_esc = re.escape(width)
        w_nodot = width.replace(".", "")
        r_esc = re.escape(rim)
        inch_pat = rf"(?<!\d)(?:{w_esc}|{w_nodot})\s*(?:[Rr/\-\s]*)\s*{r_esc}(?!\d)"
        return bool(re.search(inch_pat, t))

    w, a, r = re.escape(width), re.escape(aspect), re.escape(rim)

    # 1. الگوی استاندارد: 185/65R14 یا 185/65 R 14 یا 185-65-14 یا 185 65 14
    std_pat = rf"(?<!\d){w}\s*[/\-_\s]\s*{a}\s*(?:[RrZz]{{0,2}}\s*[/\-_\s]*|[RrZz]\s*){r}(?!\d)"
    if re.search(std_pat, t):
        return True

    # 2. الگوی توصیفی دیجی‌کالا: پهنای 185 ... فاق 65 ... رینگ 14
    has_w = re.search(rf"پهنا[ی]?\s*(?:تایر\s*)?(?::\s*)?{w}(?!\d)", t)
    has_a = re.search(rf"فاق\s*(?::\s*)?{a}(?!\d)", t)
    has_r = re.search(rf"رینگ\s*(?::\s*)?{r}(?!\d)", t)
    if has_w and has_a and has_r:
        return True

    return False


_BAD_KEYWORDS = (
    "والف",
    "والو",
    "درپوش",
    "زنجیر چرخ",
    "زنجیر",
    "اسپری",
    "واکس",
    "پولیش",
    "تعمیر",
    "پنچر",
    "آچار",
    "جک ",
    "پمپ باد",
    "کاور لاستیک",
    "روکش",
    "کفپوش",
    "لاستیک موتور",
    "موتورسیکلت",
    "دوچرخه",
    "مینیاتوری",
    "اسباب بازی",
    "ماکت",
    "دورفرمان",
    "تیوپ",
    "رینگ اسپرت",
    "رینگ آلومینیومی",
    "رینگ فولادی",
)


def is_valid_car_tire_listing(title: str, price_toman: int) -> bool:
    """حذف لوازم جانبی غیرمرتبط و قیمت‌های نامعتبر/فیک"""
    if price_toman < 1_500_000 or price_toman > 350_000_000:
        return False
    t = clean_search_text(title).lower()
    for bad in _BAD_KEYWORDS:
        if bad in t:
            return False
    return True


def detect_tire_pack_count(title: str) -> Optional[int]:
    """
    تشخیص دقیق تعداد حلقه درج‌شده در عنوان محصول:
    خروجی: 1، 2، 4 یا None (در صورتی که فروشنده در عنوان تعداد را ذکر نکرده باشد)
    """
    t = clean_search_text(title)
    # بررسی صریح ۴ حلقه یا دو جفت
    if (
        re.search(r"(?:4|چهار)\s*(?:حلقه|عددی?|تایی|تا)", t)
        or "ست چهار" in t
        or "ست 4" in t
        or "دو جفت" in t
        or "2 جفت" in t
    ):
        return 4
    # بررسی صریح ۲ حلقه یا هر نوع عبارت جفت
    if (
        re.search(r"(?:2|دو)\s*(?:حلقه|عددی?|تایی|تا)", t)
        or re.search(r"تعداد\s*(?::|\s)\s*2(?!\d)", t)
        or re.search(r"\bجفت(?:ی)?\b", t)
        or "(جفت" in t
        or "جفت)" in t
        or "جفتی" in t
    ):
        return 2
    # بررسی صریح تک حلقه / هر حلقه
    if (
        re.search(r"(?:1|یک)\s*(?:حلقه|عددی?)", t)
        or "تک حلقه" in t
        or "قیمت حلقه" in t
        or "هر حلقه" in t
        or "تکی" in t
        or "(تک)" in t
    ):
        return 1
    return None


def detect_tire_brand(title: str) -> Tuple[str, str]:
    """
    تشخیص دقیق برند لاستیک و دسته‌بندی ایرانی / خارجی
    خروجی: (نام برند فارسی, 'IR' | 'IMP')
    نکته هوشمند: نام خودروهایی مثل «دنا پلاس» یا «پژو پارس» با برند «دنا تایر» اشتباه گرفته نمی‌شود.
    """
    t = clean_search_text(title).lower()
    # حذف عبارات رایج اسم خودرو از متن تطبیق برند تا تداخل ایجاد نشود
    t_brand = re.sub(r"(?:پژو\s*پارس|دنا\s*پلاس|دنا\s*اتومات|تارا|شاهین|پراید|تیبا|ساینا|کوییک|سمند|رانا)", " ", t)

    iranian = [
        ("بارز", ("بارز", "barez")),
        ("کویر تایر", ("کویر", "kavir")),
        ("یزد تایر", ("یزد", "yazd", "yric")),
        ("ایران تایر", ("ایران تایر", "ایران‌تایر", "irantire", "iran tire")),
        ("گلدستون / آرتاویل", ("گلدستون", "آرتاویل", "goldstone", "artawheel")),
        ("رازی تایر", ("رازی", "razi")),
        ("دنا تایر", ("دنا تایر", "دناتایر", "لاستیک دنا", "تایر دنا", "dena tire", "dena-tire")),
        ("کیان تایر (البرز)", ("کیان تایر", "البرز", "kiantire", "kian tire")),
        ("پارسیان تایر", ("پارسیان تایر", "پارسیان‌تایر")),
    ]
    for label, kws in iranian:
        for kw in kws:
            if kw in t_brand:
                return label, "IR"

    foreign = [
        ("نکسن", ("نکسن", "nexen")),
        ("کومهو", ("کومهو", "kumho")),
        ("هانکوک", ("هانکوک", "hankook")),
        ("لاوفن", ("لاوفن", "لافن", "laufenn")),
        ("دانلوپ", ("دانلوپ", "dunlop")),
        ("تویو", ("تویو", "toyo")),
        ("گودیر", ("گودیر", "goodyear")),
        ("ترازانو", ("ترازانو", "ترزانو", "trazano")),
        ("ترافلکس", ("ترافلکس", "ترا فلکس", "traflex")),
        ("چائویانگ", ("چائویانگ", "چائو یانگ", "chaoyang")),
        ("هابیلد", ("هابیلد", "هابیلید", "هبیلد", "habilead")),
        ("رودکروزا", ("رودکروزا", "roadcruza")),
        ("ترایانگل", ("ترایانگل", "تریانگل", "triangle")),
        ("کندا", ("کندا", "kenda")),
        ("جی‌تی رادیال", ("جی تی", "جی‌تی", "gt radial")),
        ("مارشال", ("مارشال", "marshal")),
        ("وست لیک", ("وست لیک", "وستلیک", "westlake")),
        ("رودستون", ("رودستون", "roadstone")),
        ("کپسن", ("کپسن", "kapsen")),
        ("هانمیکس", ("هانمیکس", "hanmix")),
        ("سنترا / سنچوری", ("سنترا", "سنچوری", "sentury", "centara")),
        ("فالکن / فالکون", ("فالکن", "فالکون", "falken")),
        ("لینگ‌لانگ", ("لینگ لانگ", "لینگلانگ", "linglong")),
        ("تیگار / رایکن", ("تیگار", "tigar", "ریکن", "رایکن", "riken")),
        ("لاسا", ("لاسا", "lassa")),
        ("یوکوهاما", ("یوکوهاما", "yokohama")),
        ("بریجستون", ("بریجستون", "bridgestone")),
        ("میشلن", ("میشلن", "michelin")),
        ("کانتیننتال", ("کانتیننتال", "continental")),
        ("پیرلی", ("پیرلی", "pirelli")),
        ("لانگ مارچ", ("لانگ مارچ", "longmarch")),
        ("مکسس", ("مکسس", "مکسیس", "maxxis")),
        ("سایلون", ("سایلون", "سایلو", "sailun")),
        ("آنایت", ("آنایت", "آنیت", "annaite")),
        ("وانلی", ("وانلی", "وان لی", "wanli")),
        ("جی پلنت", ("جی پلنت", "جینیو", "jinyu", "g-planet")),
        ("بوتو", ("بوتو", "boto")),
        ("وایدر", ("وایدر", "widerway")),
        ("بلک لیون / گرین لندر", ("بلک لیون", "گرین لندر", "blacklion", "grenlander")),
    ]
    for label, kws in foreign:
        for kw in kws:
            if kw in t_brand:
                return label, "IMP"

    return "سایر برندها", "IMP"


def is_valid_iran_national_id(code: str) -> bool:
    """اعتبارسنجی ریاضی کد ملی ۱۰ رقمی ایران (رقم کنترل واقعی + رد ارقام تکراری)"""
    cleaned = re.sub(r"\D", "", persian_to_english_digits(code or ""))
    if len(cleaned) != 10 or len(set(cleaned)) == 1:
        return False
    check = int(cleaned[9])
    total = sum(int(cleaned[i]) * (10 - i) for i in range(9))
    rem = total % 11
    return (rem < 2 and check == rem) or (rem >= 2 and check == 11 - rem)


def detect_car_from_text(text: str, car_catalog: dict) -> Optional[str]:
    """تشخیص هوشمند کلید خودرو از روی متن تایپ‌شده کاربر (مثل 'پژو ۲۰۶'، 'پراید'، 'دنا' و...)"""
    t = clean_search_text(text).lower()
    if not t or len(t) > 60:
        return None
    for car_key, info in car_catalog.items():
        for kw in info.get("keywords", ()):
            kw_norm = clean_search_text(kw).lower()
            if kw_norm and kw_norm in t:
                return car_key
    return None
