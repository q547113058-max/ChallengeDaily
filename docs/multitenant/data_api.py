# -*- coding: utf-8 -*-
"""
ChallengeDaily 服务器侧「采集数据」存储与查询（CentOS 7 / Python 3.6 标准库）。

设计：
  * Windows 同步代理把本机 SQLite 的每张表以原始行 POST 到 /api/sync/push；
  * 服务器把行 UPSERT 到自己的 SQLite（表结构与本机一致，按主键去重）；
  * 查询接口复刻 routes/*.py 的 SQL 与 JSON 契约，前端无需任何改动。

只依赖 sqlite3/json/datetime，零第三方包。
"""
import os
import io
import json
import sqlite3
import threading
from datetime import date, datetime, timedelta

DB_PATH = os.environ.get("CD_SYNC_DB", "")
if not DB_PATH:
    DB_PATH = os.path.join(os.environ.get("CD_DATA_DIR", "/opt/challengedaily/data"),
                           "synced.db")

# ── 多租户：DB 路径按请求线程隔离 ────────────────────────────────────────
# 每个 HTTP 请求是独立线程；鉴权后调用 set_tenant_db(path) 把该线程的
# DB 路径切到对应租户目录。未设置时用默认 DB_PATH（兼容非 HTTP 调用）。
_thread_local = threading.local()


def set_tenant_db(path):
    if path:
        _thread_local.db_path = path
    else:
        clear_tenant_db()


def clear_tenant_db():
    if hasattr(_thread_local, "db_path"):
        del _thread_local.db_path


def current_db():
    return getattr(_thread_local, "db_path", None) or DB_PATH


_write_lock = threading.RLock()   # 可重入：connect()->_ensure_schema 与 init_db 会嵌套加锁
_initialized_paths = set()   # 已建表 DB 路径，新租户首次访问时自动初始化

# 数据保留天数（超过则服务器自动删除；本机 xiaohei.db 是源数据，不受影响）
try:
    RETENTION_DAYS = int(os.environ.get("CD_RETENTION_DAYS", "7"))
except ValueError:
    RETENTION_DAYS = 7
if RETENTION_DAYS <= 0:
    RETENTION_DAYS = 7

# 需要同步的业务表（排除 FTS 影子表 / sqlite_sequence / schema_version），
# 与 value = 该表的「主键列」列表（用于 UPSERT 冲突判定）。
SYNC_TABLES = {
    "activities": ["id"],
    "app_usage": ["id"],
    "todos": ["id"],
    "habits": ["id"],
    "habit_logs": ["id"],
    "goals": ["id"],
    "reports": ["report_date"],
    "daily_profiles": ["date"],
    "user_profile": ["id"],
    "user_corrections": ["id"],
    "app_category_rules": ["app_name"],
    "plan_meta": ["plan_type", "plan_key"],
    "diaries": ["diary_date"],
    "achievements": ["code"],
    "achievement_seasons": ["season_key"],
    "season_achievements": ["season_key", "achievement_key"],
    "countdowns": ["id"],
    "chat_history": ["id"],
    "settings": ["key"],
    "user_preferences": ["key"],
    "profile_analysis_cache": ["analysis_type"],
    "audit_log": ["id"],
    "ai_retry_queue": ["id"],
    "growth_profile": ["id"],
    "growth_log": ["id"],
    "life_quests": ["id"],
    "quest_stages": ["id"],
    "daily_plans": ["date"],
    "daily_reflections": ["date"],
    "productivity_scores": ["date"],
}

