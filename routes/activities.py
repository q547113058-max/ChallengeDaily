import re

from flask import Blueprint, jsonify, request
from datetime import date

from config import CATEGORIES
import config
from db import get_activities, insert_manual_activity
from routes.deps import safe_error, validate_date

bp = Blueprint('activities', __name__)


@bp.route("/api/activities")
def activities():
    target_date = request.args.get("date", date.today().isoformat())
    if not validate_date(target_date):
        return jsonify({"error": f"Invalid date format: {target_date}"}), 400

    # 分页参数（安全解析）
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        return jsonify({"error": "page 参数必须是正整数"}), 400
    try:
        per_page = max(1, min(500, int(request.args.get("per_page", 200))))
    except (ValueError, TypeError):
        return jsonify({"error": "per_page 参数必须是正整数"}), 400

    rows = get_activities(target_date, target_date)

    from app_tracker import get_display_name as _gdn
    import json as _json
    result = []
    for r in rows:
        raw_name = r.get("app_name", "")
        interval = r["interval_sec"] if "interval_sec" in r.keys() and r["interval_sec"] else config.SCREENSHOT_INTERVAL_SEC
        windows_json = r.get("windows_json", "[]")
        try:
            windows = _json.loads(windows_json) if windows_json else []
        except Exception:
            windows = []
        result.append({
            "id": r["id"],
            "timestamp": r["timestamp"],
            "app_name": _gdn(raw_name),
            "app_name_raw": raw_name,
            "window_title": r.get("window_title", ""),
            "category": r.get("category", "其他"),
            "ai_summary": r.get("summary"),
            "ai_detail": r.get("ai_detail", ""),
            "duration_min": interval / 60,
            "windows": windows,
        })

    total = len(result)
    total_pages = max(1, (total + per_page - 1) // per_page)
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated = result[start_idx:end_idx]

    return jsonify({
        "activities": paginated,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "has_more": page < total_pages,
        }
    })


@bp.route("/api/activities", methods=["POST"])
def create_activity():
    data = request.get_json(force=True)

    timestamp = data.get("timestamp", "").strip()
    category = data.get("category", "").strip()
    summary = data.get("summary", "").strip()

    if not timestamp or not category:
        return jsonify({"error": "时间和分类为必填项"}), 400

    if not re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", timestamp):
        return jsonify({"error": "时间格式应为 YYYY-MM-DD HH:MM:SS"}), 400

    try:
        from datetime import datetime as _dt
        _dt.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return jsonify({"error": "时间值无效，请检查日期和时间是否正确"}), 400

    if category not in CATEGORIES:
        return jsonify({"error": f"无效分类: {category}，可选: {', '.join(CATEGORIES)}"}), 400

    # 来源标记（V38）：auto 自动采集 / manual 界面补录 / agent Agent(MCP)写入 / import 导入
    source = (data.get("source") or "").strip().lower() or "manual"
    if source not in config.ACTIVITY_SOURCES:
        return jsonify({"error": f"无效来源: {source}，可选: {', '.join(config.ACTIVITY_SOURCES)}"}), 400

    app_name = data.get("app_name", "").strip() or ("agent添加" if source == "agent" else "手动补录")
    window_title = data.get("window_title", "").strip()
    duration_min = max(5, min(480, int(data.get("duration_min", 30))))

    if not summary:
        summary = f"[{'agent补录' if source == 'agent' else '手动补录'}] {category}"

    try:
        new_id = insert_manual_activity(
            timestamp=timestamp,
            app_name=app_name,
            window_title=window_title,
            category=category,
            summary=summary,
            duration_min=duration_min,
            source=source,
        )
        return jsonify({"status": "ok", "id": new_id, "source": source}), 201
    except Exception as e:
        error_str = str(e)
        if "UNIQUE constraint" in error_str or "unique" in error_str.lower():
            return jsonify({"error": "该时间点已有记录，请选择其他时间"}), 409
        return jsonify({"error": safe_error(e, "手动补录失败，请重试")}), 500


