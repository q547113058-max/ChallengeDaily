"""待办看板桥接：把「屏幕追踪自动待办」的线上同步服务代理到同源 /api/bridge/*。

为什么要代理：同步服务部署在公网上且未开 CORS，浏览器直连会被跨域拦截；
同时把 X-Todo-Token 放在后端，避免暴露给前端 JS。

配置（环境变量，均可选；未配置时桥接自动禁用，看板只显示本地待办）：
  TODO_SYNC_URL        例 http://193.112.246.85:18766
  TODO_SYNC_TOKEN      写 token（标记完成/忽略需要）
  TODO_SYNC_TIMEOUT    请求超时秒，默认 6
"""
import json
import os
import queue
import threading
import urllib.error
import urllib.request
from flask import Blueprint, jsonify, request, Response, stream_with_context

bp = Blueprint('bridge', __name__, url_prefix='/api/bridge')

_BASE = os.getenv('TODO_SYNC_URL', '').strip().rstrip('/')
_TOKEN = os.getenv('TODO_SYNC_TOKEN', '').strip()
_TIMEOUT = float(os.getenv('TODO_SYNC_TIMEOUT', '6') or '6')


def _forward(method: str, path: str, payload=None):
    """转发请求到同步服务。返回 (json_dict, http_status)。"""
    if not _BASE:
        return {'ok': False, 'error': 'bridge_not_configured'}, 503
    url = _BASE + path
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None
    headers = {'X-Todo-Token': _TOKEN, 'Content-Type': 'application/json; charset=utf-8'}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            _note_sync_recovered()
            return json.loads(r.read().decode('utf-8')), r.status
    except urllib.error.HTTPError as e:
        # 已连上但业务报错（4xx/5xx）→ 不算"同步服务不可达"，不告警
        try:
            return json.loads(e.read().decode('utf-8')), e.code
        except Exception:
            return {'ok': False, 'error': f'upstream {e.code}'}, e.code
    except Exception as e:
        _note_sync_failed(str(e))
        return {'ok': False, 'error': str(e)[:120]}, 502


# ── 同步失败/恢复通知（同类 10 分钟内去重，由 notifications 模块统一处理）──
_sync_ok_flag = {'ok': True}


def _note_sync_failed(reason: str) -> None:
    """同步服务不可达：发一次警告（去重交给 dedup_key）。"""
    if not _sync_ok_flag['ok']:
        return  # 已经报过，等恢复后再报
    _sync_ok_flag['ok'] = False
    try:
        from routes.notifications import add_notification
        add_notification(
            '数据同步中断',
            f'无法连接待办同步服务（{_BASE}）：{reason[:80]}。本地功能不受影响。',
            'warning', category='sync', dedup_key='sync_down',
        )
    except Exception:
        pass


def _note_sync_recovered() -> None:
    """同步恢复：若之前报过中断，发一条恢复通知。"""
    if _sync_ok_flag['ok']:
        return
    _sync_ok_flag['ok'] = True
    try:
        from routes.notifications import add_notification
        add_notification(
            '数据同步已恢复',
            f'已重新连上待办同步服务（{_BASE}）',
            'success', category='sync', dedup_key='sync_up',
        )
    except Exception:
        pass


@bp.route('/status', methods=['GET'])
def bridge_status():
    """前端据此判断「自动待办」区块是否可用。"""
    if not _BASE:
        return jsonify({'ok': True, 'enabled': False, 'reason': 'TODO_SYNC_URL 未配置'})
    body, code = _forward('GET', '/api/health')
    return jsonify({'ok': code == 200, 'enabled': code == 200, 'upstream': body}), code


@bp.route('/todos', methods=['GET'])
def bridge_todos():
    status = request.args.get('status', 'pending')
    if status not in ('proposed', 'pending', 'done', 'dismissed', 'all'):
        status = 'pending'
    body, code = _forward('GET', f'/api/todos?status={status}')
    return jsonify(body), code


@bp.route('/todos/<int:tid>/status', methods=['POST'])
def bridge_set_status(tid):
    data = request.get_json(force=True, silent=True) or {}
    status = str(data.get('status', '')).strip()
    if status not in ('done', 'dismissed'):
        return jsonify({'ok': False, 'error': 'bad status'}), 400
    body, code = _forward('POST', f'/api/todos/{tid}/status', {'status': status})
    return jsonify(body), code


@bp.route('/todos/<int:tid>/<action>', methods=['POST'])
def bridge_decide(tid, action):
    """审批：action = approve（加入待办）| reject（忽略）。"""
    if action not in ('approve', 'reject'):
        return jsonify({'ok': False, 'error': 'bad action'}), 404
    body, code = _forward('POST', f'/api/todos/{tid}/{action}', {})
    return jsonify(body), code


@bp.route('/events', methods=['GET'])
def bridge_events():
    """SSE 流式代理：把线上同步服务的事件流转发给浏览器。

    - 用后台线程读上游（避免 urllib 阻塞 Flask 工作线程、客户端断开后线程泄漏）
    - 每 20s 心跳，防止反代/浏览器超时
    - 客户端断开时立刻关闭上游 response
    """
    # SSE 走 EventSource，不能带自定义 header；全局鉴权已为此路径放行，
    # 这里必须自行校验：query param token 或本机请求（浏览器 shell 经 ui-server 代理）二选一。
    import hmac
    from routes.deps import LOCAL_TOKEN
    from flask import request as _req
    qtok = _req.args.get('token', '')
    is_local = (_req.remote_addr or '') in ('127.0.0.1', '::1', 'localhost')
    token_ok = bool(LOCAL_TOKEN) and hmac.compare_digest(qtok, LOCAL_TOKEN)
    if not (token_ok or is_local):
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401

    if not _BASE:
        def disabled():
            yield 'data: {"action":"disabled"}\n\n'
            while True:
                yield ': ping\n\n'
                threading.Event().wait(20)
        return Response(stream_with_context(disabled()), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    q = queue.Queue(maxsize=100)
    upstream = {'resp': None}

    def reader():
        req = urllib.request.Request(_BASE + '/api/events',
                                     headers={'X-Todo-Token': _TOKEN}, method='GET')
        try:
            with urllib.request.urlopen(req, timeout=None) as r:
                upstream['resp'] = r
                while True:
                    raw = r.readline()
                    if not raw:
                        break
                    # 原样透传（含空行与注释行），不做重组，避免 SSE 帧被拆坏
                    try:
                        q.put_nowait(raw)
                    except queue.Full:
                        pass
        except Exception as e:
            try:
                q.put_nowait(('data: ' + json.dumps(
                    {"action": "error", "error": str(e)[:100]}) + '\n\n').encode('utf-8'))
            except queue.Full:
                pass
        finally:
            try:
                q.put_nowait(b'')  # EOF 哨兵
            except queue.Full:
                pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    def generate():
        try:
            yield b': connected\n\n'
            while True:
                try:
                    chunk = q.get(timeout=20)
                    if chunk == b'':
                        yield b': reconnect\n\n'
                        break
                    yield chunk
                except queue.Empty:
                    yield b': ping\n\n'
        finally:
            r = upstream.get('resp')
            if r:
                try:
                    r.close()
                except Exception:
                    pass

    return Response(stream_with_context(generate()), mimetype='text/event-stream',
                    headers={
                        'Cache-Control': 'no-cache',
                        'X-Accel-Buffering': 'no',
                        'Connection': 'keep-alive',
                    })
