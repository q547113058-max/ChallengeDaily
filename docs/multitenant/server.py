#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ChallengeDaily 服务器存储节点（独立部署版）

运行环境：CentOS 7 / Python 3.6.8，仅使用标准库，零第三方依赖。

职责：
  1) 托管前端静态页面（client/dist）
  2) 注入 /__shim.js —— 让前端走页面同源 /api 代理（getBackendPort()=0），
     并提供 X-API-Token（部署时生成，写入 /opt/challengedaily/data/.api_token）
  3) 提供 /api/client-state 系列接口，状态落盘到服务器本地 JSON 文件
  4) 其余 /api/* 转发给「Windows 本机后端」（可选，通过反向 SSH 隧道/内网地址）

为什么不用原 Flask 后端：原后端依赖 mss / pywin32 / win32security 等 Windows
专有库，Linux 上无法运行。采集仍在用户 Windows 本机，服务器只做数据存储与页面。

配置全部走环境变量（由 systemd EnvironmentFile 提供）：
  CD_LISTEN_HOST      默认 0.0.0.0
  CD_LISTEN_PORT      默认 5173
  CD_DATA_DIR         默认 /opt/challengedaily/data
  CD_STATIC_DIR       默认 /opt/challengedaily/dist
  CD_API_TOKEN        必填（也可由 CD_TOKEN_FILE 指定文件）
  CD_UPSTREAM         可选，形如 http://127.0.0.1:58888（Windows 后端经隧道可达时）
"""
import os
import time
import io
import json
import hmac
import logging
import threading
import posixpath
import mimetypes
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
try:
    from socketserver import ThreadingMixIn
except ImportError:  # pragma: no cover
    from SocketServer import ThreadingMixIn
from urllib.parse import urlparse, unquote, parse_qs

try:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
except ImportError:  # pragma: no cover
    from urllib2 import Request, urlopen, HTTPError, URLError

# 采集数据同步与查询（同目录模块，纯标准库）
sys_path = os.path.dirname(os.path.abspath(__file__))
if sys_path not in __import__("sys").path:
    __import__("sys").path.insert(0, sys_path)
import data_api
import queries
import tenant_store

# ── 多租户上下文 ──────────────────────────────────────────────────────────
# 每个 HTTP 请求独立线程；鉴权后设置该线程的租户上下文（DB 路径 + state 文件）。
_ctx = threading.local()


def _set_tenant(tid):
    """把当前请求线程切换到指定租户的数据目录。tid=None 表示默认（兼容）。"""
    _ctx.tenant_id = tid
    if tid:
        tdir = tenant_store.tenant_dir(tid)
        os.makedirs(tdir, exist_ok=True)
        _ctx.state_file = os.path.join(tdir, "client_state.json")
        data_api.set_tenant_db(os.path.join(tdir, "synced.db"))
    else:
        if hasattr(_ctx, "state_file"):
            del _ctx.state_file
        data_api.clear_tenant_db()


def _cur_state_file():
    return getattr(_ctx, "state_file", None) or STATE_FILE


def _cur_tenant():
    return getattr(_ctx, "tenant_id", None)

def date_today_str():
    from datetime import date as _date
    return _date.today().isoformat()


# ── 配置 ────────────────────────────────────────────────────────────────
LISTEN_HOST = os.environ.get("CD_LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("CD_LISTEN_PORT", "5173"))
DATA_DIR = os.environ.get("CD_DATA_DIR", "/opt/challengedaily/data")
STATIC_DIR = os.environ.get("CD_STATIC_DIR", "/opt/challengedaily/dist")
UPDATES_DIR = os.environ.get("CD_UPDATES_DIR", "/opt/challengedaily/updates")
UPSTREAM = os.environ.get("CD_UPSTREAM", "").rstrip("/")  # 可选：Windows 后端
TOKEN_FILE = os.environ.get("CD_TOKEN_FILE", os.path.join(DATA_DIR, ".api_token"))
STATE_FILE = os.path.join(DATA_DIR, "client_state.json")
LOG_FILE = os.environ.get("CD_LOG_FILE", os.path.join(DATA_DIR, "server.log"))

# 采集数据查询接口：路径 -> (查询函数, 是否需要 token)
# 这些接口由 Windows 同步代理推送的真实 SQLite 数据驱动（data_api / queries）。
DATA_ROUTES = {
    "/api/activities": (queries.activities, True),
    "/api/activities/search": (queries.activities_search, True),
    "/api/timeline": (queries.timeline, True),
    "/api/app-usage": (queries.app_usage, True),
    "/api/stats/today": (queries.stats_today, True),
    "/api/stats/hourly": (queries.stats_hourly, True),
    "/api/stats/trend": (queries.stats_trend, True),
    "/api/stats/rhythm": (queries.stats_rhythm, True),
    "/api/stats/recent-heatmap": (queries.stats_recent_heatmap, True),
    "/api/stats/calendar": (queries.stats_calendar, True),
    "/api/stats/sankey": (queries.stats_sankey, True),
    "/api/stats/heatmap": (queries.stats_heatmap, True),
    "/api/daily-summary": (queries.daily_summary, True),
    "/api/todos": (queries.todos, True),
    "/api/habits": (queries.habits, True),
    "/api/goals": (queries.goals, True),
    "/api/goals/summary": (queries.goals_summary, True),
    "/api/report": (queries.reports, True),
    "/api/report/daily/content": (queries.report_daily_content, True),
    "/api/report/daily": (queries.report_daily, True),
    "/api/report/weekly": (queries.report_weekly, True),
    "/api/report/monthly": (queries.report_monthly, True),
    "/api/achievements": (queries.achievements, True),
    "/api/profile": (queries.profile, True),
    "/api/backup/info": (queries.backup_info, True),
    "/api/status": (queries.app_status, True),
    # Overview / 报告 / 计划等页面必需：返回真实或合法空结构
    "/api/report/search": (queries.report_search, True),
    "/api/week-plan/stats": (queries.week_plan_stats, True),
    "/api/week-plan/unassigned": (lambda q: ({"todos": []}, None), True),
    "/api/week-plan/today": (lambda q: ({"todos": [], "date": date_today_str()}, None), True),
    "/api/goals/mood-heatmap": (queries.goals_mood_heatmap, True),
    "/api/habits/recommend": (queries.habit_recommend, True),
    "/api/profile/analysis": (queries.profile_analyses, True),
    "/api/audit/logs": (queries.audit_logs, True),
    "/api/audit/stats": (queries.audit_stats, True),
    "/api/app-rules": (queries.app_rules, True),
    "/api/app-rules/known": (queries.known_apps, True),
    "/api/credibility/daily-report": (queries.credibility_daily, True),
    "/api/reports/templates": (queries.report_templates, True),
    "/api/report/weekly-goal": (queries.weekly_goal, True),
    "/api/ai/overview-summary": (queries.overview_summary, True),
    "/api/achievements/quote": (queries.ai_quote, True),
    "/api/notifications": (lambda q: ({"notifications": []}, None), True),
    "/api/webhooks": (lambda q: ({"webhooks": []}, None), True),
    "/api/auto-report/config": (lambda q: ({"enabled": False, "auto_time": "21:00", "auto_push": False}, None), True),
    "/api/report-channels/config": (lambda q: ({"channels": []}, None), True),
    "/api/calendar/subscriptions": (lambda q: ({"subscriptions": []}, None), True),
    "/api/calendar/today": (lambda q: ({"events": []}, None), True),
    "/api/calendar/upcoming": (lambda q: ({"events": []}, None), True),
    "/api/calendar/current-meeting": (lambda q: ({"meeting": None, "in_meeting": False}, None), True),
    "/api/git/repositories": (lambda q: ({"repositories": []}, None), True),
    "/api/profile/weekly-context": (lambda q: ({"context": ""}, None), True),
    "/api/profile/distilled": (lambda q: ({"work_habits": {}, "common_software": [], "work_content": {}, "behavior_patterns": {}, "efficiency_trend": []}, None), True),
    "/api/deep-insight": (lambda q: ({"status": "ok", "date": date_today_str(), "data_points": 0, "frameworks": {}, "summary": {"findings": [], "positive_count": 0, "negative_count": 0, "overall": ""}}, None), True),
    "/api/report/deep-insights": (lambda q: ({"status": "ok", "insights": {"weekly_stats": [], "trends": [], "patterns": {}, "benchmark": [], "benchmarks_definition": {}}}, None), True),
    "/api/health/coverage": (lambda q: ({"date": date_today_str(), "system": {}, "collected": {}, "gap": {}}, None), True),
    "/api/health/system-events": (lambda q: ({"date": date_today_str(), "boot_events": [], "login_events": [], "sessions": [], "current_boot_time": None, "uptime_sec": 0}, None), True),
    "/api/health/sampling-deviation": (lambda q: ({"date": date_today_str(), "sample_count": 0, "interval_count": 0, "interval_stats": {}, "expected_interval_sec": 60, "deviation": {}, "intervals": []}, None), True),
    # ── 纯读兜底：避免 server-only 501 打断前端只读请求 ──
    "/api/notifications/unread_count": (lambda q: ({"count": 0}, None), True),
    "/api/icons": (lambda q: ({"icons": {}}, None), True),
    "/api/export/activities": (lambda q: ({"activities": []}, None), True),
    "/api/exports/reports": (lambda q: ({"reports": []}, None), True),
    "/api/report/export/obsidian": (lambda q: ({"status": "ok", "exported": 0}, None), True),
    "/api/git/code-report": (lambda q: ({"status": "ok", "report": ""}, None), True),
    "/api/git/weekly-report": (lambda q: ({"status": "ok", "report": ""}, None), True),
}

# 动态路径前缀：fn(rest, q) -> (obj, err)
def _dyn_goals(rest, q):
    if rest.endswith("/progress"):
        return queries.goals_progress(q, rest.split("/")[0])
    if rest.endswith("/mood-heatmap"):
        return queries.goals_mood_heatmap(q)
    return None, "not_found"


def _dyn_habits(rest, q):
    if rest.endswith("/stats"):
        return queries.habit_stats(q, rest.split("/")[0])
    return None, "not_found"


DATA_DYNAMIC_PREFIXES = [
    ("/api/stats/date/", lambda rest, q: queries.stats_today(q, rest)),
    ("/api/report/date/", lambda rest, q: queries.report_by_date(q, rest)),
    ("/api/week-plan/month/", lambda rest, q: queries.week_plan_month(q, rest)),
    ("/api/week-plan/week/", lambda rest, q: queries.week_plan_week(q, rest)),
    ("/api/goals/", _dyn_goals),
    ("/api/habits/", _dyn_habits),
    ("/api/profile/daily/", lambda rest, q: queries.profile_daily(q, rest)),
    ("/api/activities/", lambda rest, q: ({"activity": None}, None)),
    ("/api/todos/", lambda rest, q: ({"todo": None}, None)),
    ("/api/icons/", lambda rest, q: ({"icon": None}, None)),
    ("/api/profile/analysis/", lambda rest, q: queries.profile_analysis_by_type(q, rest)),
]

# server-only 模式下，对少数未实现接口的兜底响应。
# 采集数据接口已在上面由真实 SQLite 提供，这里只留设置/偏好类占位。
SERVER_ONLY_DEFAULTS = {
    "/api/settings": {"ai_enabled": False, "ai_base_url": "", "ai_vision_model": "",
                      "ai_text_model": "", "work_start_hour": 9, "work_end_hour": 18},
    "/api/notifications": {"notifications": []},
    "/api/preferences": {"preferences": {
        "nickname": "", "greeting_enabled": True, "report_style": "balanced",
        "encouragement_level": "warm", "disclosure_level": "beginner",
        "tooltip_enabled": True}},
    "/api/webhooks": {"webhooks": []},
    "/api/quote": {"quote": "", "author": ""},  # 空文案时前端 QuoteBar 自动隐藏
    "/api/greeting": {"greeting": "欢迎回来，今天也来看看自己的时间流向吧。"},
}

MAX_KEYS = 128
MAX_KEY_LEN = 64
MAX_VALUE_LEN = 64 * 1024
MAX_BODY = 32 * 1024 * 1024  # 32MB：全量同步含 windows_json 的活动记录
ALLOWED_PREFIX = "cd_"

_state_lock = threading.Lock()
_api_token = ""

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("cd")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".ico": "image/x-icon", ".webp": "image/webp",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf",
    ".otf": "font/otf", ".map": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


# ── 状态存储 ────────────────────────────────────────────────────────────
def read_state():
    try:
        sf = _cur_state_file()
        if not os.path.exists(sf):
            return {}
        with io.open(sf, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            log.warning("state root is not object, treating as empty")
            return {}
        return dict((k, v) for k, v in data.items()
                    if isinstance(k, str) and isinstance(v, str)
                    and k.startswith(ALLOWED_PREFIX))
    except Exception as e:
        log.warning("read state failed, treating as empty: %s", e)
        return {}


def write_state(state):
    """原子写：同目录临时文件 + os.replace。"""
    sf = _cur_state_file()
    sdir = os.path.dirname(sf)
    if not os.path.isdir(sdir):
        os.makedirs(sdir)
    payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
    tmp = sf + ".tmp.%s" % os.getpid()
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    # 状态里可能含应用锁密码 hash：仅属主可读写
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, sf)


def validate_state(raw, allow_null=False):
    """返回 (cleaned, error)。allow_null=True 时 null 表示删除。"""
    if not isinstance(raw, dict):
        return None, "state must be an object"
    if len(raw) > MAX_KEYS:
        return None, "too many keys (max %d)" % MAX_KEYS
    cleaned = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not k.startswith(ALLOWED_PREFIX):
            return None, "illegal key: %s" % str(k)[:40]
        if len(k) > MAX_KEY_LEN:
            return None, "key too long"
        if v is None and allow_null:
            cleaned[k] = None
            continue
        if not isinstance(v, str):
            return None, "value of %s must be string%s" % (k, " or null" if allow_null else "")
        if len(v) > MAX_VALUE_LEN:
            return None, "value of %s too large" % k
        cleaned[k] = v
    return cleaned, None


def mtime_iso():
    try:
        return datetime.fromtimestamp(os.path.getmtime(_cur_state_file())).isoformat()
    except OSError:
        return None


def token_ok(headers):
    """鉴权：admin token / 租户 token / 旧的单 token 都接受。"""
    got = headers.get("X-API-Token", "") or ""
    if not got:
        return False
    # admin token 优先
    if tenant_store.is_admin(headers):
        return True
    # 租户 token
    if tenant_store.resolve_tenant(headers):
        return True
    # 旧单 token 兜底（未迁移场景）
    return bool(_api_token) and hmac.compare_digest(got, _api_token)


def resolve_and_bind(headers):
    """鉴权后把当前线程绑定到对应租户数据目录。
    返回 tenant_id（可能为 None=默认/admin/旧token）。"""
    tid = tenant_store.resolve_tenant(headers)
    _set_tenant(tid)
    return tid


# ── HTTP Handler ────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    server_version = "ChallengeDailyState/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        log.info("%s - %s", self.address_string(), fmt % args)

    # -- helpers --
    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        # 关键：Electron 生产版以 file:// 加载页面，fetch 到本机代理/本服务
        # 属于跨域（Origin: null）。X-API-Token 还会触发 CORS 预检。
        # 若实际响应缺少 ACAO，浏览器会丢弃 200 响应并抛 "Failed to fetch"，
        # 表现为「一直连接后端无响应」。这里作为所有响应的默认头统一注入。
        extra = dict(extra or {})
        extra.setdefault("Access-Control-Allow-Origin", "*")
        # 带 token 的写请求需要暴露自定义头给浏览器读
        extra.setdefault("Access-Control-Expose-Headers", "Content-Type, X-API-Token")
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj, extra=None):
        self._send(code, obj, extra=extra)

    def _no_store(self):
        return {"Cache-Control": "no-store, no-cache, must-revalidate"}

    def _read_body(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if n <= 0 or n > MAX_BODY:
            return None
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    def _auth(self):
        if not token_ok(self.headers):
            self._json(401, {"error": "Unauthorized"})
            return False
        # 鉴权成功后绑定租户数据目录（DB + state 按线程隔离）
        resolve_and_bind(self.headers)
        return True

    def _proxy_body(self):
        """代理请求体：重新读取原始字节（状态接口已消费时才走到这里需谨慎）。"""
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if n <= 0 or n > MAX_BODY:
            return None
        return self.rfile.read(n)

    # -- routes --
    def do_OPTIONS(self):
        self._send(204, b"", extra={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type, X-API-Token",
            "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
            "Access-Control-Max-Age": "86400",
        })

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        q = parse_qs(parsed.query)

        # ── 管理 API（仅 admin token）────────────────────────────────
        if path == "/api/admin/tenants":
            if not tenant_store.is_admin(self.headers):
                return self._json(403, {"error": "admin only"})
            tenants = tenant_store.list_tenants()
            for t in tenants:
                t["stats"] = tenant_store.tenant_stats(t["tenant_id"])
            return self._json(200, {"tenants": tenants})

        # 普通 token 也能查「我是谁」，供客户端显示当前租户
        if path == "/api/tenant/me":
            if tenant_store.is_admin(self.headers):
                return self._json(200, {"role": "admin"})
            tid = tenant_store.resolve_tenant(self.headers)
            if not tid:
                return self._json(401, {"error": "invalid token"})
            return self._json(200, dict(tenant_store.tenant_info(tid) or {}, role="tenant"),
                              extra=self._no_store())

        if path == "/api/admin/whoami":
            if tenant_store.is_admin(self.headers):
                return self._json(200, {"role": "admin"})
            tid = tenant_store.resolve_tenant(self.headers)
            if tid:
                return self._json(200, {"role": "tenant", "tenant_id": tid})
            return self._json(200, {"role": "none"})

        if path == "/admin" or path == "/admin/":
            return self._serve_admin_page()

        if path == "/__shim.js":
            # 多租户：优先用 ?token= 指定租户，否则注入默认/旧 token。
            req_token = (q.get("token") or [""])[0]
            eff_token = req_token or _api_token
            tid = tenant_store.resolve_tenant({"X-API-Token": eff_token}) if req_token else None
            if tid:
                eff_token = tenant_store.tenant_token(tid) or eff_token
            token = eff_token.replace("\\", "\\\\").replace("'", "\\'")
            tenant_js = tid or "default"
            js = """(function () {
  var TOKEN = '%s';
  var TENANT = '%s';
  window.electronAPI = {
    getBackendPort: function () { return Promise.resolve(0); },
    getApiToken: function () { return Promise.resolve(TOKEN); },
    getTenantId: function () { return Promise.resolve(TENANT); },
    getAppVersion: function () { return Promise.resolve('3.4.1-server'); },
    getAutoStart: function () { return Promise.resolve(false); },
    setAutoStart: function () { return Promise.resolve(); },
    showNotification: function (n) { try { new Notification((n && n.title) || 'ChallengeDaily', { body: (n && n.body) || '' }); } catch (e) {} },
    minimize: function () {}, maximize: function () {}, close: function () {},
    onNavigateTo: function () { return function () {}; },
    selectFolder: function () { return Promise.resolve(null); },
    getWindowsLocation: function () { return Promise.resolve(null); },
    windowsHello: function () { return Promise.resolve(false); }
  };
})();""" % (token, tenant_js)
            self._send(200, js, "text/javascript; charset=utf-8",
                       {"Cache-Control": "no-store"})
            return

        if path == "/api/client-state":
            if not self._auth():
                return
            self._json(200, {"state": read_state(), "updated_at": mtime_iso()},
                       extra=self._no_store())
            return

        # 前端启动健康检查：Web 模式下「页面服务器在线」即可进入应用。
        # 若配置了 CD_UPSTREAM（Windows 后端经隧道可达），则转发真实健康状态。
        if path == "/api/health":
            if UPSTREAM:
                return self._proxy("GET", None)
            return self._json(200, {"status": "ok", "mode": "server-only"},
                              extra=self._no_store())

        # /__seed：自动化验证用，服务端写首启标记
        if path == "/__seed":
            if not self._auth():
                return
            with _state_lock:
                st = read_state()
                st["cd_legal_accepted"] = "1"
                st["cd_onboarding_done"] = "1"
                write_state(st)
            target = (q.get("to") or ["/"])[0]
            html = "<!doctype html><meta charset=\"utf-8\"><script>location.replace('#%s');</script>" % target.replace("'", "")
            self._send(200, html, "text/html; charset=utf-8", {"Cache-Control": "no-store"})
            return

        if path == "/api/sync/status":
            if not self._auth():
                return
            st = data_api.status()
            st["retention_days"] = data_api.RETENTION_DAYS
            st["retention_cutoff"] = data_api.cutoff_values()[0]
            st["last_cleanup"] = data_api.get_meta("last_cleanup")
            return self._json(200, st, extra=self._no_store())

        # 采集数据查询：由同步代理推送的服务器 SQLite 提供
        if path in DATA_ROUTES:
            fn, need_auth = DATA_ROUTES[path]
            if need_auth and not self._auth():
                return
            try:
                obj, err = fn(q)
            except Exception as e:
                log.warning("query %s failed: %s", path, e)
                return self._json(500, {"error": "query_failed", "detail": str(e)[:120]})
            if err:
                return self._json(400, {"error": err})
            return self._json(200, obj, extra=self._no_store())
        for prefix, fn in DATA_DYNAMIC_PREFIXES:
            if path.startswith(prefix):
                if not self._auth():
                    return
                rest = path[len(prefix):]
                try:
                    obj, err = fn(rest, q)
                except Exception as e:
                    return self._json(500, {"error": "query_failed", "detail": str(e)[:120]})
                if err:
                    return self._json(400, {"error": err})
                return self._json(200, obj, extra=self._no_store())

        # server-only：SSE 事件流无本机采集后端，返回保持连接的空流，
        # 让前端 EventSource onopen 成功、不再指数退避重连刷 501。
        if path == "/api/events/stream":
            if not self._auth():
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                while True:
                    time.sleep(25)
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            return

        # 可选：把其余 /api/* 转发到 Windows 后端（需 CD_UPSTREAM）
        if path.startswith("/api/") and UPSTREAM:
            self._proxy("GET", None)
            return

        # server-only 模式：对少数未实现接口返回占位，避免满屏报错
        if path in SERVER_ONLY_DEFAULTS:
            return self._json(200, SERVER_ONLY_DEFAULTS[path], extra=self._no_store())

        # 已下线接口：明确返回 410 Gone，与「尚未实现」的 501 区分开
        if path == "/api/stats/distraction-heatmap":
            return self._json(410, {"error": "gone",
                                   "detail": "分心热点图已下线（分类定义失真、无行动闭环），相关组件与数据接口已移除"},
                              extra=self._no_store())

        # 其余业务接口：明确告知「此部署仅提供服务器存储，无采集后端」
        if path.startswith("/api/"):
            return self._json(501, {"error": "server_only_mode",
                                   "detail": "该部署仅提供状态存储与静态页面；采集后端运行在 Windows 本机"},
                              extra=self._no_store())

        # /updates/ : client installer + latest.yml (online update)
        # Must NOT go through _serve_static SPA fallback, otherwise a missing
        # latest.yml returns index.html and electron-updater fails to parse.
        if path.startswith("/updates/"):
            return self._serve_update_file(path[len("/updates/"):])

        self._serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        # ── 租户登录（公开接口：租户 ID + 密码 → 该租户 token）────────
        if path == "/api/auth/login":
            body = self._read_body() or {}
            tid = str(body.get("tenant_id", "")).strip()
            pw = str(body.get("password", ""))
            token, err = tenant_store.login(tid, pw)
            if err:
                log.warning("login failed for %s: %s", tid, err)
                return self._json(401, {"error": err}, extra=self._no_store())
            return self._json(200, {"status": "ok", "token": token, "tenant_id": tid},
                              extra=self._no_store())

        # ── 管理 API（仅 admin token）────────────────────────────────
        if path.startswith("/api/admin/"):
            if not tenant_store.is_admin(self.headers):
                return self._json(403, {"error": "admin only"})
            body = self._read_body() or {}
            if path == "/api/admin/tenants":
                info, err = tenant_store.create_tenant(
                    str(body.get("tenant_id", "")).strip(),
                    str(body.get("name", "")).strip(),
                    body.get("token") or None,
                    body.get("password") or None)
                if err:
                    return self._json(400, {"error": err})
                return self._json(200, {"status": "ok", "tenant": info})
            if path == "/api/admin/tenants/set-password":
                ok = tenant_store.set_password(str(body.get("tenant_id", "")),
                                               str(body.get("password", "")))
                return self._json(200 if ok else 404,
                                  {"status": "ok" if ok else "not found"})
            if path == "/api/admin/tenants/enable":
                ok = tenant_store.set_tenant_enabled(str(body.get("tenant_id", "")), True)
                return self._json(200 if ok else 404, {"status": "ok" if ok else "not found"})
            if path == "/api/admin/tenants/disable":
                ok = tenant_store.set_tenant_enabled(str(body.get("tenant_id", "")), False)
                return self._json(200 if ok else 404, {"status": "ok" if ok else "not found"})
            if path == "/api/admin/tenants/rotate-token":
                tok = tenant_store.rotate_token(str(body.get("tenant_id", "")))
                return self._json(200 if tok else 404,
                                  {"status": "ok", "token": tok} if tok else {"error": "not found"})
            if path == "/api/admin/tenants/delete":
                ok = tenant_store.delete_tenant(str(body.get("tenant_id", "")))
                return self._json(200 if ok else 404, {"status": "ok" if ok else "not found"})
            return self._json(404, {"error": "unknown admin api"})

        # 采集数据同步接收：Windows 同步代理把本机 SQLite 的表行推上来
        if path == "/api/sync/push":
            if not self._auth():
                return
            body = self._read_body()
            if not isinstance(body, dict):
                return self._json(400, {"error": "invalid payload"})
            mode = "replace" if body.get("full") else "upsert"
            stats, err = data_api.apply_push(body, mode=mode)
            if err:
                log.warning("sync push failed: %s", err)
                return self._json(500, {"error": "push_failed", "detail": err})
            log.info("sync push applied: %s", json.dumps(stats, ensure_ascii=False))
            return self._json(200, {"status": "ok", "tables": stats,
                                    "synced_at": data_api.get_meta("last_push")})
        if path == "/api/sync/status":
            if not self._auth():
                return
            st = data_api.status()
            st["retention_days"] = data_api.RETENTION_DAYS
            st["retention_cutoff"] = data_api.cutoff_values()[0]
            st["last_cleanup"] = data_api.get_meta("last_cleanup")
            return self._json(200, st, extra=self._no_store())
        if path == "/api/sync/cleanup":
            if not self._auth():
                return
            cleaned = data_api.cleanup_expired()
            if cleaned:
                data_api.log_cleanup(cleaned)
            return self._json(200, {"status": "ok", "deleted": cleaned,
                                    "retention_days": data_api.RETENTION_DAYS,
                                    "cutoff": data_api.cutoff_values()[0]},
                              extra=self._no_store())
        if path == "/api/client-state/migrate":
            if not self._auth():
                return
            body = self._read_body()
            changes, err = validate_state(body.get("state") if isinstance(body, dict) else None)
            if err:
                return self._json(400, {"error": err})
            with _state_lock:
                current = read_state()
                merged = dict(changes or {})
                merged.update(current)  # 服务端已有值优先
                write_state(merged)
            return self._json(200, {"status": "ok", "migrated": len(changes or {}), "total": len(merged)})
        if path == "/api/client-state/seed":
            if not self._auth():
                return
            with _state_lock:
                st = read_state()
                st["cd_legal_accepted"] = "1"
                st["cd_onboarding_done"] = "1"
                write_state(st)
            return self._json(200, {"status": "ok"})
        if path.startswith("/api/") and UPSTREAM:
            return self._proxy("POST", self._proxy_body())
        # server-only 模式下，常见写操作返回 ok（no-op），避免设置页报错
        if path.startswith("/api/"):
            self._read_body()  # 消费请求体，保持 HTTP/1.1 连接干净
            return self._json(200, {"status": "ok", "mode": "server-only"})
        self._json(404, {"error": "not found"})

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/client-state":
            if not self._auth():
                return
            body = self._read_body()
            state, err = validate_state(body.get("state") if isinstance(body, dict) else None)
            if err:
                return self._json(400, {"error": err})
            with _state_lock:
                write_state(state or {})
            return self._json(200, {"status": "ok", "count": len(state or {})},
                              extra=self._no_store())
        if path.startswith("/api/") and UPSTREAM:
            return self._proxy("PUT", self._proxy_body())
        if path.startswith("/api/"):
            self._read_body()
            return self._json(200, {"status": "ok", "mode": "server-only"})
        self._json(404, {"error": "not found"})

    def do_PATCH(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/client-state":
            if not self._auth():
                return
            body = self._read_body()
            changes, err = validate_state(body.get("state") if isinstance(body, dict) else None,
                                          allow_null=True)
            if err:
                return self._json(400, {"error": err})
            with _state_lock:
                current = read_state()
                for k, v in (changes or {}).items():
                    if v is None:
                        current.pop(k, None)
                    else:
                        current[k] = v
                write_state(current)
            return self._json(200, {"status": "ok", "state": current},
                              extra=self._no_store())
        self._json(404, {"error": "not found"})

    def do_DELETE(self):
        self._json(404, {"error": "not found"})

    # -- static --
    def _serve_update_file(self, rel):
        """Serve installer / latest.yml with single & multi Range support.

        electron-updater differential download sends
        "Range: bytes=a-b,c-d,..." and expects multipart/byteranges.
        """
        import re as _re
        rel = unquote(rel or "")
        target = os.path.normpath(os.path.join(UPDATES_DIR, rel.lstrip("/")))
        if not target.startswith(os.path.abspath(UPDATES_DIR)):
            return self._json(403, {"error": "forbidden"})
        if not rel or not os.path.isfile(target):
            return self._json(404, {"error": "not found", "path": rel})
        ext = os.path.splitext(target)[1].lower()
        ctype = MIME.get(ext) or mimetypes.guess_type(target)[0] or "application/octet-stream"
        size = os.path.getsize(target)

        ranges = []
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes="):
            for spec in rng[6:].split(","):
                spec = spec.strip()
                m = _re.match(r"^(\d*)-(\d*)$", spec)
                if not m:
                    continue
                a, b = m.group(1), m.group(2)
                try:
                    if a == "":
                        if b == "": continue
                        s = max(size - int(b), 0); e = size - 1
                    else:
                        s = int(a)
                        e = int(b) if b else size - 1
                        e = min(e, size - 1)
                    if 0 <= s <= e < size:
                        ranges.append((s, e))
                except ValueError:
                    continue

        common_hdrs = [
            ("Accept-Ranges", "bytes"),
            ("Access-Control-Allow-Origin", "*"),
            ("Cache-Control", "public, max-age=60"),
            ("Access-Control-Expose-Headers", "Content-Type, X-API-Token"),
        ]
        if not ranges:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            for k, v in common_hdrs: self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                with open(target, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk: break
                        try: self.wfile.write(chunk)
                        except (BrokenPipeError, ConnectionResetError): break
            return

        if len(ranges) == 1:
            s, e = ranges[0]
            length = e - s + 1
            self.send_response(206)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            for k, v in common_hdrs: self.send_header(k, v)
            self.send_header("Content-Range", "bytes %d-%d/%d" % (s, e, size))
            self.end_headers()
            if self.command != "HEAD":
                with open(target, "rb") as f:
                    f.seek(s); remain = length
                    while remain > 0:
                        chunk = f.read(min(65536, remain))
                        if not chunk: break
                        try: self.wfile.write(chunk)
                        except (BrokenPipeError, ConnectionResetError): break
                        remain -= len(chunk)
            return

        # multipart/byteranges
        boundary = "CDUPDATEBOUNDARY"
        parts = []
        for (s, e) in ranges:
            head = ("--%s\r\nContent-Type: %s\r\n"
                    "Content-Range: bytes %d-%d/%d\r\n\r\n" % (boundary, ctype, s, e, size))
            parts.append((s, e, head.encode("utf-8")))
        total = sum(len(h) + (e - s + 1) + 2 for (s, e, h) in parts)
        total += len(("--%s--\r\n" % boundary).encode("utf-8"))

        self.send_response(206)
        self.send_header("Content-Type", "multipart/byteranges; boundary=%s" % boundary)
        self.send_header("Content-Length", str(total))
        for k, v in common_hdrs: self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            with open(target, "rb") as f:
                for (s, e, head) in parts:
                    try:
                        self.wfile.write(head)
                        f.seek(s); remain = e - s + 1
                        while remain > 0:
                            chunk = f.read(min(65536, remain))
                            if not chunk: break
                            self.wfile.write(chunk); remain -= len(chunk)
                        self.wfile.write(b"\r\n")
                    except (BrokenPipeError, ConnectionResetError):
                        break
                try:
                    self.wfile.write(("--%s--\r\n" % boundary).encode("utf-8"))
                except (BrokenPipeError, ConnectionResetError):
                    pass

    def _serve_admin_page(self):
        html = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ChallengeDaily 租户管理</title>
<style>
body{font-family:-apple-system,Segoe UI,Microsoft YaHei,sans-serif;margin:0;background:#f5f6fa;color:#222}
.wrap{max-width:960px;margin:40px auto;padding:0 20px}
h1{font-size:22px} .card{background:#fff;border-radius:10px;padding:20px;margin-bottom:18px;box-shadow:0 1px 4px rgba(0,0,0,.06)}
label{display:block;font-size:13px;color:#666;margin:10px 0 4px}
input{padding:8px 10px;border:1px solid #d5d8e0;border-radius:6px;width:100%;box-sizing:border-box;font-size:14px}
button{padding:8px 14px;border:0;border-radius:6px;background:#6c5ce7;color:#fff;cursor:pointer;font-size:14px;margin-top:8px}
button.small{padding:4px 9px;font-size:12px;margin:0 2px}
button.danger{background:#e74c3c} button.warn{background:#f39c12} button.ok{background:#27ae60}
table{width:100%;border-collapse:collapse;margin-top:12px;font-size:14px}
th,td{text-align:left;padding:9px 8px;border-bottom:1px solid #eef0f4}
.code{font-family:Consolas,monospace;font-size:12px;word-break:break-all;background:#f7f8fb;padding:2px 5px;border-radius:4px}
.msg{margin-top:10px;font-size:13px;color:#c0392b;min-height:18px}
.hint{font-size:12px;color:#888;margin-top:6px}
</style></head><body><div class="wrap">
<h1>ChallengeDaily · 租户管理后台</h1>
<div class="card">
  <label>管理员 Token</label>
  <input type="password" id="adminToken" placeholder="输入 .admin_token 中的管理员令牌">
  <button onclick="load()">验证并加载</button>
  <div class="msg" id="m1"></div>
</div>
<div class="card">
  <h2 style="font-size:17px">新建租户</h2>
  <label>租户 ID（字母数字 - _，唯一）</label><input id="newId" placeholder="acme">
  <label>显示名称</label><input id="newName" placeholder="Acme 公司">
  <button onclick="createTenant()">创建租户</button>
  <div class="hint">创建后系统会生成该租户专属 API Token，复制给该租户的同步代理与客户端使用。</div>
</div>
<div class="card">
  <h2 style="font-size:17px">租户列表</h2>
  <table><thead><tr><th>租户 ID</th><th>名称</th><th>状态</th><th>活动数 / DB 大小</th><th>创建时间</th><th>操作</th></tr></thead>
  <tbody id="rows"></tbody></table>
  <div class="msg" id="m2"></div>
</div>
</div>
<script>
function tok(){return document.getElementById('adminToken').value.trim()}
function api(path,body,cb){
  fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-API-Token':tok()},body:body?JSON.stringify(body):undefined})
   .then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j}})})
   .then(function(x){cb(x.j,x.ok)}).catch(function(e){cb({error:String(e)},false)})
}
function load(){
  api('/api/admin/tenants',null,function(j,ok){
    document.getElementById('m1').textContent=ok?'已连接 · 共 '+j.tenants.length+' 个租户':(j.error||'鉴权失败');
    if(!ok)return;
    var h='';
    j.tenants.forEach(function(t){
      var st=t.stats||{};var sz=st.db_size_bytes?((st.db_size_bytes/1024/1024).toFixed(1)+' MB'):'0 MB';
      h+='<tr><td><span class="code">'+t.tenant_id+'</span></td><td>'+t.name+'</td><td>'+(t.enabled?'<span style="color:#27ae60">启用</span>':'<span style="color:#e74c3c">停用</span>')+'</td><td>'+(st.activities||0)+' 条 / '+sz+'</td><td>'+t.created_at+'</td><td>'+
        '<button class="small ok" onclick="act(\''+t.tenant_id+'\',\'rotate-token\')">重置Token</button>'+
        '<button class="small warn" onclick="act(\''+t.tenant_id+'\',\''+(t.enabled?'disable':'enable')+'\')">'+(t.enabled?'停用':'启用')+'</button>'+
        '<button class="small danger" onclick="del(\''+t.tenant_id+'\')">删除</button></td></tr>';
    });
    document.getElementById('rows').innerHTML=h||'<tr><td colspan="6">暂无租户</td></tr>';
  });
}
function createTenant(){
  var id=document.getElementById('newId').value.trim(),name=document.getElementById('newName').value.trim();
  if(!id){document.getElementById('m2').textContent='请填写租户 ID';return}
  api('/api/admin/tenants',{tenant_id:id,name:name},function(j,ok){
    if(ok){document.getElementById('m2').style.color='#27ae60';
      document.getElementById('m2').innerHTML='已创建！该租户 Token：<span class="code">'+j.tenant.token+'</span>';
      document.getElementById('newId').value='';document.getElementById('newName').value='';load();}
    else{document.getElementById('m2').style.color='#c0392b';document.getElementById('m2').textContent=j.error||'创建失败'}
  });
}
function act(id,op){api('/api/admin/tenants/'+op,{tenant_id:id},function(j,ok){
  if(ok&&j.token){alert('新 Token（请妥善保存）：\n'+j.token)} load();});}
function del(id){if(!confirm('确定删除租户 '+id+' 及其全部数据？'))return;
  api('/api/admin/tenants/delete',{tenant_id:id},function(j,ok){load();});}
</script></body></html>"""
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8",
                   {"Cache-Control": "no-store"})

    def _serve_static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not target.startswith(os.path.abspath(STATIC_DIR)):
            return self._json(403, {"error": "forbidden"}, {"Content-Type": "text/plain; charset=utf-8"})
        if not os.path.isfile(target):
            # SPA fallback
            target = os.path.join(STATIC_DIR, "index.html")
        if not os.path.isfile(target):
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        ext = os.path.splitext(target)[1].lower()
        ctype = MIME.get(ext) or mimetypes.guess_type(target)[0] or "application/octet-stream"
        with open(target, "rb") as f:
            data = f.read()
        if ext == ".html":
            data = inject_shim(data.decode("utf-8")).encode("utf-8")
            extra = {"Cache-Control": "no-store"}
        else:
            extra = {"Cache-Control": "public, max-age=3600"}
        self._send(200, data, ctype, extra)

    # -- optional upstream proxy --
    def _proxy(self, method, body):
        url = UPSTREAM + self.path
        headers = {"Content-Type": "application/json"}
        if _api_token:
            headers["X-API-Token"] = _api_token
        req = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=30) as resp:
                data = resp.read()
                self._send(resp.status, data, resp.headers.get("Content-Type", "application/json"),
                           {"Access-Control-Allow-Origin": "*"})
        except HTTPError as e:
            self._send(e.code, e.read(), "application/json", {"Access-Control-Allow-Origin": "*"})
        except (URLError, Exception) as e:
            self._json(502, {"error": "backend_unreachable", "detail": str(e)[:120]},
                       {"Access-Control-Allow-Origin": "*"})


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Python 3.6 没有内置 ThreadingHTTPServer（3.7+ 才有），这里显式组合。
    daemon_threads=True 保证 Ctrl-C / systemd stop 时不会被残留线程卡住。
    request_queue_size 覆盖 TCPServer 默认 5 —— 默认 backlog 太小时，
    多个客户端同时建连（页面 + 轮询 + 同步代理）会被内核直接丢弃 SYN，
    表现为偶发「连接超时」。取 128，与本机 somaxconn=4096 相比留足余量。"""
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


def inject_shim(html):
    tag = '<script src="/__shim.js"></script>'
    if "</head>" in html:
        return html.replace("</head>", tag + "\n  </head>", 1)
    return tag + html


def load_token():
    global _api_token
    tok = os.environ.get("CD_API_TOKEN", "").strip()
    if not tok and os.path.isfile(TOKEN_FILE):
        with io.open(TOKEN_FILE, "r", encoding="utf-8") as f:
            tok = f.read().strip()
    if not tok:
        raise RuntimeError("CD_API_TOKEN is empty and %s not found" % TOKEN_FILE)
    _api_token = tok


def _cleanup_loop():
    """后台定时清理：即使长时间没有新数据推送，也会按保留期删除过期行。"""
    import time as _time
    while True:
        _time.sleep(3600)  # 每小时一次
        try:
            cleaned = data_api.cleanup_expired()
            if cleaned:
                data_api.log_cleanup(cleaned)
        except Exception as e:
            log.warning("定时清理失败: %s", e)


def main():
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR)
    load_token()

    # ── 多租户初始化 ────────────────────────────────────────────────
    # 1) 若注册表为空，把旧单租户数据迁移到 default 租户
    tenant_store._load()   # 触发 _migrate_legacy_locked()
    # 2) 确保管理员令牌文件存在（首次生成一次）
    admin_file = tenant_store.ADMIN_TOKEN_FILE
    if not os.path.isfile(admin_file):
        try:
            import hashlib as _hl
            tok = _hl.sha256(os.urandom(32)).hexdigest()
            with open(admin_file, "w", encoding="utf-8") as f:
                f.write(tok)
            os.chmod(admin_file, 0o600)
            log.info("admin token generated at %s (keep it secret!)", admin_file)
        except Exception as e:
            log.warning("generate admin token failed: %s", e)

    try:
        # 为每个启用的租户初始化独立 DB
        for tid, info in tenant_store._load()["tenants"].items():
            if not info.get("enabled", True):
                continue
            data_api.set_tenant_db(os.path.join(tenant_store.tenant_dir(tid), "synced.db"))
            data_api.init_db()
            cleaned = data_api.cleanup_expired()
            if cleaned:
                data_api.log_cleanup(cleaned)
            log.info("tenant db ready: %s", tid)
        data_api.clear_tenant_db()
        # 兼容：默认 DB 也初始化（无租户/旧路径直连场景）
        data_api.init_db()
        log.info("synced db ready (retention=%d days)", data_api.RETENTION_DAYS)
    except Exception as e:
        log.error("init synced db failed: %s", e)
        raise
    t = threading.Thread(target=_cleanup_loop)
    t.daemon = True
    t.start()
    log.info("ChallengeDaily state server starting on %s:%s", LISTEN_HOST, LISTEN_PORT)
    log.info("static=%s state=%s upstream=%s", STATIC_DIR, STATE_FILE, UPSTREAM or "(none)")
    httpd = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    httpd.daemon_threads = True
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        log.info("stopped")


if __name__ == "__main__":
    main()
