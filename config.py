import os
from pathlib import Path

# مسیر پروژه
BASE_DIR = Path(__file__).resolve().parent

# تنظیمات ربات بله
BOT_TOKEN = os.getenv("BALE_BOT_TOKEN", "867906633:IcjuDU147iZrdlKq9kRfNbCD_edEginX3_U")
BALE_BASE_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"

# پایگاه داده
DB_PATH = BASE_DIR / "tire_bot.db"

# سامانه‌های پشتیبانی شده با آدرس‌های فعال روز
PORTALS = {
    "barez": {
        "title": "گروه صنعتی بارز (Barez)",
        "base_url": "https://shop.barez.org",
        "sale_hours": ["09:00", "10:00"]
    },
    "kavir": {
        "title": "کویر تایر (Kavir Tire)",
        "base_url": "https://kavirtire.ir",
        "sale_hours": ["09:30", "10:30"]
    },
    "ntsw": {
        "title": "سامانه تخصیص تایر جامع تجارت (NTSW)",
        "base_url": "https://kala.ntsw.ir",
        "sale_hours": ["08:00", "10:00"]
    }
}

# سایزهای استاندارد و پرتقاضای تایر سواری با تفکیک شیک
TIRE_SIZES = {
    "165_65_13": "🚗 165/65R13 (خانواده پراید)",
    "175_70_13": "🚙 175/70R13 (تیبا، ریو، پیکان)",
    "185_65_14": "🏎 185/65R14 (پژو ۲۰۶، ۲۰۷، ۴۰۵، پارس، رانا)",
    "185_65_15": "🚘 185/65R15 (سمند، ال۹۰، دنا، شاهین، ساندرو)",
    "205_60_14": "✨ 205/60R14 (پژو و رانا - پهن اسپرت)",
    "205_60_15": "✨ 205/60R15 (سمند و دنا - پهن اسپرت)",
    "205_55_16": "🌟 205/55R16 (تارا، سراتو، مگان، شاهین اتومات)",
}

# هدرهای شبیه‌سازی مرورگر واقعی با بالاترین سرعت و عبور از فایروال
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
    "Sec-Ch-Ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}
