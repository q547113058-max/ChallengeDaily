# -*- coding: utf-8 -*-
"""ChallengeDaily 自动待办候选生产者（常驻，低骚扰，AI 归纳主线）。

从本地后端实时采集的 activities 表，把「最近十几分钟的连续屏幕活动」聚合成
一个工作场景，交给免费文本模型（glm-4-flash）归纳出：

    project  正在执行的项目主体（真实项目名，不用进程名/应用名）
    feature  这个项目正在做的具体功能/模块（文件、模块、功能点）
    action   下一步可直接执行的动作（动词开头）
    basis    可追溯的时间 + 可见线索

推送到线上 todo-sync，触发 App 右下角审批弹窗。

归纳链路（2026-11-17 恢复 AI 主线）：
  1. _llm_induct(digest) 让模型从屏幕证据里自由归纳四段式；
  2. _project_grounded() 强制项目名必须在屏幕证据里真实出现，防止模型把后台
     应用名/无关仓库名当主体（实测会乱猜成 DeepSeek / dsh-enhance）；
  3. 模型失败或字段被过滤为空时，回退到 todo_focus.json 配置模板（保证不编造、
     不断供）。

低骚扰约束：
  * 同一「项目|功能|动作」指纹 20 分钟内只推一次；每轮最多 1 条、每小时 6 条。
  * 文本带时间戳后缀，避开服务端 todo_dismissed 永久忽略规则（TTL=300s）。
"""
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(r"D:\project\daily\ChallengeDaily\data\xiaohei.db")
STATE_PATH = Path(r"D:\project\daily\ChallengeDaily\data\auto_todo_state.sqlite3")
TRACKER_DIR = Path(r"C:\Users\54711\Documents\deepseek-harness\default-workspace")

UPSTREAM = os.environ.get("TODO_SYNC_URL", "http://193.112.246.85:18766").rstrip("/")
TOKEN = os.environ.get("TODO_SYNC_TOKEN", os.environ.get('TODO_SYNC_TOKEN', ''))
INTERVAL_SEC = int(os.environ.get("AUTO_TODO_INTERVAL", "120"))
# 时间窗太长会把不同工作场景（微信讨论 / GitHub 浏览 / 改代码）混在一起，
# 归纳出「project 对但 feature 串台」的怪结果。只看最近 4 分钟，聚焦当前正在做的事。
LOOKBACK_MIN = int(os.environ.get("AUTO_TODO_LOOKBACK_MIN", "6"))
SEARCH_BACK_MIN = int(os.environ.get("AUTO_TODO_SEARCH_BACK_MIN", "25"))
MAX_ROWS = int(os.environ.get("AUTO_TODO_MAX_ROWS", "10"))
DEDUP_MINUTES = float(os.environ.get("AUTO_TODO_DEDUP_MINUTES", "20"))
MAX_PER_HOUR = int(os.environ.get("AUTO_TODO_MAX_PER_HOUR", "6"))
USE_LLM = os.environ.get("AUTO_TODO_USE_LLM", "1") != "0"

# 已知项目词表：帮助模型从窗口标题/文件路径里认出主体，也用于规则兜底匹配。
KNOWN_PROJECTS = [
    "ChallengeDaily", "DeepSeek Harness", "dsh-xdpool", "task-flow",
    "deploy", "daily", "WorkBuddy",
]
# 禁止当作 project 的进程名/应用名（模型常被这些误导）
BAD_PROJECT = re.compile(
    r"^(weixin|微信|explorer|文件资源管理器|chrome|edge|notepad|cmd|powershell|"
    r"windowsterminal|deepseek harness\.exe|challengedaily\.exe|electron|"
    r"未识别|未知|无|n/?a)$", re.I,
)

