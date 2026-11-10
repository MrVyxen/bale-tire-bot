DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>مرکز رصد و آنالیز لحظه‌ای ربات تایر (@tairbot)</title>
<style>
  :root {
    --bg: #0b1120;
    --card: #111827;
    --card-border: #1e293b;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --green: #10b981;
    --yellow: #f59e0b;
    --red: #ef4444;
    --blue: #38bdf8;
    --purple: #a78bfa;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: radial-gradient(circle at top right, #172554 0%, var(--bg) 55%);
    color: var(--text);
    font-family: Tahoma, "Vazirmatn", "Segoe UI", sans-serif;
    padding: 18px;
    line-height: 1.6;
  }
  .container { max-width: 1380px; margin: 0 auto; }
  .topbar {
    display: flex; flex-wrap: wrap; gap: 12px; justify-content: space-between; align-items: center;
    background: rgba(17, 24, 39, 0.88); border: 1px solid var(--card-border);
    border-radius: 14px; padding: 14px 20px; margin-bottom: 16px;
    backdrop-filter: blur(8px);
  }
  .brand { display: flex; align-items: center; gap: 12px; }
  .pulse {
    width: 12px; height: 12px; border-radius: 50%; background: var(--green);
    box-shadow: 0 0 12px var(--green); animation: ping 1.6s infinite;
  }
  .pulse.err { background: var(--red); box-shadow: 0 0 12px var(--red); }
  @keyframes ping { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.45; transform: scale(1.25); } }
  .title { font-size: 17px; font-weight: bold; }
  .meta { font-size: 12px; color: var(--muted); }
  .grid-kpi {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 12px; margin-bottom: 16px;
  }
  .kpi {
    background: var(--card); border: 1px solid var(--card-border);
    border-radius: 12px; padding: 14px 16px;
  }
  .kpi-label { font-size: 12px; color: var(--muted); }
  .kpi-val { font-size: 22px; font-weight: bold; margin-top: 4px; color: #f8fafc; }
  .kpi-sub { font-size: 11px; color: var(--blue); margin-top: 4px; }
  .grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(460px, 1fr)); gap: 16px; margin-bottom: 16px; }
  .panel {
    background: var(--card); border: 1px solid var(--card-border);
    border-radius: 14px; padding: 16px; overflow: hidden;
  }
  .panel h2 { font-size: 15px; margin-bottom: 12px; color: #f1f5f9; border-bottom: 1px solid var(--card-border); padding-bottom: 8px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { text-align: right; padding: 8px 6px; border-bottom: 1px solid #1e293b; }
  th { color: var(--muted); font-weight: normal; }
  .badge {
    display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: bold;
  }
  .b-ok { background: rgba(16, 185, 129, 0.16); color: var(--green); }
  .b-warn { background: rgba(245, 158, 11, 0.16); color: var(--yellow); }
  .b-err { background: rgba(239, 68, 68, 0.16); color: var(--red); }
  .b-info { background: rgba(56, 189, 248, 0.16); color: var(--blue); }
  .bar-wrap { background: #1e293b; height: 7px; border-radius: 99px; overflow: hidden; margin-top: 4px; }
  .bar-fill { height: 100%; background: linear-gradient(90deg, var(--blue), var(--purple)); }
  .feed { max-height: 290px; overflow-y: auto; font-size: 12px; }
  .feed-item { padding: 7px 8px; border-bottom: 1px solid #1e293b; display: flex; justify-content: space-between; gap: 10px; }
  .mono { font-family: Consolas, monospace; direction: ltr; display: inline-block; }
  @media (max-width: 600px) { .grid-2 { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div class="container">
  <div class="topbar">
    <div class="brand">
      <div id="connPulse" class="pulse"></div>
      <div>
        <div class="title">📊 مرکز رصد و آنالیز فوق‌دقیق ربات تایر (@<span id="botUser">tairbot</span>)</div>
        <div class="meta" id="tehranTime">در حال دریافت داده زنده...</div>
      </div>
    </div>
    <div class="meta">آپتایم: <b id="uptime">-</b> | به‌روزرسانی خودکار هر ۳ ثانیه</div>
  </div>

  <div class="grid-kpi" id="kpiGrid"></div>

  <div class="grid-2">
    <div class="panel">
      <h2>🏭 وضعیت و آنالیز کارخانه‌ها و سامانه‌های دولتی</h2>
      <table>
        <thead><tr><th>شرکت / سامانه</th><th>وضعیت</th><th>تاخیر</th><th>آپتایم</th><th>موجودی</th></tr></thead>
        <tbody id="portalsBody"></tbody>
      </table>
    </div>

    <div class="panel">
      <h2>💰 عملکرد منابع استعلام قیمت آزاد</h2>
      <table>
        <thead><tr><th>منبع</th><th>وضعیت</th><th>تعداد نتایج</th><th>تاخیر میانگین</th><th>نرخ موفقیت</th></tr></thead>
        <tbody id="sourcesBody"></tbody>
      </table>
      <h2 style="margin-top:16px">🎯 محبوب‌ترین عملیات و سایزها</h2>
      <div id="analyticsBars" style="font-size:12px;"></div>
    </div>
  </div>

  <div class="grid-2">
    <div class="panel">
      <h2>⚡ جریان لحظه‌ای رویدادهای ربات</h2>
      <div class="feed" id="eventsFeed"></div>
    </div>
    <div class="panel">
      <h2>🚨 خطاها و هشدارهای ثبت‌شده</h2>
      <div class="feed" id="errorsFeed"></div>
    </div>
  </div>
</div>

<script>
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function fmtSec(s) {
  s = Math.floor(Number(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return (h > 0 ? h + "س " : "") + (m > 0 ? m + "د " : "") + sec + "ث";
}
async function refresh() {
  try {
    const r = await fetch("/status", { cache: "no-store" });
    const d = await r.json();
    document.getElementById("botUser").textContent = d.bot_username || "tairbot";
    document.getElementById("tehranTime").textContent = d.tehran_now + " | شروع سرویس: " + d.started_tehran;
    document.getElementById("uptime").textContent = fmtSec(d.uptime_sec);
    const pulse = document.getElementById("connPulse");
    pulse.className = "pulse" + (d.connected ? "" : " err");

    const db = d.db_analytics || {};
    const perf = d.performance || {};
    const ps = d.portals_summary || {};
    const kpis = [
      ["وضعیت اتصال بله", d.connected ? "🟢 آنلاین" : "🔴 قطع", "پینگ بله: " + (d.bale_api_latency_ms || 0) + " ms"],
      ["کل پیام و کلیک‌ها", (d.total_updates || 0), "پیام: " + (d.total_messages || 0) + " | دکمه: " + (d.total_callbacks || 0)],
      ["کارایی پاسخ (P50 / P95)", (perf.p50_ms || 0) + " / " + (perf.p95_ms || 0) + " ms", "میانگین: " + (perf.avg_ms || 0) + " ms"],
      ["نرخ خطا و قطعی", (d.total_errors || 0) + " (" + (d.error_rate_pct || 0) + "%)", "تجدید Polling: " + (d.polling_reconnects || 0)],
      ["کاربران و شکارچی‌ها", (db.total_users ?? "-") + " کاربر", "آماده ثبت: " + (db.ready_profile_users ?? 0) + " | شکارچی فعال: " + (d.active_snipers_count || 0)],
      ["پورتال‌های دولتی", (ps.online_now || 0) + " / " + (ps.tracked || 0) + " آنلاین", "موجودی لحظه: " + (ps.in_stock_items_now || 0) + " مدل | RAM: " + (d.memory_mb || 0) + " MB"],
    ];
    document.getElementById("kpiGrid").innerHTML = kpis.map(k =>
      `<div class="kpi"><div class="kpi-label">${esc(k[0])}</div><div class="kpi-val">${esc(k[1])}</div><div class="kpi-sub">${esc(k[2])}</div></div>`
    ).join("");

    const portals = d.portals || [];
    document.getElementById("portalsBody").innerHTML = portals.length ? portals.map(p => {
      let badge = `<span class="badge b-err">آفلاین</span>`;
      if (p.in_stock_count > 0) badge = `<span class="badge b-ok">موجود (${esc(p.in_stock_count)})</span>`;
      else if (p.last_ok) badge = `<span class="badge b-warn">آنلاین/ناموجود</span>`;
      else if (p.vpn_blocked) badge = `<span class="badge b-info">نیاز به IP ایران</span>`;
      return `<tr>
        <td><b>${esc(p.title)}</b><div class="meta">${esc((p.status_desc || "").slice(0, 52))}</div></td>
        <td>${badge}</td>
        <td class="mono">${esc(p.last_latency_ms)} ms</td>
        <td class="mono">${esc(p.uptime_pct)}%</td>
        <td class="mono">${esc((p.in_stock_sizes || []).join(", ") || "-")}</td>
      </tr>`;
    }).join("") : `<tr><td colspan="5" class="meta">در انتظار اولین اسکن پورتال‌ها...</td></tr>`;

    const srcs = d.market_sources || [];
    document.getElementById("sourcesBody").innerHTML = srcs.length ? srcs.map(s => {
      const b = s.last_status === "ok" ? `<span class="badge b-ok">فعال</span>` :
                s.last_status === "rate_limited" ? `<span class="badge b-warn">محدود موقت</span>` : `<span class="badge b-err">خطا</span>`;
      return `<tr>
        <td><b>${esc(s.source)}</b></td><td>${b}</td>
        <td class="mono">${esc(s.last_count)}</td>
        <td class="mono">${esc(s.avg_latency_ms)} ms</td>
        <td class="mono">${esc(s.success_rate_pct)}%</td>
      </tr>`;
    }).join("") : `<tr><td colspan="5" class="meta">هنوز استعلام قیمت آزاد ثبت نشده است</td></tr>`;

    const acts = d.top_actions || [];
    const maxAct = acts.length ? acts[0][1] : 1;
    const sizes = d.top_searched_sizes || [];
    let barHtml = acts.slice(0, 5).map(([name, cnt]) =>
      `<div style="margin-bottom:8px"><div style="display:flex;justify-content:space-between"><span>${esc(name)}</span><b class="mono">${esc(cnt)}</b></div><div class="bar-wrap"><div class="bar-fill" style="width:${Math.round((cnt/maxAct)*100)}%"></div></div></div>`
    ).join("");
    if (sizes.length) {
      barHtml += `<div style="margin-top:10px" class="meta">سایزهای پرتقاضا: ` + sizes.map(([sz, c]) => `<span class="badge b-info mono" style="margin-left:4px">${esc(sz)} (${esc(c)})</span>`).join("") + `</div>`;
    }
    document.getElementById("analyticsBars").innerHTML = barHtml || `<div class="meta">هنوز رویدادی ثبت نشده است</div>`;

    const evs = d.recent_events || [];
    document.getElementById("eventsFeed").innerHTML = evs.length ? evs.map(e =>
      `<div class="feed-item"><div><span class="badge ${e.status === "OK" ? "b-ok" : "b-err"}">${esc(e.kind)}</span> <b>${esc(e.label)}</b> <span class="meta">چت ${esc(e.chat_id)}</span></div><div class="mono meta">${esc(e.latency_ms)}ms • ${esc(e.time)}</div></div>`
    ).join("") : `<div class="meta">در انتظار تعامل کاربران...</div>`;

    const errs = d.recent_errors || [];
    document.getElementById("errorsFeed").innerHTML = errs.length ? errs.map(e =>
      `<div class="feed-item"><div><span class="badge b-err">${esc(e.type)}</span> <b>${esc(e.component)}</b>: ${esc(e.detail)}</div><div class="mono meta">${esc(e.time)}</div></div>`
    ).join("") : `<div class="badge b-ok">✅ تا این لحظه هیچ خطایی ثبت نشده است!</div>`;
  } catch (err) {
    document.getElementById("tehranTime").textContent = "⚠️ قطع ارتباط موقت با سرور رصد: " + err;
    document.getElementById("connPulse").className = "pulse err";
  }
}
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
"""
