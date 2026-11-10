# ربات هوشمند تایر دولتی و استعلام قیمت روز بازار آزاد (`@tairbot`)

دستیار هوشمند و فوق‌سریع پیام‌رسان بله برای **رصد خودکار و خرید لاستیک دولتی** از تمامی شرکت‌ها و درگاه‌های فروش ایران، به همراه **موتور استعلام زنده قیمت روز لاستیک آزاد** بر اساس تاریخ و ساعت دقیق تهران.

---

## ✨ قابلیت‌های کلیدی
1. **اتصال یکپارچه و خودکار به تمام ۱۰ شرکت و درگاه دولتی:**
   - گزینه **«🌐 همه شرکت‌ها (اسکن خودکار سراسری)»** به‌صورت هم‌زمان وضعیت و موجودی کارخانه‌ها و فروشگاه‌های **هایپرتایر دولتی، بارز، کویرتایر، ایران‌تایر، یزدتایر، رازی‌تایر، کیان‌تایر (البرز)، آرتاویل/گلدستون، دنا تایر و سامانه جامع تجارت (`ntsw.ir`)** را رصد می‌کند.
2. **نمایش سایز تایر صرفاً بر اساس موجودی واقعی سایت‌ها:**
   - هیچ سایز ثابت یا ساختگی نمایش داده نمی‌شود؛ منوی سایزها هر بار به‌صورت زنده انبار سایت‌ها را اسکن کرده و فقط سایزهای واقعاً موجود را به همراه قیمت و کارخانه نشان می‌دهد (به‌همراه لیست جداگانه کاتالوگ کارخانه‌ها برای پایش خودکار).
3. **استعلام لحظه‌ای و دقیق قیمت روز لاستیک آزاد (تک‌حلقه و جفت):**
   - با انتخاب سایز از منو یا **تایپ مستقیم هر سایز دلخواه** (مثل `185/65R14` یا `۲۰۵/۶۰/۱۵`) در چت، ربات هم‌زمان به **دیجی‌کالا، باسلام، هایپرتایر و ترب** متصل می‌شود.
   - اقلام متفرقه (والو، زنجیر، بیعانه، دست‌دوم) را حذف، تک‌حلقه را از بسته‌های جفتی و ۴تایی تفکیک، و بازه واقعی ایرانی و خارجی را همراه با ساعت دقیق تهران ارائه می‌دهد.
4. **شکارچی خودکار چندپورتالی و ورود پیامکی مستقیم:**
   - پایش هر ۳ ثانیه، پیش‌گرم‌سازی سوکت (`Keep-Alive`)، حذف هشدارهای DNS و پشتیبانی از ورود پیامکی بارز و کویرتایر.

---

## 📁 ساختار پروژه
- [config.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/config.py): تنظیمات توکن بله، لیست ۱۰ درگاه دولتی و سایزهای قیمت روز آزاد
- [database.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/database.py): پایگاه داده SQLite ناهمگام (`aiosqlite`) با مهاجرت خودکار نسخه کاربر
- [bale_api.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/bale_api.py): کلاینت بله با بازیابی خودکار در خطاهای قالب‌بندی
- [tire_api/utils.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/tire_api/utils.py): تاریخ شمسی و ساعت رسمی تهران، نرمال‌سازی سایز، تشخیص برند ایرانی/خارجی و تفکیک تعداد حلقه
- [tire_api/base_client.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/tire_api/base_client.py): کلاینت پایه HTTP با پیش‌بررسی امن DNS و Connection Pooling
- [tire_api/hypertire_client.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/tire_api/hypertire_client.py): اسکن زنده بخش تایر دولتی و آزاد هایپرتایر و رزرو سبد خرید
- [tire_api/barez_client.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/tire_api/barez_client.py): اسکن رینگ‌های ۱۳ تا ۱۸ بارز و ورود پیامکی
- [tire_api/kavir_client.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/tire_api/kavir_client.py) و [tire_api/kala_ntsw_client.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/tire_api/kala_ntsw_client.py): کلاینت کویرتایر و سامانه جامع تجارت (با تشخیص خودکار محدودیت آی‌پی ایران)
- [tire_api/multi_portal_client.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/tire_api/multi_portal_client.py): پایش کارخانه‌های ایران‌تایر، یزدتایر، رازی، کیان‌تایر، آرتاویل/گلدستون و دنا
- [tire_api/market_price_client.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/tire_api/market_price_client.py): موتور هوشمند استعلام زنده قیمت روز تایر آزاد
- [tire_api/sniper_engine.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/tire_api/sniper_engine.py): هسته مرکزی اسکن هم‌زمان و شکارچی چندپورتالی
- [tire_api/__init__.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/tire_api/__init__.py): صادرات یکپارچه ماژول‌ها و کلاینت‌های تایر
- [captcha_solver.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/captcha_solver.py): پیش‌پردازش و شفاف‌سازی تصاویر امنیتی (CAPTCHA) متصل به موتور شکارچی
- [bot_handlers.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/bot_handlers.py): رابط دکمه‌ای متقارن، مسیرهای پیوسته بدون بن‌بست و دستورات متنی سریع (`/start`, `/stock`, `/price`, `/sniper`, `/profile`, `/help`)
- [telemetry.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/telemetry.py): موتور آنالیز دقیق تاخیر (`P50/P95`)، آپتایم ۱۰ پورتال، عملکرد منابع آزاد و مصرف حافظه
- [dashboard_html.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/dashboard_html.py): داشبورد وب رصد زنده در مسیر `/dashboard`
- [main.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/main.py): نقطه شروع، وب‌سرور سلامت و آنالیز (`/dashboard`, `/status`)، لاگ چرخان و پروب فعال
- [monitor_realtime.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/monitor_realtime.py): سرویس مانیتورینگ لحظه‌ای سلامت، تغییرات موجودی و هشدار خطاها
- [analyze_logs.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/analyze_logs.py): گزارش‌گیر تحلیلی فوری از لاگ، دیتابیس و تله‌متری زنده
- [bot_ctl.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/bot_ctl.py) و [run.bat](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/run.bat): مرکز کنترل واحد برای روشن/خاموش کردن ربات، مانیتورینگ، داشبورد وب و ممیزی یکپارچگی

---

## 🚀 اجرا و آزمایش یکپارچه
راحت‌ترین راه در ویندوز دابل‌کلیک روی `run.bat` یا استفاده از دستورات زیر است:
```bash
python bot_ctl.py start     # روشن کردن ربات + مانیتورینگ لحظه‌ای
python bot_ctl.py dashboard # باز کردن داشبورد زنده (http://127.0.0.1:10000/dashboard)
python bot_ctl.py status    # گزارش تحلیلی جامع (لاگ + دیتابیس + سرور زنده)
python bot_ctl.py check     # ممیزی خودکار اتصال فایل‌ها و دکمه‌ها
python bot_ctl.py test      # اجرای تست کامل End-to-End
python bot_ctl.py stop      # توقف کامل ربات و مانیتورینگ
```
سپس در پیام‌رسان بله به ربات **`@tairbot`** بروید و `/start` را بزنید.
