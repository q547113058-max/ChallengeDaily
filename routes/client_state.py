"""通用客户端状态（Client State）API — 把原本存在浏览器 localStorage 的数据搬到服务器。

设计要点：
  * 单机服务器、单租户、无账号体系：数据全部落在后端 DATA_DIR 下的
    ``client_state.json``（与 SQLite 主库同目录，便于备份 / 自毁 / 迁移）。
  * 沿用现有鉴权：server.py 的全局 ``auth_check`` 已要求 X-API-Token，
    这里再做一次 ``deps.check_token`` 与白名单校验，纵深防御。
  * 只接受 ``cd_`` 前缀的键，避免变成任意文件写入接口。
  * 值统一为字符串（与 localStorage 完全一致），前端读到的就是原值，
    不需要改动任何解析逻辑。
  * ``GET`` 响应强制 ``no-store``，绕过 server.py 对 GET JSON 的 ETag/5s 缓存。
  * 写入是整份覆盖（前端每次携带全量快照），服务端用原子替换落盘，
    避免并发写导致文件损坏；单进程本地服务场景下足够安全。
"""
import json
import logging
import os
import tempfile
import threading
from datetime import datetime

from flask import Blueprint, jsonify, request

import routes.deps as deps

logger = logging.getLogger(__name__)

bp = Blueprint('client_state', __name__, url_prefix='/api/client-state')

# 与 config.DATA_DIR 保持一致（延迟导入，避免影响 routes 包加载顺序）
from config import DATA_DIR  # noqa: E402

STATE_PATH = DATA_DIR / 'client_state.json'
_MAX_KEYS = 128
_MAX_KEY_LEN = 64
_MAX_VALUE_LEN = 64 * 1024
_ALLOWED_PREFIX = 'cd_'
_write_lock = threading.Lock()


def _read_state() -> dict:
    """读取状态文件；不存在 / 损坏时返回空字典（不抛错，保证前端能启动）。"""
    try:
        if not STATE_PATH.exists():
            return {}
        raw = STATE_PATH.read_text(encoding='utf-8')
        data = json.loads(raw)
        if not isinstance(data, dict):
            logger.warning('client_state.json 根节点不是对象，按空状态处理')
            return {}
        return {k: v for k, v in data.items()
                if isinstance(k, str) and isinstance(v, str)
                and k.startswith(_ALLOWED_PREFIX)}
    except Exception as e:
        logger.warning(f'读取 client_state.json 失败，按空状态处理: {e}')
        return {}


