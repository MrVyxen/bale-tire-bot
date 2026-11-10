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
- [bot_handlers.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/bot_handlers.py): رابط دکمه‌ای متقارن، زیبا و مدیریت تعامل با کاربر
- [main.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/main.py): نقطه شروع، وب‌سرور سلامت و مانیتورینگ (`/status`)، لاگ چرخان و حلقه دریافت پیام‌ها
- [monitor_realtime.py](file:///C:/Users/adltarabar/.gemini/antigravity/scratch/bale-tire-bot/monitor_realtime.py): سرویس مانیتورینگ لحظه‌ای سلامت، رویدادها و هشدار خطاها

---

## 🚀 اجرا و آزمایش
برای اجرای تست کامل End-to-End:
```bash
python test_e2e.py
```
و برای روشن کردن ربات:
```bash
python main.py
```
سپس در پیام‌رسان بله به ربات **`@tairbot`** بروید و `/start` را بزنید.
