"""探测 DSH 当前工作区（供采集时标注活动所属项目边界）。

原理：DSH 把每个会话投影到
  C:\\Users\\54711\\.dsh\\storages\\session_projcache\\sessions\\session-*.json
每个投影含 record.cwd；投影的 mtime 随会话活动更新。
"最近被更新的投影的 cwd" ≈ 当前工作区。

时效过滤：若最新投影超过 MAX_AGE_SEC 未更新，认为工作区不可靠（可能后台旧会话），
返回空串，让下游回退到窗口标题推断。

工作区标题来自 .dsh/storages/workspace.json（path -> title）。
"""
import glob
import json
import logging
import os
import re
import time

logger = logging.getLogger(__name__)

_SESSION_GLOB = os.path.join(
    os.path.expanduser("~"), ".dsh", "storages", "session_projcache", "sessions", "session-*.json"
)
_WORKSPACE_JSON = os.path.join(os.path.expanduser("~"), ".dsh", "storages", "workspace.json")
_MAX_AGE_SEC = 5 * 60  # 5 分钟内更新过才认
_CWD_RE = re.compile(r'"cwd"\s*:\s*"((?:[^"\\]|\\.)*)"')

_cache = {"ts": 0.0, "cwd": "", "title": ""}
_CACHE_TTL = 20  # 20 秒缓存，避免每条活动都扫一遍文件


def _load_titles() -> dict:
    """workspace.json 里 path -> title 映射。"""
    try:
        with open(_WORKSPACE_JSON, "r", encoding="utf-8") as f:
            d = json.load(f)
        tables = d.get("tables", {}).get("workspaces", {})
        return {w.get("path", ""): w.get("title", "") for w in tables.values() if w.get("path")}
    except Exception:
        return {}


def detect_workspace(force: bool = False) -> tuple:
    """返回 (cwd, title)。无法可靠判定时返回 ("", "")。

    force=True 跳过缓存（测试用）。
    """
    now = time.time()
    if not force and now - _cache["ts"] < _CACHE_TTL:
        return _cache["cwd"], _cache["title"]

    result = ("", "")
    try:
        files = glob.glob(_SESSION_GLOB)
        latest = None
        latest_mt = 0.0
        latest_cwd = ""
        for f in files:
            mt = os.path.getmtime(f)
            if mt <= latest_mt:
                continue
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    txt = fh.read()
            except Exception:
                continue
            m = _CWD_RE.search(txt)
            if not m:
                continue
            try:
                cwd = json.loads('"' + m.group(1) + '"')  # 还原转义
            except Exception:
                cwd = m.group(1).replace("\\\\", "\\")
            latest_mt, latest_cwd, latest = mt, cwd, f

        if latest_cwd and (now - latest_mt) <= _MAX_AGE_SEC:
            titles = _load_titles()
            # 精确匹配优先；否则用目录名
            title = titles.get(latest_cwd, "")
            if not title:
                title = os.path.basename(latest_cwd.rstrip("\\/")) or ""
            result = (latest_cwd, title)
    except Exception as e:
        logger.debug(f"DSH workspace 探测失败: {e}")

    _cache.update({"ts": now, "cwd": result[0], "title": result[1]})
    return result


def project_name_from_workspace() -> str:
    """给 experience_pipeline 用：优先返回可读的工作区标题，否则空串。"""
    _, title = detect_workspace()
    return title or ""


if __name__ == "__main__":
    cwd, title = detect_workspace(force=True)
    print("cwd  =", cwd)
    print("title=", title)
