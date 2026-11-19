"""通知中心：持久化到 DB，支持去重、未读拉取、标记已读。

历史问题（本次修复）：
  1. 原先只存内存 list —— 后端重启即全部丢失
  2. `GET /api/notifications` 一读就把所有未读标记已读 —— 多窗口/多客户端互相抢消息，
     且没有「未读列表」概念，只剩一次性弹窗

现在的语义：
  - 通知落库（notifications 表，V41）
  - `GET  /api/notifications?since_id=N&unread_only=1` 只读不写，按 id 增量返回
  - `POST /api/notifications/read` 显式标记已读（body: {ids:[...]} 或 {all:true}）
  - 同类通知通过 dedup_key + 冷却窗口去重，避免刷屏
"""
import logging
import threading
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint('notifications', __name__)

# 同 dedup_key 在多少秒内不重复推送（默认 10 分钟）
_DEDUP_WINDOW_SEC = 600
_dedup_lock = threading.Lock()
# 内存兜底：DB 不可用时降级，仍能推送但在内存里（重启丢失）
_mem: list[dict] = []
_mem_next_id = 1


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _recent_duplicate(conn, dedup_key: str) -> bool:
    """同 dedup_key 在冷却窗口内是否已有通知。"""
    if not dedup_key:
        return False
    cutoff = (datetime.now() - timedelta(seconds=_DEDUP_WINDOW_SEC)).strftime('%Y-%m-%d %H:%M:%S')
    row = conn.execute(
        "SELECT 1 FROM notifications WHERE dedup_key=? AND created_at>=? LIMIT 1",
        (dedup_key, cutoff),
    ).fetchone()
    return row is not None


def add_notification(title: str, body: str = '', ntype: str = 'info',
                     category: str = 'system', dedup_key: str = ''):
    """写入一条通知。

    title/body: 展示文案
    ntype: info | success | warning | error
    category: report | collector | ai | disk | sync | todo | system（用于前端分组/过滤）
    dedup_key: 非空时，同 key 在 _DEDUP_WINDOW_SEC 内只记一条（防刷屏）
    """
    global _mem_next_id
    payload = None

    try:
        from db import get_conn
        with get_conn() as conn:
            if _recent_duplicate(conn, dedup_key):
                logger.debug(f"通知被去重跳过: {dedup_key} / {title}")
                return None
            cur = conn.execute(
                "INSERT INTO notifications (title, body, type, category, dedup_key, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (title, body, ntype, category, dedup_key, _now()),
            )
            nid = cur.lastrowid
            payload = {"id": nid, "title": title, "body": body,
                       "type": ntype, "category": category, "timestamp": _now()}
    except Exception as e:
        # DB 不可用 → 内存兜底
        logger.warning(f"通知落库失败，降级内存: {e}")
        with _dedup_lock:
            _mem.append({"id": _mem_next_id, "title": title, "body": body,
                         "type": ntype, "category": category,
                         "timestamp": _now(), "read": False})
            payload = dict(_mem[-1])
            _mem_next_id += 1
            if len(_mem) > 100:
                _mem[:] = _mem[-100:]

    # 推送 SSE 事件（前端实时弹窗）
    try:
        from event_bus import push_event
        push_event('notification', payload)
    except Exception:
        pass
    try:
        logger.info(f"[通知] {title} — {body}")
    except Exception:
        pass
    return payload


def _query(since_id: int = 0, unread_only: bool = False, limit: int = 50) -> list:
    try:
        from db import get_conn
        with get_conn() as conn:
            sql = "SELECT id,title,body,type,category,created_at,read_at FROM notifications WHERE id > ?"
            args = [since_id]
            if unread_only:
                sql += " AND read_at IS NULL"
            sql += " ORDER BY id ASC LIMIT ?"
            args.append(limit)
            return [dict(r) for r in conn.execute(sql, args).fetchall()]
    except Exception:
        with _dedup_lock:
            return [n for n in _mem if (not unread_only or not n.get('read')) and n['id'] > since_id][:limit]


@bp.route('/api/notifications')
def get_notifications():
    """读取通知（**不修改已读状态**）。

    参数：
      since_id     只返回 id 大于该值的通知（前端增量轮询用）
      unread_only  1=只要未读
      limit        默认 50
    """
    try:
        since_id = int(request.args.get('since_id', '0') or 0)
    except ValueError:
        since_id = 0
    unread_only = request.args.get('unread_only', '0') in ('1', 'true', 'yes')
    try:
        limit = min(int(request.args.get('limit', '50') or 50), 200)
    except ValueError:
        limit = 50

    items = _query(since_id, unread_only, limit)
    # 兼容旧前端：无参数调用时仍返回最近未读，但**不标记已读**
    return jsonify({"notifications": items, "count": len(items)})


@bp.route('/api/notifications/read', methods=['POST'])
def mark_read():
    """显式标记已读。body: {"ids":[...]} 或 {"all": true}"""
    data = request.get_json(force=True, silent=True) or {}
    ids = data.get('ids') or []
    mark_all = bool(data.get('all'))
    now = _now()
    try:
        from db import get_conn
        with get_conn() as conn:
            if mark_all:
                conn.execute("UPDATE notifications SET read_at=? WHERE read_at IS NULL", (now,))
            elif ids:
                placeholders = ','.join('?' * len(ids))
                conn.execute(
                    f"UPDATE notifications SET read_at=? WHERE read_at IS NULL AND id IN ({placeholders})",
                    (now, *ids),
                )
            else:
                return jsonify({"error": "需要 ids 或 all"}), 400
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.warning(f"标记已读失败: {e}")
        with _dedup_lock:
            for n in _mem:
                if mark_all or n['id'] in ids:
                    n['read'] = True
        return jsonify({"status": "ok"})


@bp.route('/api/notifications/unread_count')
def unread_count():
    try:
        from db import get_conn
        with get_conn() as conn:
            n = conn.execute("SELECT COUNT(*) FROM notifications WHERE read_at IS NULL").fetchone()[0]
        return jsonify({"count": n})
    except Exception:
        with _dedup_lock:
            return jsonify({"count": sum(1 for n in _mem if not n.get('read'))})
