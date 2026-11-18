# -*- coding: utf-8 -*-
"""
多租户注册表（CentOS 7 / Python 3.6 标准库，零第三方依赖）。

设计：
  * 一个 JSON 文件 tenants.json 保存租户列表：
      {
        "tenants": {
          "<tenant_id>": {
            "name": "显示名",
            "token": "<该租户唯一 API Token>",
            "created_at": "ISO",
            "enabled": true
          }
        },
        "admins": ["<admin token>", ...]
      }
  * 每个租户的数据放在 DATA_DIR/tenants/<tenant_id>/ 下：
      synced.db          —— 采集数据（独立 DB）
      client_state.json  —— 前端状态
  * token -> tenant_id 映射从注册表构建，用于请求鉴权后切换数据目录。
  * 单个 admin token 可以管理（创建/删除/列表）所有租户。

向后兼容：初始化时若注册表为空，把旧的 DATA_DIR/.api_token + synced.db
迁移为 "default" 租户；旧 token 继续可用。
"""
import os
import json
import hmac
import threading
import hashlib
import shutil
import binascii
from datetime import datetime

# 租户登录密码：PBKDF2-HMAC-SHA256（标准库，Python 3.6 可用）
_PBKDF2_ITER = 100000
_PW_SALT_BYTES = 16


def hash_password(password):
    """返回 'pbkdf2$<iter>$<salt_hex>$<hash_hex>'。"""
    salt = os.urandom(_PW_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, _PBKDF2_ITER)
    return 'pbkdf2$%d$%s$%s' % (_PBKDF2_ITER, binascii.hexlify(salt).decode('ascii'),
                                binascii.hexlify(dk).decode('ascii'))


def verify_password(password, encoded):
    """校验密码；返回 (ok, need_rehash)。兼容旧明文（自动升级）。"""
    if not encoded:
        return False, False
    if not encoded.startswith('pbkdf2$'):
        # 旧数据兼容：明文相等即可，并建议升级
        return hmac.compare_digest(str(password), str(encoded)), True
    try:
        parts = encoded.split('$')
        iter_n = int(parts[1])
        salt = binascii.unhexlify(parts[2])
        want = binascii.unhexlify(parts[3])
        got = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iter_n)
        return hmac.compare_digest(got, want), False
    except Exception:
        return False, False


DATA_DIR = os.environ.get("CD_DATA_DIR", "/opt/challengedaily/data")
REGISTRY_FILE = os.environ.get("CD_TENANTS_FILE", os.path.join(DATA_DIR, "tenants.json"))
ADMIN_TOKEN_FILE = os.environ.get("CD_ADMIN_TOKEN_FILE", os.path.join(DATA_DIR, ".admin_token"))
LEGACY_TOKEN_FILE = os.environ.get("CD_TOKEN_FILE", os.path.join(DATA_DIR, ".api_token"))

_lock = threading.RLock()
_registry = None


def _now():
    return datetime.now().isoformat()


def _fresh():
    return {"tenants": {}, "admins": []}


def _load():
    global _registry
    with _lock:
        if _registry is not None:
            return _registry
        data = _fresh()
        if os.path.isfile(REGISTRY_FILE):
            try:
                with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data.setdefault("tenants", {})
                    data.setdefault("admins", [])
                    if isinstance(loaded.get("tenants"), dict):
                        data["tenants"] = loaded["tenants"]
                    if isinstance(loaded.get("admins"), list):
                        data["admins"] = loaded["admins"]
            except Exception:
                pass
        _registry = data
        _migrate_legacy_locked()
        return _registry


def _save_locked():
    os.makedirs(os.path.dirname(REGISTRY_FILE), exist_ok=True)
    tmp = REGISTRY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_registry, f, ensure_ascii=False, indent=2)
    try:
        os.replace(tmp, REGISTRY_FILE)
    except OSError:
        os.rename(tmp, REGISTRY_FILE)
    try:
        os.chmod(REGISTRY_FILE, 0o600)
    except OSError:
        pass