def _write_state(state: dict) -> None:
    """原子写：先写同目录临时文件，再 os.replace，避免半截文件。"""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
    fd, tmp = tempfile.mkstemp(prefix='.client_state-', suffix='.json', dir=str(STATE_PATH.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STATE_PATH)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _validate_state(data) -> tuple[dict | None, str | None]:
    """校验前端提交的全量快照；返回 (规范化后的 dict, 错误信息)。"""
    if not isinstance(data, dict):
        return None, 'state 必须是对象'
    if len(data) > _MAX_KEYS:
        return None, f'键数量超过上限（{_MAX_KEYS}）'
    cleaned = {}
    for k, v in data.items():
        if not isinstance(k, str) or not k.startswith(_ALLOWED_PREFIX):
            return None, f'非法键名: {str(k)[:40]}'
        if len(k) > _MAX_KEY_LEN:
            return None, f'键名过长: {k[:40]}'
        if v is None:
            # null 表示删除该键（对齐 localStorage.removeItem 语义）
            continue
        if not isinstance(v, str):
            return None, f'键 {k} 的值必须是字符串或 null'
        if len(v) > _MAX_VALUE_LEN:
            return None, f'键 {k} 的值过大'
        cleaned[k] = v
    return cleaned, None


def _persist(cleaned: dict) -> None:
    with _write_lock:
        _write_state(cleaned)


@bp.route('', methods=['GET'])
def get_state():
    """获取全部客户端状态（前端启动时调用一次，之后读写内存缓存）。"""
    if not deps.check_token(request):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        state = _read_state()
    except Exception as e:
        logger.error(f'获取客户端状态失败: {e}', exc_info=True)
        return jsonify({"error": str(e)[:80]}), 500
    resp = jsonify({"state": state, "updated_at": _mtime_iso()})
    # 绕过 server.py 的 GET JSON ETag / private,max-age=5 缓存
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    resp.headers.pop('ETag', None)
    return resp


def _mtime_iso() -> str | None:
    try:
        return datetime.fromtimestamp(STATE_PATH.stat().st_mtime).isoformat(timespec='seconds')
    except OSError:
        return None


@bp.route('', methods=['PUT'])
def put_state():
    """整份覆盖写入客户端状态（前端每次携带全量快照）。"""
    if not deps.check_token(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True)
    state, err = _validate_state(data.get('state') if isinstance(data, dict) else None)
    if err:
        return jsonify({"error": err}), 400
    try:
        _persist(state)
    except Exception as e:
        logger.error(f'写入客户端状态失败: {e}', exc_info=True)
        return jsonify({"error": str(e)[:80]}), 500
    return jsonify({"status": "ok", "count": len(state)})


@bp.route('', methods=['PATCH'])
def patch_state():
    """按变更集合并写入（多窗口/多设备共享同一份状态时避免互相覆盖）。

    请求体 ``{"state": {key: value | null}}``：只更新这些键，
    ``null`` 表示删除；其他键保持原样。返回合并后的全量状态，
    前端可据此刷新缓存（顺便拿到别的窗口刚写的改动）。
    """
    if not deps.check_token(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True)
    changes, err = _validate_changes(data)
    if err:
        return jsonify({"error": err}), 400
    try:
        with _write_lock:
            current = _read_state()
            for k, v in changes.items():
                if v is None:
                    current.pop(k, None)
                else:
                    current[k] = v
            _write_state(current)
        resp = jsonify({"status": "ok", "state": current})
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        return resp
    except Exception as e:
        logger.error(f'合并客户端状态失败: {e}', exc_info=True)
        return jsonify({"error": str(e)[:80]}), 500


def _validate_changes(data) -> tuple[dict | None, str | None]:
    """校验变更集：允许 value=null 表示删除该键。"""
    if not isinstance(data, dict) or not isinstance(data.get('state'), dict):
        return None, 'state 必须是对象'
    raw = data['state']
    if len(raw) > _MAX_KEYS:
        return None, f'键数量超过上限（{_MAX_KEYS}）'
    cleaned = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not k.startswith(_ALLOWED_PREFIX):
            return None, f'非法键名: {str(k)[:40]}'
        if len(k) > _MAX_KEY_LEN:
            return None, f'键名过长: {k[:40]}'
        if v is None:
            cleaned[k] = None
        elif isinstance(v, str):
            if len(v) > _MAX_VALUE_LEN:
                return None, f'键 {k} 的值过大'
            cleaned[k] = v
        else:
            return None, f'键 {k} 的值必须是字符串或 null'
    return cleaned, None


@bp.route('/migrate', methods=['POST'])
def migrate_state():
    """一次性迁移：接收旧版浏览器 localStorage 的全量快照并合并入库。

    仅合并服务器上尚不存在的键（不覆盖服务端已有的新值），避免用户
    在新版产生的数据被旧浏览器残留数据回滚。
    """
    if not deps.check_token(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True)
    incoming, err = _validate_state(data.get('state') if isinstance(data, dict) else None)
    if err:
        return jsonify({"error": err}), 400
    try:
        with _write_lock:
            current = _read_state()
            merged = dict(incoming)
            merged.update(current)  # 服务端已有值优先
            _write_state(merged)
        return jsonify({"status": "ok", "migrated": len(incoming), "total": len(merged)})
    except Exception as e:
        logger.error(f'迁移客户端状态失败: {e}', exc_info=True)
        return jsonify({"error": str(e)[:80]}), 500


@bp.route('/seed', methods=['POST'])
def seed_state():
    """供自动化验证使用：写入首启标记（等价于旧的 /__seed 页面脚本）。"""
    if not deps.check_token(request):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        with _write_lock:
            current = _read_state()
            current['cd_legal_accepted'] = '1'
            current['cd_onboarding_done'] = '1'
            _write_state(current)
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f'写入首启标记失败: {e}', exc_info=True)
        return jsonify({"error": str(e)[:80]}), 500
