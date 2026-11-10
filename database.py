import asyncio
import aiosqlite
from typing import Optional, Dict, Any
from config import DB_PATH

_db_lock = asyncio.Lock()


async def init_db():
    async with _db_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    chat_id INTEGER PRIMARY KEY,
                    username TEXT,
                    state TEXT DEFAULT 'IDLE',
                    national_id TEXT,
                    mobile TEXT,
                    car_plate TEXT,
                    car_vin TEXT,
                    chassis_no TEXT,
                    green_sheet_no TEXT,
                    target_portal TEXT DEFAULT 'all',
                    target_tire_size TEXT DEFAULT '185_65_14',
                    tire_count INTEGER DEFAULT 2,
                    sniper_enabled INTEGER DEFAULT 0,
                    last_auth_token TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    action TEXT,
                    status TEXT,
                    message TEXT,
                    latency_ms REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS market_price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tire_size TEXT NOT NULL,
                    ir_min_unit INTEGER,
                    ir_median_unit INTEGER,
                    imp_min_unit INTEGER,
                    imp_median_unit INTEGER,
                    total_offers INTEGER DEFAULT 0,
                    sources_json TEXT,
                    tehran_time TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            async with db.execute("PRAGMA user_version") as cur:
                ver_row = await cur.fetchone()
                schema_ver = ver_row[0] if ver_row else 0
            if schema_ver < 2:
                # ارتقای یک‌باره کاربران نسخه قبلی از پورتال تکی به اسکن سراسری همه کارخانه‌ها
                await db.execute("UPDATE users SET target_portal = 'all' WHERE target_portal IN ('barez', 'kavir', '') OR target_portal IS NULL")
                await db.execute("PRAGMA user_version = 2")
            await db.commit()


async def get_user(chat_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None


async def upsert_user(chat_id: int, username: str = "", **kwargs) -> Dict[str, Any]:
    allowed_cols = {
        "username", "state", "national_id", "mobile", "car_plate",
        "car_vin", "chassis_no", "green_sheet_no", "target_portal",
        "target_tire_size", "tire_count", "sniper_enabled", "last_auth_token",
    }
    clean_kwargs = {k: v for k, v in kwargs.items() if k in allowed_cols}
    async with _db_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO users (chat_id, username, target_portal) VALUES (?, ?, 'all')",
                (chat_id, username)
            )
            if username:
                await db.execute(
                    "UPDATE users SET username = ?, last_updated = CURRENT_TIMESTAMP WHERE chat_id = ? AND (username IS NULL OR username = '')",
                    (username, chat_id)
                )
            if clean_kwargs:
                set_clause = ", ".join([f"{k} = ?" for k in clean_kwargs.keys()])
                vals = list(clean_kwargs.values()) + [chat_id]
                await db.execute(
                    f"UPDATE users SET {set_clause}, last_updated = CURRENT_TIMESTAMP WHERE chat_id = ?",
                    vals
                )
            await db.commit()
    return await get_user(chat_id)


async def set_state(chat_id: int, state: str):
    async with _db_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET state = ? WHERE chat_id = ?", (state, chat_id))
            await db.commit()


async def get_all_active_snipers():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE sniper_enabled = 1") as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def log_action(chat_id: int, action: str, status: str, message: str, latency_ms: float = 0.0):
    async with _db_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO logs (chat_id, action, status, message, latency_ms) VALUES (?, ?, ?, ?, ?)",
                (chat_id, action, status, message, latency_ms)
            )
            await db.commit()


async def record_market_price_snapshot(
    tire_size: str,
    ir_min: Optional[int],
    ir_med: Optional[int],
    imp_min: Optional[int],
    imp_med: Optional[int],
    total_offers: int,
    sources_json: str,
    tehran_time: str,
):
    async with _db_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO market_price_history
                (tire_size, ir_min_unit, ir_median_unit, imp_min_unit, imp_median_unit, total_offers, sources_json, tehran_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (tire_size, ir_min, ir_med, imp_min, imp_med, total_offers, sources_json, tehran_time),
            )
            await db.commit()


async def get_analytics_summary() -> Dict[str, Any]:
    """خلاصه دقیق آماری کاربران، اکشن‌ها و سوابق قیمت از SQLite"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            total_users = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
            active_snipers = (await (await db.execute("SELECT COUNT(*) FROM users WHERE sniper_enabled = 1")).fetchone())[0]
            ready_users = (
                await (
                    await db.execute(
                        "SELECT COUNT(*) FROM users WHERE national_id IS NOT NULL AND national_id != '' AND mobile IS NOT NULL AND mobile != ''"
                    )
                ).fetchone()
            )[0]
            portal_dist = [
                {"portal": r[0] or "unknown", "count": r[1]}
                for r in await (
                    await db.execute("SELECT target_portal, COUNT(*) c FROM users GROUP BY target_portal ORDER BY c DESC")
                ).fetchall()
            ]
            size_dist = [
                {"size": r[0] or "unknown", "count": r[1]}
                for r in await (
                    await db.execute("SELECT target_tire_size, COUNT(*) c FROM users GROUP BY target_tire_size ORDER BY c DESC LIMIT 8")
                ).fetchall()
            ]
            action_stats = [
                {"action": r[0], "status": r[1], "count": r[2], "avg_ms": r[3] or 0.0}
                for r in await (
                    await db.execute(
                        "SELECT action, status, COUNT(*) c, ROUND(AVG(latency_ms), 1) FROM logs GROUP BY action, status ORDER BY c DESC LIMIT 15"
                    )
                ).fetchall()
            ]
            recent_logs = [
                dict(r)
                for r in await (
                    await db.execute("SELECT id, chat_id, action, status, message, latency_ms, created_at FROM logs ORDER BY id DESC LIMIT 12")
                ).fetchall()
            ]
            price_history_count = (
                await (await db.execute("SELECT COUNT(*) FROM market_price_history")).fetchone()
            )[0]
            return {
                "total_users": total_users,
                "ready_profile_users": ready_users,
                "active_snipers": active_snipers,
                "portal_distribution": portal_dist,
                "size_distribution": size_dist,
                "action_stats": action_stats,
                "recent_db_logs": recent_logs,
                "price_history_records": price_history_count,
            }
    except Exception as e:
        return {"error": str(e)}