# 建表 DDL（与本机 db_migrations.py 最终形态一致；列顺序无关，按列名 UPSERT）
DDL = {
    "activities": """CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY, timestamp TEXT, screenshot TEXT, app_name TEXT,
        window_title TEXT, category TEXT, summary TEXT, source TEXT,
        created_at TEXT, interval_sec INTEGER, ai_detail TEXT, windows_json TEXT)""",
    "app_usage": """CREATE TABLE IF NOT EXISTS app_usage (
        id INTEGER PRIMARY KEY, app_name TEXT, window_title TEXT,
        start_time TEXT, end_time TEXT, duration_sec INTEGER)""",
    "todos": """CREATE TABLE IF NOT EXISTS todos (
        id INT, title TEXT, category TEXT, mode TEXT, target_min INT,
        repeat_type TEXT, repeat_days TEXT, due_date TEXT, priority INT,
        status TEXT, progress_min INT, sort_order INT, created_at TEXT,
        updated_at TEXT, completed_at TEXT, parent_id INT, task_level TEXT,
        assigned_date TEXT, week_start TEXT, month_key TEXT, color TEXT,
        goal_id INT, plan_start_min INT)""",
    "habits": """CREATE TABLE IF NOT EXISTS habits (
        id INTEGER PRIMARY KEY, name TEXT, target_count INTEGER, period TEXT,
        color TEXT, sort_order INTEGER, created_at TEXT, auto_category TEXT)""",
    "habit_logs": """CREATE TABLE IF NOT EXISTS habit_logs (
        id INTEGER PRIMARY KEY, habit_id INTEGER, log_date TEXT, count INTEGER,
        created_at TEXT)""",
    "goals": """CREATE TABLE IF NOT EXISTS goals (
        id INTEGER PRIMARY KEY, title TEXT, description TEXT, category TEXT,
        timeframe TEXT, start_date TEXT, target_date TEXT, status TEXT,
        progress INTEGER, key_results TEXT, linked_todos TEXT, linked_habits TEXT,
        color TEXT, created_at TEXT, updated_at TEXT)""",
    "reports": """CREATE TABLE IF NOT EXISTS reports (
        id INTEGER, report_date TEXT PRIMARY KEY, content TEXT,
        created_at TEXT, template TEXT)""",
    "daily_profiles": """CREATE TABLE IF NOT EXISTS daily_profiles (
        date TEXT PRIMARY KEY, hourly_digest TEXT, daily_summary TEXT,
        work_patterns TEXT, top_apps TEXT, focus_hours TEXT, productivity TEXT,
        key_insights TEXT, peak_hours TEXT, work_rhythm TEXT, content_types TEXT,
        behavior_tags TEXT, efficiency_pattern TEXT, generated_at TEXT)""",
    "user_profile": """CREATE TABLE IF NOT EXISTS user_profile (
        id INTEGER PRIMARY KEY, role_desc TEXT, work_style TEXT, habits TEXT,
        app_overrides TEXT, custom_rules TEXT, peak_hours TEXT, work_rhythm TEXT,
        content_types TEXT, behavior_tags TEXT, efficiency_pattern TEXT,
        updated_at TEXT)""",
    "user_corrections": """CREATE TABLE IF NOT EXISTS user_corrections (
        id INTEGER PRIMARY KEY, app_name TEXT, correct_category TEXT,
        correct_desc TEXT, notes TEXT, created_at TEXT)""",
    "app_category_rules": """CREATE TABLE IF NOT EXISTS app_category_rules (
        id INTEGER, app_name TEXT PRIMARY KEY, display_name TEXT,
        primary_category TEXT, tags TEXT, window_rules TEXT, created_at TEXT,
        updated_at TEXT)""",
    "plan_meta": """CREATE TABLE IF NOT EXISTS plan_meta (
        id INTEGER, plan_type TEXT, plan_key TEXT, title TEXT, goal TEXT,
        created_at TEXT, updated_at TEXT,
        PRIMARY KEY (plan_type, plan_key))""",
    "diaries": """CREATE TABLE IF NOT EXISTS diaries (
        id INTEGER, diary_date TEXT PRIMARY KEY, mood TEXT, weather TEXT,
        content TEXT, tags TEXT, highlights TEXT, gratitude TEXT,
        created_at TEXT, updated_at TEXT, media_json TEXT, font_style TEXT)""",
    "achievements": """CREATE TABLE IF NOT EXISTS achievements (
        id INTEGER PRIMARY KEY, code TEXT, name TEXT, description TEXT,
        icon TEXT, unlocked_at TEXT)""",
    "achievement_seasons": """CREATE TABLE IF NOT EXISTS achievement_seasons (
        id INTEGER, season_key TEXT PRIMARY KEY, start_date TEXT, end_date TEXT,
        created_at TEXT)""",
    "season_achievements": """CREATE TABLE IF NOT EXISTS season_achievements (
        id INTEGER, season_key TEXT, achievement_key TEXT, user_id INTEGER,
        unlocked_at TEXT, progress INTEGER,
        PRIMARY KEY (season_key, achievement_key))""",
    "countdowns": """CREATE TABLE IF NOT EXISTS countdowns (
        id INTEGER PRIMARY KEY, title TEXT, target_date TEXT, color TEXT,
        created_at TEXT)""",
    "chat_history": """CREATE TABLE IF NOT EXISTS chat_history (
        id INTEGER PRIMARY KEY, role TEXT, content TEXT, created_at TEXT)""",
    "settings": """CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)""",
    "user_preferences": """CREATE TABLE IF NOT EXISTS user_preferences (
        key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)""",
    "profile_analysis_cache": """CREATE TABLE IF NOT EXISTS profile_analysis_cache (
        id INTEGER, analysis_type TEXT PRIMARY KEY, result_json TEXT,
        confidence REAL, data_points INTEGER, created_at TEXT, updated_at TEXT)""",
    "audit_log": """CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY, ts TEXT, category TEXT, action TEXT, status TEXT,
        detail TEXT, duration_ms INTEGER, metadata TEXT)""",
    "ai_retry_queue": """CREATE TABLE IF NOT EXISTS ai_retry_queue (
        id INTEGER PRIMARY KEY, kind TEXT, payload TEXT, attempts INTEGER,
        last_attempt TEXT, created_at TEXT, status TEXT)""",
    "growth_profile": """CREATE TABLE IF NOT EXISTS growth_profile (
        id INTEGER PRIMARY KEY, total_exp INTEGER, level INTEGER,
        current_level_exp INTEGER, dimensions_json TEXT, streak_days INTEGER,
        longest_streak INTEGER, last_active_date TEXT, initialized INTEGER,
        updated_at TEXT)""",
    "growth_log": """CREATE TABLE IF NOT EXISTS growth_log (
        id INTEGER PRIMARY KEY, exp_amount INTEGER, dimension TEXT, source TEXT,
        source_id INTEGER, quality_mult REAL, streak_mult REAL, note TEXT,
        created_at TEXT)""",
    "life_quests": """CREATE TABLE IF NOT EXISTS life_quests (
        id INTEGER PRIMARY KEY, title TEXT, description TEXT, target_date TEXT,
        status TEXT, progress REAL, ai_breakdown_json TEXT, created_at TEXT)""",
    "quest_stages": """CREATE TABLE IF NOT EXISTS quest_stages (
        id INTEGER PRIMARY KEY, quest_id INTEGER, title TEXT, order_index INTEGER,
        status TEXT, estimated_hours REAL, actual_hours REAL, linked_todo_ids TEXT)""",
    "daily_plans": """CREATE TABLE IF NOT EXISTS daily_plans (
        id INTEGER, date TEXT PRIMARY KEY, plan_json TEXT, mit_task TEXT,
        focus_target_min INTEGER, limits_json TEXT, status TEXT, adopted_ai INTEGER,
        created_at TEXT)""",
    "daily_reflections": """CREATE TABLE IF NOT EXISTS daily_reflections (
        id INTEGER, date TEXT PRIMARY KEY, productivity_score REAL,
        good_thing TEXT, improve_thing TEXT, ai_insights_json TEXT,
        report_generated INTEGER, created_at TEXT)""",
    "productivity_scores": """CREATE TABLE IF NOT EXISTS productivity_scores (
        id INTEGER, date TEXT PRIMARY KEY, score REAL, deep_work_min INTEGER,
        learning_min INTEGER, exercise_min INTEGER, distraction_count INTEGER,
        total_active_min INTEGER, created_at TEXT)""",
}