def _migrate_legacy_locked():
    """首次运行：把旧的单一 token 迁移为 default 租户，避免现有用户断线。"""
    if _registry["tenants"]:
        return
    legacy = ""
    if os.path.isfile(LEGACY_TOKEN_FILE):
        try:
            with open(LEGACY_TOKEN_FILE, "r", encoding="utf-8") as f:
                legacy = f.read().strip()
        except Exception:
            pass
    if not legacy:
        return
    _registry["tenants"]["default"] = {
        "name": "默认租户",
        "token": legacy,
        "created_at": _now(),
        "enabled": True,
    }
    # 把旧数据文件移到 default 目录（存在才移）
    tdir = tenant_dir("default")
    os.makedirs(tdir, exist_ok=True)
    for name in ("synced.db", "synced.db-wal", "synced.db-shm", "client_state.json"):
        src = os.path.join(DATA_DIR, name)
        dst = os.path.join(tdir, name)
        if os.path.isfile(src) and not os.path.isfile(dst):
            try:
                os.rename(src, dst)
            except OSError:
                pass
    _save_locked()


def _safe_id(tenant_id):
    """tenant_id 只能含安全字符，防目录穿越。"""
    if not tenant_id or len(tenant_id) > 64:
        return None
    ok = all(c.isalnum() or c in "-_" for c in tenant_id)
    return tenant_id if ok else None


def tenant_dir(tenant_id):
    tid = _safe_id(tenant_id)
    if not tid:
        return os.path.join(DATA_DIR, "tenants", "_invalid")
    return os.path.join(DATA_DIR, "tenants", tid)


def get_admin_tokens():
    toks = list(_load()["admins"])
    if os.path.isfile(ADMIN_TOKEN_FILE):
        try:
            with open(ADMIN_TOKEN_FILE, "r", encoding="utf-8") as f:
                t = f.read().strip()
            if t and t not in toks:
                toks.append(t)
        except Exception:
            pass
    return toks


def is_admin(headers):
    got = headers.get("X-API-Token", "") or headers.get("X-Admin-Token", "")
    return any(hmac.compare_digest(got, t) for t in get_admin_tokens() if t)


def resolve_tenant(headers):
    """根据 X-API-Token 返回 tenant_id；无效返回 None。"""
    got = headers.get("X-API-Token", "")
    if not got:
        return None
    for tid, info in _load()["tenants"].items():
        if not info.get("enabled", True):
            continue
        if hmac.compare_digest(got, str(info.get("token", ""))):
            return tid
    # admin token 不是租户 token
    return None


def tenant_token(tenant_id):
    info = _load()["tenants"].get(tenant_id)
    return str(info.get("token", "")) if info else ""


def list_tenants():
    out = []
    for tid, info in _load()["tenants"].items():
        out.append({
            "tenant_id": tid,
            "name": info.get("name", ""),
            "created_at": info.get("created_at", ""),
            "enabled": info.get("enabled", True),
            # 不返回 token / 密码 hash 明文，避免列表接口泄露
            "has_token": bool(info.get("token")),
            "has_password": bool(info.get("password_hash")),
        })
    return sorted(out, key=lambda x: x["tenant_id"])


def create_tenant(tenant_id, name, token=None, password=None):
    with _lock:
        reg = _load()
        tid = _safe_id(tenant_id)
        if not tid:
            return None, "invalid tenant_id"
        if tid in reg["tenants"]:
            return None, "tenant already exists"
        if not token:
            token = _new_unique_token_locked()
        else:
            token = str(token).strip()
            # token 冲突检测：一个 token 只能属于一个租户
            for other, info in reg["tenants"].items():
                if hmac.compare_digest(token, str(info.get("token", ""))):
                    return None, "token already used by tenant: %s" % other
        pw_hash = hash_password(password) if password else ""
        reg["tenants"][tid] = {
            "name": str(name or tid)[:64],
            "token": token,
            "password_hash": pw_hash,
            "created_at": _now(),
            "enabled": True,
        }
        os.makedirs(tenant_dir(tid), exist_ok=True)
        _save_locked()
        return {"tenant_id": tid, "name": reg["tenants"][tid]["name"],
                "token": token, "has_password": bool(pw_hash)}, None