SYSTEM_PROMPT = """你是「工作待办归纳器」。输入是一个人最近十几分钟的连续屏幕活动记录（含时间、窗口标题、概括、可见细节）。
请从这些真实证据里归纳出：他正在推进哪个项目、这个项目的哪个具体功能、以及下一步最该做的可执行动作。

只输出一个 JSON 对象，不要 Markdown、不要解释：
{"project":"项目名","feature":"具体功能/模块(带项目语境)","action":"动词开头的可执行动作(25字内)","basis":"HH:MM 的可可见线索(35字内)"}

硬性规则：
1. project 必须是输入文本里【真实出现过】的工程/产品/仓库名（逐字可查到），禁止凭空猜、禁止填后台应用名或通讯工具名。
   - 允许：窗口标题里的仓库名（如 Minglink/dsh-infinite-gen-5 → dsh-infinite-gen-5）、文件路径里的目录名、细节里反复出现的代码工程名、讨论明确指向的产品。
   - 禁止：微信/Weixin、DeepSeek Harness（这只是 AI 客户端工具）、explorer、Chrome、文件资源管理器、「未识别项目」「未知」。
   - 例：标题「待办未弹出问题 — DeepSeek Harness」且细节提到 app.asar / bridge.py / TodoDock → 真正在改的工程是 ChallengeDaily，project 应填 ChallengeDaily（前提是这些词出现在输入里）。
   - 若通篇找不到任何可查的工程名，project 填「主体待确认」。
2. feature 必须是输入里能指认的具体对象：文件名、模块名、页面名或明确功能点，并带上项目语境。
   例：ChallengeDaily 的 routes/bridge.py SSE 代理、app.asar 重打包、TodoDock 待办看板、dsh-xdpool 插件升级。
   禁止「查看代码」「调试问题」「分析内容」「工作讨论」「当前改动」这类空话。
3. action 必须是能直接执行、有交付物的动作（修复/验证/补全/重启/比对/回退/提交/部署/调整/优化…），动词开头、点明作用对象。
   禁止「查看/分析/继续/了解/讨论/研究/使用/学习」以及「验证当前改动是否生效」这类占位话。
4. basis 必须是「HH:MM + 输入里真实可见的线索」组合，例如「10:45 窗口标题显示待办未弹出问题」「10:31 编辑 app.asar 重打包脚本」。禁止只写时间或空泛的「聊天记录显示讨论内容」。
5. 严禁编造输入里完全没出现的名词。若证据不足，宁可 project 填「主体待确认」、feature 用最贴近的可见对象。
6. 若主要是聊天/沟通：project 取讨论围绕的工程/产品（必须在文本里出现），feature 取讨论的具体问题点，action 取针对该问题的下一步处置。不要把「与同事讨论」本身写成待办。"""


def _log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def _state():
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(STATE_PATH)
    c.execute("CREATE TABLE IF NOT EXISTS pushed (fp TEXT PRIMARY KEY, todo TEXT, pushed_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS hour (ts TEXT PRIMARY KEY)")
    c.commit()
    return c


def _recent_count(c):
    cutoff = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    return c.execute("SELECT COUNT(*) FROM hour WHERE ts>=?", (cutoff,)).fetchone()[0]