# 同步元信息表
META_DDL = """CREATE TABLE IF NOT EXISTS _sync_meta (
    k TEXT PRIMARY KEY, v TEXT)"""


def _ensure_schema(db_path):
    """给指定 DB 建表（独立连接，避免与 connect() 递归）。线程安全。"""
    with _write_lock:
        if db_path in _initialized_paths:
            return
        d = os.path.dirname(db_path)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        con = sqlite3.connect(db_path, timeout=15)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute(META_DDL)
            for ddl in DDL.values():
                con.execute(ddl)
            con.commit()
            try:
                os.chmod(db_path, 0o600)
            except OSError:
                pass
            _initialized_paths.add(db_path)
        finally:
            con.close()


def connect():
    db_path = current_db()
    d = os.path.dirname(db_path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    # 新租户（运行时创建）首次访问时自动建表，避免 "no such table"
    if db_path not in _initialized_paths:
        _ensure_schema(db_path)
    con = sqlite3.connect(db_path, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    # 采集数据含窗口标题等隐私内容：仅属主可读写
    try:
        os.chmod(db_path, 0o600)
    except OSError:
        pass
    return con


def init_db():
    with _write_lock:
        con = connect()
        try:
            con.execute(META_DDL)
            for ddl in DDL.values():
                con.execute(ddl)
            # 常用索引
            for sql in [
                "CREATE INDEX IF NOT EXISTS idx_act_ts ON activities(timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_act_date ON activities(date(timestamp))",
                "CREATE INDEX IF NOT EXISTS idx_usage_start ON app_usage(start_time)",
                "CREATE INDEX IF NOT EXISTS idx_reports_date ON reports(report_date)",
            ]:
                try:
                    con.execute(sql)
                except sqlite3.Error:
                    pass
            con.commit()
        finally:
            con.close()


def table_columns(con, table):
    return [r[1] for r in con.execute('PRAGMA table_info("%s")' % table).fetchall()]


def apply_push(payload, mode="upsert"):
    """接收同步代理推送的表数据。

    payload = {"tables": {table: [row, ...], ...}, "full": bool, "ts": ...}
    mode=upsert（默认，增量）或 replace（整表替换，用于首次全量）。
    返回 (stats_dict, error)。
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("tables"), dict):
        return None, "payload must have tables object"
    tables = payload["tables"]
    deleted_keys = payload.get("deleted_keys") or {}
    stats = {}
    with _write_lock:
        con = connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            # 删除传播：本机已删除的行，服务器同步删除
            for name, key_lists in deleted_keys.items():
                if name not in SYNC_TABLES or name not in DDL or not isinstance(key_lists, list):
                    continue
                keys = SYNC_TABLES[name]
                removed = 0
                for kl in key_lists:
                    if not isinstance(kl, list) or len(kl) != len(keys):
                        continue
                    where = " AND ".join('"%s"=?' % k for k in keys)
                    cur = con.execute('DELETE FROM "%s" WHERE %s' % (name, where), kl)
                    removed += cur.rowcount
                stats[name + ":deleted"] = removed
            for name, rows in tables.items():
                if name not in SYNC_TABLES or name not in DDL:
                    continue
                if not isinstance(rows, list):
                    continue
                cols = table_columns(con, name)
                keys = SYNC_TABLES[name]
                # 只保留目标表真实存在的列
                usable = [c for c in cols]
                if mode == "replace":
                    con.execute('DELETE FROM "%s"' % name)
                inserted = 0
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    vals = {}
                    for c in usable:
                        if c in row:
                            v = row[c]
                            if isinstance(v, (dict, list)):
                                v = json.dumps(v, ensure_ascii=False)
                            vals[c] = v
                    if not vals:
                        continue
                    # 冲突列必须都存在于本行
                    if not all(k in vals for k in keys):
                        continue
                    cs = ", ".join('"%s"' % c for c in vals)
                    qs = ", ".join("?" for _ in vals)
                    # CentOS 7 自带 SQLite 3.7.17，不支持 ON CONFLICT(...)
                    # DO UPDATE（需 3.24+）。改为「按主键删除 + 插入」，
                    # 在所有 SQLite 版本上通用且幂等。
                    where = " AND ".join('"%s"=?' % k for k in keys)
                    con.execute('DELETE FROM "%s" WHERE %s' % (name, where),
                                [vals[k] for k in keys])
                    con.execute('INSERT INTO "%s" (%s) VALUES (%s)' % (name, cs, qs),
                                list(vals.values()))
                    inserted += 1
                stats[name] = inserted
            con.execute("INSERT OR REPLACE INTO _sync_meta (k, v) VALUES (?, ?)",
                        ("last_push", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            con.execute("INSERT OR REPLACE INTO _sync_meta (k, v) VALUES (?, ?)",
                        ("last_push_ts", str(payload.get("ts", ""))))
            con.commit()
        except Exception as e:
            con.rollback()
            return None, str(e)[:200]
        finally:
            con.close()
    # 每次有效推送后顺带清理过期数据（幂等，删除量小时开销可忽略）
    cleaned = cleanup_expired()
    if cleaned:
        log_cleanup(cleaned)
        stats["_expired"] = cleaned
    return stats, None


# 按时间列清理的表：table -> (时间列, 时间格式)。格式 date=YYYY-MM-DD / ts=完整时间戳
TIME_TABLES = {
    "activities": ("timestamp", "ts"),
    "app_usage": ("start_time", "ts"),
    "reports": ("report_date", "date"),
    "daily_profiles": ("date", "date"),
    "diaries": ("diary_date", "date"),
    "daily_plans": ("date", "date"),
    "daily_reflections": ("date", "date"),
    "productivity_scores": ("date", "date"),
    "habit_logs": ("log_date", "date"),
    "chat_history": ("created_at", "ts"),
    "audit_log": ("ts", "ts"),
    "ai_retry_queue": ("created_at", "ts"),
    "growth_log": ("created_at", "ts"),
    "achievements": ("unlocked_at", "ts"),
    "achievement_seasons": ("start_date", "date"),
    "season_achievements": ("unlocked_at", "ts"),
    "user_corrections": ("created_at", "ts"),
    "profile_analysis_cache": ("updated_at", "ts"),
}


def cutoff_values():
    """返回 (date_cutoff, ts_cutoff)，均为 YYYY-MM-DD / 完整时间戳字符串。"""
    c = date.today() - timedelta(days=RETENTION_DAYS)
    return c.isoformat(), c.isoformat() + " 23:59:59"


def cleanup_expired():
    """删除服务器上超过保留期的行；返回 {table: deleted_count}（只含有删除的）。"""
    d_cut, ts_cut = cutoff_values()
    cleaned = {}
    with _write_lock:
        con = connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            for table, (col, kind) in TIME_TABLES.items():
                if table not in DDL:
                    continue
                cols = table_columns(con, table)
                if col not in cols:
                    continue
                cutoff = d_cut if kind == "date" else ts_cut
                cur = con.execute('DELETE FROM "%s" WHERE "%s" < ? AND "%s" IS NOT NULL'
                                  % (table, col, col), (cutoff,))
                if cur.rowcount > 0:
                    cleaned[table] = cur.rowcount
            con.execute("INSERT OR REPLACE INTO _sync_meta (k, v) VALUES (?, ?)",
                        ("last_cleanup", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            con.execute("INSERT OR REPLACE INTO _sync_meta (k, v) VALUES (?, ?)",
                        ("retention_days", str(RETENTION_DAYS)))
            con.commit()
        except Exception:
            con.rollback()
            return {}
        finally:
            con.close()
    return cleaned


def log_cleanup(cleaned):
    import logging
    logging.getLogger("cd").info("过期清理(%d天): %s",
                                 RETENTION_DAYS,
                                 json.dumps(cleaned, ensure_ascii=False))


def get_meta(key):
    try:
        con = connect()
        r = con.execute("SELECT v FROM _sync_meta WHERE k=?", (key,)).fetchone()
        con.close()
        return r[0] if r else None
    except sqlite3.Error:
        return None


def status():
    con = connect()
    try:
        counts = {}
        for t in SYNC_TABLES:
            try:
                counts[t] = con.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
            except sqlite3.Error:
                counts[t] = 0
        return {
            "db_path": current_db(),
            "tables": counts,
            "last_push": get_meta("last_push"),
            "last_push_ts": get_meta("last_push_ts"),
        }
    finally:
        con.close()
