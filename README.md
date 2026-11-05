# ربات ثبت‌نام فوق‌سریع لاستیک دولتی در بله (Tire Sniper Bot)

سیستم ثبت‌نام خودکار و فوق‌سریع سهمیه لاستیک دولتی با اتصال به پیام‌رسان بله و ارسال مستقیم درخواست‌های API بدون نیاز به مرورگر کند.

---

## ⚡ چرا این ربات بسیار سریع‌تر از انسان و ربات‌های معمولی است؟
1. **ارسال مستقیم به وب‌سرویس (Direct API Calls):** به جای باز کردن مرورگر (سلنیوم یا پلی‌رایت) که ۳ تا ۶ ثانیه زمان می‌برد، درخواست‌ها به صورت بسته باینری/JSON خام در **۱۰ تا ۵۰ میلی‌ثانیه** ارسال می‌شوند.
2. **پیش‌گرم‌سازی کانکشن (Keep-Alive):** سوکت‌های TCP از قبل باز و آماده هستند، بنابراین در لحظه باز شدن سهمیه، هیچ زمانی صرف ایجاد اتصال (TLS Handshake) نمی‌شود.
3. **پردازش و حل محلی کپچا با OpenCV:** تصویر کد امنیتی به جای معطلی برای تایپ دستی، توسط فیلترهای کنتراست محلی و مدل‌های پردازش تصویر در کسری از ثانیه آماده می‌گردد.
4. **شلیک در لحظه صفر (NTP Synchronized):** هماهنگ با سرورهای زمانی جهت ارسال بسته در ثانیه `00:00`.

---

## 📁 ساختار پروژه
- [config.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/config.py): تنظیمات توکن بله، سایزهای تایر و هدرهای شبیه‌سازی مرورگر
- [database.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/database.py): پایگاه داده SQLite ناهمگام (aiosqlite) برای ذخیره اطلاعات خودرو و لاگ‌ها
- [bale_api.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/bale_api.py): کلاینت اختصاصی و سریع برای ارتباط با API پیام‌رسان بله
- [captcha_solver.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/captcha_solver.py): ماژول پیش‌پردازش و حذف نویز کپچا با OpenCV
- [tire_api/base_client.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/tire_api/base_client.py): کلاینت پایه با Connection Pooling و محاسبه تاخیر (Latency)
- [tire_api/kavir_client.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/tire_api/kavir_client.py): وب‌سرویس‌های اختصاصی کویر تایر
- [tire_api/barez_client.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/tire_api/barez_client.py): وب‌سرویس‌های اختصاصی گروه صنعتی بارز
- [tire_api/kala_ntsw_client.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/tire_api/kala_ntsw_client.py): وب‌سرویس‌های سامانه جامع تجارت (kala.ntsw.ir)
- [tire_api/sniper_engine.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/tire_api/sniper_engine.py): هسته موتور شکارچی خودکار (Auto-Sniper)
- [bot_handlers.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/bot_handlers.py): منوهای دکمه‌ای شیشه‌ای (Inline Keyboards) و دریافت مراحل ثبت مشخصات
- [main.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/main.py): نقطه شروع برنامه و حلقه دریافت پیام‌ها

---

## 🚀 نحوه اجرا
کافیست در پوشه پروژه فایل [run.bat](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/run.bat) را اجرا کرده یا در ترمینال دستور زیر را وارد نمایید:
```bash
python main.py
```
سپس در پیام‌رسان بله به ربات **`@tairbot`** رفته و دستور `/start` را ارسال فرمایید.