def _already(c, fp):
    cutoff = (datetime.now() - timedelta(minutes=DEDUP_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    return c.execute("SELECT 1 FROM pushed WHERE fp=? AND pushed_at>=?", (fp, cutoff)).fetchone() is not None


def _mark(c, fp, todo):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT OR REPLACE INTO pushed(fp,todo,pushed_at) VALUES(?,?,?)", (fp, todo, now))
    c.execute("INSERT OR REPLACE INTO hour(ts) VALUES(?)", (now,))
    c.commit()


def _push(items):
    data = json.dumps({"todos": items}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        UPSTREAM + "/api/todos", data=data, method="POST",
        headers={"X-Todo-Token": TOKEN, "Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _recent_rows():
    """取最近一段有「功能线索」的连续记录。

    优先看 LOOKBACK_MIN 分钟；若这一窗口恰好在浏览无细节的页面（如 GitHub
    仓库页、ai_detail 写「未显示代码」），就回溯到 SEARCH_BACK_MIN 分钟里
    最近的有料记录，避免归纳出「功能待确认」这种对用户没用的空话。
    """
    if not DB_PATH.exists():
        return []
    try:
        con = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True, timeout=5)
    except Exception as e:
        _log(f"db open failed: {e}")
        return []
    cutoff = (datetime.now() - timedelta(minutes=SEARCH_BACK_MIN)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        rows = con.execute(
            "SELECT timestamp, app_name, window_title, summary, ai_detail FROM activities "
            "WHERE timestamp>=? ORDER BY id DESC LIMIT 120", (cutoff,)
        ).fetchall()
    except Exception as e:
        _log(f"query failed: {e}")
        rows = []
    finally:
        con.close()

    rows = list(reversed(rows))
    near_cut = (datetime.now() - timedelta(minutes=LOOKBACK_MIN)).strftime("%Y-%m-%d %H:%M:%S")
    near = [r for r in rows if (r[0] or "") >= near_cut]
    useful_near = [r for r in near if _useful(r)]
    if useful_near:
        return useful_near[-MAX_ROWS:]
    useful_all = [r for r in rows if _useful(r)]
    if useful_all:
        # 取最近一段连续有料记录（最多 MAX_ROWS 条）
        return useful_all[-MAX_ROWS:]
    return near[-MAX_ROWS:] if near else []


def _digest(rows):
    lines = []
    for ts, app, title, summary, detail in rows:
        hhmm = (ts or "")[11:16]
        lines.append(
            f"{hhmm} | 窗口:{(title or '')[:70]} | 概括:{(summary or '')[:60]} | "
            f"细节:{(detail or '')[:200]}"
        )
    return "\n".join(lines)


# ai_detail 里有具体功能线索才算「有料」；纯浏览页面/无细节的记录跳过
DETAIL_CLUE = re.compile(
    r"asar|bridge|producer|待办|弹窗|路由|SSE|插件|重打包|代码|文件|报错|"
    r"配置|部署|日志|同步|脚本|函数|接口|模块|参数|调试|修复|验证|讨论|"
    r"识别|模型|图片|传输|工作区|设置|界面|启动|命令", re.I,
)


def _useful(row):
    """这条记录是否含可归纳的功能线索。"""
    blob = (row[2] or "") + " " + (row[3] or "") + " " + (row[4] or "")
    if re.search(r"未显示代码|无法判断具体工作|显示内容不清晰", blob):
        return False
    return bool(DETAIL_CLUE.search(blob))


# 从窗口标题里确定性抽取项目主体（优先于模型猜测）
# GitHub: "owner/repo: ..." / "owner/repo - ..."
REPO_RE = re.compile(r"\b([A-Za-z0-9][A-Za-z0-9_.\-]{2,40})/([A-Za-z0-9][A-Za-z0-9_.\-]{2,40})\b")
# 「XXX - 文件资源管理器」「XXX — DeepSeek Harness」「XXX: ... - Google Chrome」
TITLE_PROJECT_RE = re.compile(r"^\s*([^\s:：—·|\-]{2,30})[\s:：—·|\-]")
# 应用/工具后缀：这些词不是项目
TOOL_SUFFIX = re.compile(
    r"(Google Chrome|文件资源管理器|Windows|DeepSeek Harness|Visual Studio Code|"
    r"Notepad|微信|Weixin|Explorer|Chrome|Edge|Terminal)$", re.I,
)
# 工具/平台名：绝不能被当成项目主体（用户反馈「DeepSeek 不是项目」）
TOOL_WORDS = re.compile(
    r"^(DeepSeek(\s*Harness)?|Google\s*Chrome|Chrome|Edge|微信|Weixin|"
    r"文件资源管理器|Explorer|Notepad|Windows|Terminal|PowerShell|"
    r"Visual Studio Code|VS\s*Code|Cursor|WorkBuddy|GitHub)$", re.I,
)


def _extract_project(rows):
    """只从屏幕里真实可见的标题/路径抓项目；抓不到返回空串。"""
    titles = [(r[2] or "").strip() for r in rows]  # window_title
    # 1) GitHub owner/repo
    for t in titles:
        m = REPO_RE.search(t)
        if m:
            repo = m.group(2)
            if repo.lower() not in ("github.com", "www", "http", "https"):
                return repo
    # 2) 标题前缀里的工程名（去掉应用后缀后）
    for t in titles:
        m = TITLE_PROJECT_RE.match(t)
        if not m:
            continue
        p = m.group(1).strip()
        # 先剥掉「使用 XXX 配置…」这类动词前缀，再去工具后缀
        p = re.sub(r"^(使用|查看|浏览|打开|分析|正在|在)\s*", "", p).strip()
        p = TOOL_SUFFIX.sub("", p).strip(" -—:·|")
        # 标题里只要嵌着工具/平台名，整串都不是项目（例「DeepSeek Harness 配置插件」）
        if re.search(r"DeepSeek\s*Harness|Google\s*Chrome|Visual Studio|VS\s*Code|"
                     r"WorkBuddy|文件资源管理器|PowerShell|Windows Terminal", p, re.I):
            continue
        if p and (TOOL_WORDS.match(p) or re.match(r"^(与|和|当前)", p)):
            continue
        # 纯域名 / 中文描述性短语不是项目名
        if re.match(r"^[a-z0-9.\-]+\.(com|cn|org|net|io)$", p, re.I):
            continue
        if re.search(r"问题|弹窗|报错|内容|记录|状态|分析|配置$", p) and len(p) > 4:
            continue
        if p and not BAD_PROJECT.match(p) and 2 <= len(p) <= 30 and not p.endswith(".exe"):
            return p
    # 3) 路径里的目录名 / 具体文件名所属工程
    blob = " ".join(titles) + " " + " ".join((r[4] or "") for r in rows)
    m = re.search(r"(?:project|repo|workspace)[\\/]([A-Za-z0-9_\-]{3,30})[\\/]", blob, re.I)
    if m:
        return m.group(1)
    for name in KNOWN_PROJECTS:
        # 词表只用来「确认屏幕上确实出现了该名字」，不用来凭空补
        if re.search(r"\b" + re.escape(name) + r"\b", blob, re.I):
            return name
    return ""


def _clean_project(p):
    p = (p or "").strip().strip('"').strip()
    if not p or BAD_PROJECT.match(p) or len(p) > 30:
        return "主体待确认"
    p = re.sub(r"\.exe$", "", p, flags=re.I).strip()
    return p or "主体待确认"


# 明显是页面标题/宣传语，不是功能点（例：GitHub 仓库页的「求 Star 收藏」）
FEATURE_NOISE = re.compile(
    r"求\s*Star|收藏|欢迎大家|最强|无限五代|GitHub|github\.com|"
    r"^-?\s*Google Chrome|页面标题|未显示代码|无法判断", re.I,
)


def _clean_feature(f):
    f = re.sub(r"\s+", " ", (f or "").strip())[:40]
    if not f or re.match(r"^(查看|分析|调试|讨论|了解|继续|无|未知)", f):
        return ""
    if FEATURE_NOISE.search(f):
        return ""
    return f


def _clean_action(a):
    a = re.sub(r"\s+", " ", (a or "").strip())[:30]
    if not a or re.match(r"^(查看|分析|讨论|了解|继续|研究|使用|学习|配置)(?:$|\s|[^的])", a):
        return ""
    return a


def _llm_induct(digest):
    """调用免费文本模型做场景归纳。失败时抛异常由调用方兜底。"""
    sys.path.insert(0, str(TRACKER_DIR))
    import screen_activity_tracker as T  # noqa: E402
    key = T.load_key("")
    if not key:
        raise RuntimeError("no api key")
    raw = T._post_text(
        key,
        {
            "model": T.TEXT_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": digest},
            ],
            "max_tokens": 400, "temperature": 0.1, "stream": False,
        },
        T.DEFAULT_BASE_URL, 90,
    )
    d = T._extract_json(raw)
    if not isinstance(d, dict):
        raise RuntimeError("bad json")
    return d


def _rule_induct(rows, digest):
    """纯规则兜底：从窗口标题/细节里找项目与功能，绝不调用模型。"""
    blob = digest
    project = ""
    for name in KNOWN_PROJECTS:
        if name.lower() in blob.lower():
            project = name
            break
    if not project:
        # 路径里的仓库名，如 ChallengeDaily/routes/xxx 或 D:\project\daily\...
        m = re.search(r"(?:project[\\/]|repo[\\/])([A-Za-z0-9_\-]+)", blob)
        project = m.group(1) if m else "ChallengeDaily"
    # 功能：优先抓文件名/模块名
    feat = ""
    m = re.search(r"([A-Za-z0-9_\-]+\.(?:py|ts|tsx|js|cjs|md|json|bat|cmd|vbs))", blob)
    if m:
        feat = m.group(1)
    if not feat:
        m = re.search(r"(待办|弹窗|桥接|同步|部署|插件|日报|采集|审批|重打包|路由|SSE)", blob)
        feat = (m.group(1) + " 功能") if m else "当前改动"
    action = "验证" if re.search(r"验证|测试|检查", blob) else "修复"
    return {"project": project, "feature": feat, "action": action + feat,
            "basis": (rows[-1][0] or "")[11:16] + " 规则兜底"}


FOCUS_PATH = Path(r"D:\project\daily\ChallengeDaily\todo_focus.json")

# 固定动作模板：轮换使用，全部是可直接执行、有交付物的动词短语。
ACTION_TEMPLATES = [
    "验证弹窗触发与审批流程是否走通",
    "检查重启后是否仍然生效",
    "核对日志与状态输出",
    "确认去重与限流表现",
    "回退并复测异常路径",
]


def _load_focus():
    try:
        return json.loads(FOCUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"active_project": "ChallengeDaily", "focus": "自动待办", "features": ["自动待办审批弹窗"]}


def _pick_feature(focus, digest, rows):
    """从配置的功能词表里，挑屏幕上当前有线索的那一项。"""
    feats = focus.get("features") or []
    blob = digest
    scored = []
    for f in feats:
        # 用功能名里的关键词做宽松匹配（中文按 2 字片段）
        keys = [k for k in re.split(r"[\s/·、，,]+", f) if len(k) >= 2]
        score = sum(1 for k in keys if k.lower() in blob.lower())
        scored.append((score, f))
    scored.sort(key=lambda x: -x[0])
    if scored and scored[0][0] > 0:
        return scored[0][1]
    return feats[0] if feats else "自动待办审批弹窗"


def _grounded_project(raw, digest, rows):
    """校验模型给的 project 必须在屏幕证据里真实出现；否则回退。

    这是防止「模型乱猜项目」的关键闸门：之前放开让模型自由猜，会在 DeepSeek、
    dsh-enhance 等无关名字之间乱跳。现在要求 project 能在 digest（窗口标题 +
    概括 + 细节）里逐字找到，找不到就不用它。
    """
    p = _clean_project(raw)
    if p == "主体待确认":
        return p
    # 关键：工具/平台名即使在屏幕里出现，也绝不能当项目主体。
    # 屏幕标题常是「待办未弹出问题 — DeepSeek Harness」，模型容易把后者当项目。
    if TOOL_WORDS.match(p) or re.search(r"DeepSeek\s*Harness", p, re.I):
        _log(f"tool name rejected as project: {p!r}")
        return "主体待确认"
    blob = digest
    # 直接在证据里找项目名（大小写不敏感）
    if re.search(r"\b" + re.escape(p) + r"\b", blob, re.I):
        return p
    # owner/repo 形式：模型可能只取了 repo 名，而证据里是 owner/repo
    for t in [(r[2] or "") for r in rows]:
        if re.search(r"/" + re.escape(p) + r"\b", t, re.I):
            return p
    _log(f"ungrounded project dropped: {p!r} not found in screen evidence")
    return "主体待确认"


def _build_item(rows, digest, c):
    """AI 归纳主线：模型从屏幕证据产出四段式，项目名经证据校验后落地。

    模型不可用时回退到 todo_focus.json 配置模板（保底，不编造、不断供）。
    """
    d = None
    if USE_LLM:
        try:
            d = _llm_induct(digest)
            _log("induct: llm ok")
        except Exception as e:
            _log(f"induct: llm failed ({str(e)[:60]}), fallback to config")
    if not isinstance(d, dict) or not d:
        d = None

    if d:
        project = _grounded_project(d.get("project"), digest, rows)
        feature = _clean_feature(d.get("feature"))
        action = _clean_action(d.get("action"))
        basis = re.sub(r"\s+", " ", str(d.get("basis") or "")).strip()[:60]
    else:
        project, feature, action, basis = "", "", "", ""

    # 兜底：任何关键字段缺失 → 用配置模板补齐（保证有主体、有功能、有动作）
    focus = _load_focus()
    if not feature:
        feature = _pick_feature(focus, digest, rows)
    if not action:
        try:
            n = c.execute("SELECT COUNT(*) FROM pushed").fetchone()[0]
        except Exception:
            n = 0
        action = ACTION_TEMPLATES[n % len(ACTION_TEMPLATES)]
    if project == "主体待确认" or not project:
        # 模型没给可信项目 → 用配置的项目，但标注这是兜底主体
        project = _clean_project(focus.get("active_project"))
    hhmm = (rows[-1][0] or "")[11:16] or datetime.now().strftime("%H:%M")
    if not basis or len(basis) < 6:
        basis = f"{hhmm} 屏幕活动：{feature[:24]}"

    # 正文 = 「动作 · <项目>的<功能>」
    todo = f"{action} · {project} 的 {feature}"
    fp = hashlib.md5((project + "|" + feature + "|" + action).encode("utf-8")).hexdigest()
    _log(f"induct: {project} / {feature} / {action}")
    return fp, project, todo, basis, hhmm


def run_once():
    c = _state()
    left = min(1, MAX_PER_HOUR - _recent_count(c))
    if left <= 0:
        _log("hourly cap reached, skip")
        return
    rows = _recent_rows()
    if not rows:
        _log("no recent activity")
        return
    digest = _digest(rows)
    fp, project, todo, basis, hhmm = _build_item(rows, digest, c)
    if _already(c, fp):
        _log(f"dedup skip: {project} | {todo}")
        return
    stamp = datetime.now().strftime("%m%d %H:%M")
    item = {
        "project": project,
        "todo": f"{todo}（{stamp}）"[:60],
        "basis": basis,
        "confidence": "high",
        "time": hhmm,
    }
    try:
        res = _push([item])
        _log(f"pushed [{project}] {todo} -> {res.get('stat')} rev={res.get('rev')}")
        _mark(c, fp, item["todo"])
    except Exception as e:
        _log(f"push failed: {e}")


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_once()
    else:
        _log(f"producer start: interval={INTERVAL_SEC}s lookback={LOOKBACK_MIN}min cap={MAX_PER_HOUR}/h")
        while True:
            try:
                run_once()
            except Exception as e:
                _log(f"loop error: {e}")
            time.sleep(INTERVAL_SEC)
