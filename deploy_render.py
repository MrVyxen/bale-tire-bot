import json
import urllib.request
import urllib.error

RENDER_KEY = "rnd_Duj1JLoZehtNtcondAWBlvYOqgl1"
RENDER_OWNER_ID = "tea-ct92oru8ii6s73fpi9rg"
REPO_NAME = "bale-tire-bot"
GITHUB_USER = "MrVyxen"
BOT_TOKEN = "867906633:IcjuDU147iZrdlKq9kRfNbCD_edEginX3_U"

def render_request(method, endpoint, data=None):
    url = f"https://api.render.com/v1/{endpoint.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {RENDER_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"Render API Error [{e.code}]: {e.read().decode()}")
        return None

def main():
    print("=" * 60)
    print("🚀 ایجاد وب‌سرویس در Render برای مخزن MrVyxen/bale-tire-bot")
    print("=" * 60)

    # بررسی سرویس‌های موجود
    services = render_request("GET", "services?limit=50")
    service_id = None
    service_url = None

    if services:
        for item in services:
            svc = item.get("service", {})
            if svc.get("name") == REPO_NAME:
                service_id = svc.get("id")
                service_url = svc.get("serviceDetails", {}).get("url")
                print(f"سرویس از قبل موجود است: {service_id}")
                break

    if not service_id:
        create_payload = {
            "type": "web_service",
            "name": REPO_NAME,
            "ownerId": RENDER_OWNER_ID,
            "repo": f"https://github.com/{GITHUB_USER}/{REPO_NAME}",
            "branch": "main",
            "autoDeploy": "yes",
            "serviceDetails": {
                "env": "python",
                "plan": "free",
                "region": "frankfurt",
                "envSpecificDetails": {
                    "buildCommand": "pip install -r requirements.txt",
                    "startCommand": "python main.py"
                },
                "healthCheckPath": "/health",
                "envVars": [
                    {"key": "BALE_BOT_TOKEN", "value": BOT_TOKEN},
                    {"key": "PORT", "value": "10000"}
                ]
            }
        }
        res = render_request("POST", "services", create_payload)
        if res:
            service_id = res.get("id")
            service_url = res.get("serviceDetails", {}).get("url")
            print(f"✅ وب‌سرویس جدید در Render با موفقیت ساخته شد! (ID: {service_id})")
        else:
            print("❌ خطا در ساخت وب‌سرویس!")
            return

    # ارسال دستور استقرار و بیلد (Trigger Deploy)
    print("⏳ ارسال دستور بیلد و استقرار (Deploy)...")
    deploy_res = render_request("POST", f"services/{service_id}/deploys", {"clearCache": "clear"})
    if deploy_res:
        print(f"✅ بیلد با موفقیت استارت شد! (Deploy ID: {deploy_res.get('id')})")
    
    print("=" * 60)
    print(f"🌐 آدرس اینترنتی سرویس: {service_url}")
    print(f"📊 پنل مدیریت رندر: https://dashboard.render.com/web/{service_id}")
    print("=" * 60)

if __name__ == "__main__":
    main()