def set_password(tenant_id, password):
    """管理员设置/重置租户登录密码。"""
    with _lock:
        reg = _load()
        if tenant_id not in reg["tenants"]:
            return False
        reg["tenants"][tenant_id]["password_hash"] = hash_password(password)
        _save_locked()
        return True


def login(tenant_id, password):
    """租户登录：校验 tenant_id + password，成功返回 (token, None)。"""
    with _lock:
        reg = _load()
        info = reg["tenants"].get(tenant_id)
        if not info:
            return None, "invalid tenant or password"
        if not info.get("enabled", True):
            return None, "tenant disabled"
        stored = str(info.get("password_hash", ""))
        if not stored:
            return None, "password not set for this tenant"
        ok, need_rehash = verify_password(str(password), stored)
        if not ok:
            return None, "invalid tenant or password"
        # 旧明文密码自动升级为 hash
        if need_rehash:
            info["password_hash"] = hash_password(str(password))
            _save_locked()
        return str(info["token"]), None


def set_tenant_enabled(tenant_id, enabled):
    with _lock:
        reg = _load()
        if tenant_id not in reg["tenants"]:
            return False
        reg["tenants"][tenant_id]["enabled"] = bool(enabled)
        _save_locked()
        return True


def rotate_token(tenant_id):
    with _lock:
        reg = _load()
        if tenant_id not in reg["tenants"]:
            return None
        token = _new_unique_token_locked()
        reg["tenants"][tenant_id]["token"] = token
        _save_locked()
        return token


def _new_unique_token_locked():
    """生成不与任何现有租户 token 冲突的新 token。"""
    reg = _load()
    used = set(str(v.get("token", "")) for v in reg["tenants"].values())
    while True:
        token = hashlib.sha256(os.urandom(32)).hexdigest()
        if token not in used:
            return token


def tenant_info(tenant_id):
    """给租户自己看的脱敏信息（不含完整 token）。"""
    info = _load()["tenants"].get(tenant_id)
    if not info:
        return None
    tok = str(info.get("token", ""))
    return {
        "tenant_id": tenant_id,
        "name": info.get("name", ""),
        "enabled": info.get("enabled", True),
        "created_at": info.get("created_at", ""),
        "token_hint": (tok[:6] + "…" + tok[-4:]) if len(tok) > 12 else "****",
    }


def tenant_stats(tenant_id):
    """租户数据概况：DB 大小、活动数（供管理后台展示）。"""
    tdir = tenant_dir(tenant_id)
    db = os.path.join(tdir, "synced.db")
    out = {"db_size_bytes": 0, "activities": 0}
    if os.path.isfile(db):
        out["db_size_bytes"] = os.path.getsize(db)
        try:
            import sqlite3
            con = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True, timeout=3)
            try:
                out["activities"] = con.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
            except Exception:
                pass
            finally:
                con.close()
        except Exception:
            pass
    return out


def delete_tenant(tenant_id, purge_data=True):
    """删除租户。purge_data=True 时同时删除其数据目录。"""
    with _lock:
        reg = _load()
        if tenant_id not in reg["tenants"]:
            return False
        del reg["tenants"][tenant_id]
        _save_locked()
        if purge_data:
            tdir = tenant_dir(tenant_id)
            # 二次校验：只允许删 tenants/ 下的合法 id 目录
            if _safe_id(tenant_id) and os.path.isdir(tdir) and \
                    os.path.dirname(os.path.abspath(tdir)) == os.path.abspath(os.path.join(DATA_DIR, "tenants")):
                try:
                    shutil.rmtree(tdir)
                except OSError:
                    pass
        return True