@bp.route("/api/activities/<int:act_id>", methods=["PUT"])
def update_activity(act_id):
    data = request.get_json(force=True)
    category = data.get("category")
    summary = data.get("summary")

    updates = []
    params: list = []
    if category is not None:
        if category not in CATEGORIES:
            return jsonify({"error": f"无效分类: {category}，可选: {', '.join(CATEGORIES)}"}), 400
        updates.append("category = ?")
        params.append(category)
    if summary is not None:
        updates.append("summary = ?")
        params.append(summary)

    if not updates:
        return jsonify({"error": "没有要更新的字段"}), 400

    params.append(act_id)
    from db import get_conn
    with get_conn() as conn:
        cursor = conn.execute(
            f"UPDATE activities SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "记录不存在"}), 404

    return jsonify({"status": "ok", "id": act_id})


@bp.route("/api/activities/<int:act_id>", methods=["DELETE"])
def delete_activity(act_id):
    """软删除：将记录移到 activities_deleted 表，支持 undo。
    使用 BEGIN IMMEDIATE 显式事务保证 INSERT+DELETE 原子性。"""
    from db import get_conn

    with get_conn() as conn:
        # 显式事务：防止 INSERT 成功但 DELETE 失败导致数据不一致
        conn.execute("BEGIN IMMEDIATE")
        try:
            # 查找原始记录
            row = conn.execute("SELECT * FROM activities WHERE id = ?", (act_id,)).fetchone()
            if not row:
                conn.rollback()
                return jsonify({"error": "记录不存在"}), 404

            # 创建 deleted 表（如不存在）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS activities_deleted (
                    id INTEGER PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    screenshot TEXT,
                    app_name TEXT,
                    window_title TEXT,
                    category TEXT,
                    summary TEXT,
                    interval_sec INTEGER DEFAULT 60,
                    ai_detail TEXT DEFAULT '',
                    windows_json TEXT DEFAULT '[]',
                    created_at TEXT,
                    original_id INTEGER,
                    deleted_at TEXT DEFAULT (datetime('now'))
                )
            """)
            # 兼容：为旧版 deleted 表补齐新列
            try:
                conn.execute("ALTER TABLE activities_deleted ADD COLUMN interval_sec INTEGER DEFAULT 60")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE activities_deleted ADD COLUMN ai_detail TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE activities_deleted ADD COLUMN windows_json TEXT DEFAULT '[]'")
            except Exception:
                pass

            # 插入 deleted 表
            deleted_cols = {"id", "timestamp", "screenshot", "app_name", "window_title", "category", "summary", "interval_sec", "ai_detail", "windows_json", "created_at"}
            insert_cols = []
            insert_vals = []
            for k in row.keys():
                if k in deleted_cols:
                    insert_cols.append(k)
                    insert_vals.append(row[k])
            insert_cols.append("original_id")
            insert_vals.append(act_id)

            placeholders = ', '.join(['?'] * len(insert_cols))
            col_names = ', '.join(insert_cols)
            conn.execute(
                f"INSERT INTO activities_deleted ({col_names}) VALUES ({placeholders})",
                insert_vals,
            )

            # 从原表删除
            conn.execute("DELETE FROM activities WHERE id = ?", (act_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return jsonify({"status": "ok", "id": act_id, "deleted": True})


@bp.route("/api/activities/<int:act_id>/undo", methods=["POST"])
def undo_delete_activity(act_id):
    """撤销删除：从 activities_deleted 表恢复到 activities"""
    from db import get_conn

    with get_conn() as conn:
        row = conn.execute("SELECT * FROM activities_deleted WHERE original_id = ?", (act_id,)).fetchone()
        if not row:
            return jsonify({"error": "删除记录不存在"}), 404

        # 恢复到 activities（排除 deleted_at 和 original_id）
        skip_cols = {"deleted_at", "original_id"}
        activities_cols = {k for k in row.keys() if k not in skip_cols}
        restore_cols = []
        restore_vals = []
        for k in row.keys():
            if k in activities_cols:
                restore_cols.append(k)
                restore_vals.append(row[k])

        placeholders = ', '.join(['?'] * len(restore_cols))
        col_names = ', '.join(restore_cols)
        conn.execute(
            f"INSERT OR IGNORE INTO activities ({col_names}) VALUES ({placeholders})",
            restore_vals,
        )

        # 从 deleted 表删除
        conn.execute("DELETE FROM activities_deleted WHERE original_id = ?", (act_id,))
        conn.commit()

    return jsonify({"status": "ok", "id": act_id, "restored": True})


@bp.route("/api/activities/search")
def search_activities():
    """活动关键词检索，支持日期范围。

    GET /api/activities/search?q=关键词&startDate=2026-09-01&endDate=2026-09-30
    GET /api/activities/search?q=关键词&date=2026-09-09      # 单日（旧行为，保留）

    优先级：startDate/endDate > date > 今天。
    只传 startDate 或 endDate 其一表示单侧不限制。匹配 window_title 与 summary。
    """
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"activities": [], "query": "", "count": 0})

    start_date = (request.args.get("startDate") or request.args.get("start_date") or "").strip()
    end_date = (request.args.get("endDate") or request.args.get("end_date") or "").strip()
    if start_date:
        start_date = validate_date(start_date) or ""
        if not start_date:
            return jsonify({"error": "startDate 格式应为 YYYY-MM-DD"}), 400
    if end_date:
        end_date = validate_date(end_date) or ""
        if not end_date:
            return jsonify({"error": "endDate 格式应为 YYYY-MM-DD"}), 400

    range_sql = ""
    range_params: list = []
    if start_date or end_date:
        if start_date:
            range_sql += " AND timestamp >= ?"
            range_params.append(f"{start_date} 00:00:00")
        if end_date:
            range_sql += " AND timestamp <= ?"
            range_params.append(f"{end_date} 23:59:59")
        if start_date and end_date and start_date > end_date:
            return jsonify({"error": "startDate 不能晚于 endDate"}), 400
    else:
        # 兼容旧行为：默认查当天
        target_date = request.args.get("date", date.today().isoformat())
        range_sql += " AND date(timestamp) = ?"
        range_params.append(target_date)

    from db import get_conn
    safe_q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM activities "
            "WHERE 1=1" + range_sql + " "
            "AND (window_title LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\') "
            "ORDER BY timestamp DESC",
            (*range_params, f"%{safe_q}%", f"%{safe_q}%"),
        ).fetchall()
    # 统一转 dict：sqlite3.Row 没有 .get()，直接遍历会抛 AttributeError 导致整个接口 500
    rows = [dict(r) for r in rows]

    from app_tracker import get_display_name as _gdn_s
    import json as _json
    result = []
    for r in rows:
        interval = r["interval_sec"] if "interval_sec" in r.keys() and r["interval_sec"] else config.SCREENSHOT_INTERVAL_SEC
        windows_json = r.get("windows_json", "[]")
        try:
            windows = _json.loads(windows_json) if windows_json else []
        except Exception:
            windows = []
        result.append({
            "id": r["id"],
            "timestamp": r["timestamp"],
            "app_name": _gdn_s(r["app_name"] if "app_name" in r.keys() else ""),
            "window_title": r["window_title"] if "window_title" in r.keys() else "",
            "category": r["category"] if "category" in r.keys() else "其他",
            "ai_summary": r["summary"] if "summary" in r.keys() else None,
            "ai_detail": r["ai_detail"] if "ai_detail" in r.keys() else "",
            "duration_min": interval / 60,
            "windows": windows,
            "source": r["source"] if "source" in r.keys() and r["source"] else "auto",
        })
    return jsonify({
        "activities": result,
        "query": q,
        "count": len(result),
        "startDate": start_date or None,
        "endDate": end_date or None,
    })


@bp.route("/api/timeline")
def timeline():
    start = request.args.get("startDate", date.today().isoformat())
    end = request.args.get("endDate", date.today().isoformat())
    data = get_activities(start, end)
    return jsonify(data)


@bp.route("/api/app-usage")
def app_usage():
    target_date = request.args.get("date", request.args.get("startDate", date.today().isoformat()))
    end_date = request.args.get("endDate", target_date)
    if not validate_date(target_date):
        return jsonify({"error": f"Invalid date format: {target_date}"}), 400

    from db import get_app_usage, get_app_usage_by_content
    apps = get_app_usage(target_date, end_date)
    total_min = sum(a["duration_min"] for a in apps)

    # 内容维度：同应用下不同 window_title 的时长明细，按 app 分组
    content_rows = get_app_usage_by_content(target_date, end_date)
    contents_by_app: dict[str, list[dict]] = {}
    for c in content_rows:
        contents_by_app.setdefault(c["app_name"], []).append({
            "title": c["window_title"],
            "duration_min": c["duration_min"],
        })

    from db import get_conn
    with get_conn() as conn:
        app_cat_rows = conn.execute(
            "SELECT app_name, category, COUNT(*) as cnt FROM activities "
            "WHERE date(timestamp) = ? "
            "GROUP BY app_name, category",
            (target_date,),
        ).fetchall()

    app_primary_cat = {}
    cat_counts: dict[str, dict[str, int]] = {}
    for r in app_cat_rows:
        an = r["app_name"]
        cat = r["category"] or "其他"
        if an not in cat_counts:
            cat_counts[an] = {}
        cat_counts[an][cat] = (cat_counts[an].get(cat) or 0) + r["cnt"]
    for an, cats in cat_counts.items():
        app_primary_cat[an] = max(cats, key=cats.get)

    from app_tracker import get_display_name as _gdn3
    result = []
    for a in apps:
        raw_name = a["app_name"]
        contents = contents_by_app.get(raw_name, [])
        # 内容维度百分比：基于该 app 自身总时长
        app_total = a["duration_min"] if a["duration_min"] > 0 else 0
        contents_payload = [
            {
                "title": c["title"],
                "duration_min": c["duration_min"],
                "percentage": round(c["duration_min"] / app_total * 100, 1) if app_total > 0 else 0,
            }
            for c in contents
        ]
        result.append({
            "app_name": _gdn3(raw_name),
            "app_name_raw": raw_name,
            "category": app_primary_cat.get(raw_name, "其他"),
            "duration_min": a["duration_min"],
            "percentage": round(a["duration_min"] / total_min * 100, 1) if total_min > 0 else 0,
            "contents": contents_payload,
            "window_count": len(contents_payload),
        })
    return jsonify({"apps": result})
