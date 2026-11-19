"""任务经历档案流水线：从采集活动聚合出项目/任务经历/技能/协作/习惯。

设计目标：
- 单一事实源：让日报/首页洞察/深度画像/AI 自我认知/待办建议读到同一份档案，措辞互证
- 增量控成本：按 activity id 水位推进，session 批处理，规则前置，AI 只做语义归纳
- 隐私优先：协作对象只存称呼/角色，不存聊天原文

触发：由 experience_scheduler 定时调用 run_once()；手动 /api/experience/rebuild。
"""
import json
import logging
import re
import hashlib
from collections import Counter
from datetime import datetime

logger = logging.getLogger(__name__)

# 复用 auto_todo_producer 已验证的「证据校验」项目抽取（防把工具名当项目）
try:
    from auto_todo_producer import _extract_project, KNOWN_PROJECTS
except Exception:
    _extract_project = None
    KNOWN_PROJECTS = ("ChallengeDaily", "task-flow", "xdpool")

# 无 AI 时的技能映射：分类 -> 技能维度（与 report._compute_skill_radar 一致）
_CATEGORY_SKILL = {
    "开发": "编码开发", "测试": "测试验证", "设计": "设计创作", "文档": "文档写作",
    "数据分析": "数据分析", "运维": "运维部署", "学习": "学习研究", "管理": "项目管理",
    "产品": "产品规划", "沟通": "协作沟通", "会议": "协作沟通", "生活": "",
}
_TOOL_WORDS = re.compile(
    r"^(DeepSeek(\s*Harness)?|Google\s*Chrome|Chrome|Edge|微信|Weixin|"
    r"文件资源管理器|Explorer|Notepad|Windows|Terminal|PowerShell|WorkBuddy|GitHub)$", re.I,
)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _jsond(s, default):
    try:
        return json.loads(s) if s else default
    except Exception:
        return default


# ── 水位/状态 ───────────────────────────────────────────────
def get_state(key: str, default=None):
    from db import get_conn
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM exp_extraction_state WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(key: str, value) -> None:
    from db import get_conn
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO exp_extraction_state (key,value,updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, str(value), _now()),
        )
        conn.commit()


# ── 增量取数 + 会话分簇 ─────────────────────────────────────
def collect_pending(min_id: int = 0, limit: int = 800) -> list:
    from db import get_conn
    with get_conn() as conn:
        if limit <= 0:  # 全量回扫（force 模式）
            rows = conn.execute(
                "SELECT a.* FROM activities a "
                "LEFT JOIN exp_activity_link l ON l.activity_id=a.id "
                "WHERE a.id>? AND a.ai_detail IS NOT NULL AND a.ai_detail<>'' "
                "AND l.activity_id IS NULL ORDER BY a.id ASC",
                (min_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT a.* FROM activities a "
                "LEFT JOIN exp_activity_link l ON l.activity_id=a.id "
                "WHERE a.id>? AND a.ai_detail IS NOT NULL AND a.ai_detail<>'' "
                "AND l.activity_id IS NULL ORDER BY a.id ASC LIMIT ?",
                (min_id, limit),
            ).fetchall()
    return [dict(r) for r in rows]


def _task_key(r: dict) -> str:
    """任务标识：窗口标题去掉工具后缀后的核心。用于同工作区内拆分子任务。"""
    title = (r.get("window_title") or "").strip()
    core = _TOOL_PREFIX_RE.sub("", title)
    core = re.sub(r"\s*[-—:：|]\s*(DeepSeek Harness|Google Chrome|微信|WorkBuddy).*$", "", core, flags=re.I)
    core = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", core)
    return core[:20]


def build_sessions(rows: list, gap_min: int = 20) -> list:
    """同项目 + 同任务 + 时间间隔内的记录聚成一个 session。

    关键：同一工作区（项目）内，任务标题变化会切分成不同 session，
    保证「一个会话内开发多个功能」不会被合并成一条经历。
    """
    sessions, cur, last_ts, last_proj, last_task = [], [], None, None, None
    for r in rows:
        ts = r.get("timestamp", "")
        try:
            t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except Exception:
            t = None
        proj = _project_of(r)
        task = _task_key(r)
        new = (
            not cur or last_ts is None or t is None
            or (t - last_ts).total_seconds() > gap_min * 60
            or (proj and last_proj and proj != last_proj)
            # 同一项目内任务切换 → 拆成不同经历（任务标识都非空且不同才切）
            or (task and last_task and task != last_task)
        )
        if new and cur:
            sessions.append(cur)
            cur = []
        cur.append(r)
        last_ts, last_proj, last_task = t, proj, task
        last_ts, last_proj = t, proj
    if cur:
        sessions.append(cur)
    return sessions


# 动词开头/动作短语不是项目名（"安装更新""改为服务器存储数据""分析异常"）
_ACTION_PREFIX_RE = re.compile(
    r"^(安装|更新|改为|设置|配置|查看|浏览|打开|分析|编辑|删除|下载|上传|"
    r"创建|新建|修复|解决|正在|使用|进入|返回|切换到|调整|整理)\b", re.I,
)
# 工具名/系统词/泛词：一律不能当项目（即便 KNOWN_PROJECTS 兜底命中）
_NOT_PROJECT_RE = re.compile(
    r"^(DeepSeek(\s*Harness)?|WorkBuddy|Google\s*Chrome|Chrome|Edge|微信|Weixin|"
    r"文件(资源管理器)?|管理员|Window(s)?|Terminal|PowerShell|Explorer|Notepad|"
    r"Visual Studio Code|VS\s*Code|Cursor|GitHub|AI|Electron|腾讯云|"
    r"设置|更新|安装|下载|控制台|任务管理器|计算器|Photos|照片)$", re.I,
)


def _project_of(r: dict) -> str:
    """从单条记录提取项目名：优先采集时记录的 DSH 工作区（项目边界），
    其次 GitHub repo / 明确工程名，宁缺勿滥。

    注意：工作区是「项目边界」，不是「任务」——同一工作区内的多个功能
    由 exp_task_episode 的 fingerprint(project|title) 拆成多条经历，不会全合并。
    """
    title = r.get("window_title") or ""
    detail = r.get("ai_detail") or ""
    # 0) 采集时落库的 DSH 工作区 —— 最权威的项目边界
    ws = (r.get("workspace") or "").strip()
    if ws:
        return ws
    # 1) 窗口标题里的 GitHub owner/repo —— 次可靠
    m = re.search(r"\b([A-Za-z0-9][\w.\-]{2,40})/([A-Za-z0-9][\w.\-]{2,40})\b", title)
    if m and m.group(2).lower() not in ("github.com", "www", "http", "https"):
        return m.group(2)
    # 2) 确定性规则抽取，但严格排除工具名/动作短语/泛词
    if _extract_project:
        try:
            p = _extract_project([(None, None, title, None, detail)])
            if (p and p != "主体待确认" and not _NOT_PROJECT_RE.match(p.strip())
                    and not _TOOL_WORDS.match(p) and not _ACTION_PREFIX_RE.match(p)
                    and not _NOISE_RE.search(p) and not re.match(r"^[（(\d]", p)
                    # 动作短语（顿号/动词结尾/长度过长的中文描述）不是项目
                    and not re.search(r"[、，,]", p)
                    and not re.search(r"(更新|维护|设置|运行|配置|安装|打包|存储数据)$", p)
                    and not (re.search(r"[\u4e00-\u9fa5]{6,}", p) and len(p) > 12)
                    and 2 <= len(p) <= 30):
                return p
        except Exception:
            pass
    # 3) 已知工程名兜底——仅当它出现在窗口标题里（不是 ai_detail 的泛泛提及）
    for name in KNOWN_PROJECTS:
        if not _NOT_PROJECT_RE.match(name) and re.search(r"\b" + re.escape(name) + r"\b", title, re.I):
            return name
    return "主体待确认"


# 噪声文本：AI 报错/占位/系统提示，不能当经历标题或证据
_NOISE_RE = re.compile(
    r"AI\s*未配置|请在设置中配置|Error\s*code|429|1305|max_tokens|"
    r"请求失败|分析异常|配置 API|API\s*Key|too many requests|rate limit", re.I,
)


def _clean_ai_detail(text: str, limit: int = 160) -> str:
    """清洗 AI 描述：去掉报错占位、截断。"""
    t = (text or "").strip()
    if not t or _NOISE_RE.search(t[:60]):
        return ""
    return t[:limit]


def build_digest(session: list, existing_titles: list, number: bool = False):
    """构造证据摘要。number=True 时给每行加 [编号] 并返回 (文本, 编号->活动 映射)。"""
    lines = []
    idx_map = {}
    idx = 0
    for r in session:
        hhmm = (r.get("timestamp") or "")[11:16]
        detail = _clean_ai_detail(r.get("ai_detail"))
        summary = (r.get("summary") or "").strip()
        title = (r.get("window_title") or "").strip()
        if not detail and not summary:
            continue
        prefix = f"[{idx}] " if number else "- "
        lines.append(f"{prefix}{hhmm} [{r.get('category','')}] {title[:40]} | {summary[:40]} | {detail[:120]}")
        idx_map[idx] = r
        idx += 1
        if len(lines) >= 16:  # 多任务拆分需要更多证据行
            break
    head = ""
    if existing_titles:
        head = "已有经历（延续则选其一，勿另起炉灶）：" + "、".join(existing_titles[:15]) + "\n"
    text = head + "\n".join(lines)
    return (text, idx_map) if number else text


# ── AI 提炼（可选，失败回退规则）─────────────────────────────
_EXPERIENCE_SCHEMA = """只输出一个 JSON 对象，不要 Markdown 或解释：
{
  "match_existing": "延续已有经历的标题；新经历填空字符串",
  "title": "任务/功能点名称，带项目语境，20字内名词短语",
  "summary": "这段经历做了什么，2-3句，只用证据里的事实",
  "skills": ["证据里能指认的技能"],
  "collaborators": ["称呼或角色，如 产品同事/文件传输助手"],
  "status": "open|done",
  "evidence": ["HH:MM 证据线索，最多3条"]
}
硬规则：1) 只用证据事实，不编造；2) 证据不足时 skills/collaborators 留空、status 填 open；
3) 协作对象只写称呼/角色，禁止聊天原文/手机号；4) 延续已有经历时 title 保持一致。"""


def _call_ai_extract(prompt: str, max_tokens: int = 600):
    """统一的 AI 调用封装（预算/熔断/解析），返回解析后的 dict/list 或 None。"""
    try:
        import config
        from ai_client import (
            _get_client, _cb_check, _rate_limit_check, _parse_json_response,
            _cb_record_success, _cb_record_failure, _reset_client,
        )
        if not config.AI_API_KEY or not _cb_check() or not _rate_limit_check("text"):
            return None
        today = datetime.now().strftime("%Y-%m-%d")
        cnt = int(get_state(f"daily_call_count:{today}", "0") or 0)
        if cnt >= 120:
            return None
        resp = _get_client().chat.completions.create(
            model=config.AI_TEXT_MODEL,
            messages=[
                {"role": "system", "content": "你是工作经历档案整理器，只输出合法 JSON，绝不编造数据。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens, temperature=0.2,
            extra_body={"thinking": {"type": "disabled"}},
        )
        text = (resp.choices[0].message.content or "").strip()
        _cb_record_success()
        set_state(f"daily_call_count:{today}", cnt + 1)
        return _parse_json_response(text)
    except Exception as e:
        logger.debug(f"经历档案 AI 提炼失败: {e}")
        try:
            from ai_client import _cb_record_failure, _reset_client
            _cb_record_failure()
            _reset_client()
        except Exception:
            pass
        return None


def extract_with_ai(digest: str) -> dict | None:
    """单任务语义归纳；失败返回 None。"""
    d = _call_ai_extract(f"屏幕活动证据：\n{digest}\n\n{_EXPERIENCE_SCHEMA}")
    return d if isinstance(d, dict) and d else None


# 多任务拆分 schema：一个证据段里可能含多个不同任务
_MULTI_TASK_SCHEMA = """这段证据可能包含多个不同的任务/功能。请把它们拆开，输出 JSON：
{"tasks": [
  {"title":"任务名(20字内名词短语)","summary":"做了什么,2-3句只用证据事实",
   "line_refs":[引用哪些证据行的编号,如 [0,1,4]],
   "skills":["证据里能指认的技能"],"status":"open|done"}
]}
硬规则：
1) 把讨论同一件事的证据行归到同一任务；讨论不同功能的才拆成不同任务。
2) 标题相近、都是"查看/了解同一主题"的行要合并成一个任务，不要拆成多个近义任务。
   一段证据通常只有 2-4 个真正不同的任务，不要拆出 7 个以上的碎任务。
3) line_refs 必须是证据里真实出现的行编号；每行只能属于一个任务，不要重复分配。
4) 证据不足、无法判断具体任务的行（如"无法判断工作内容""429报错"）不要分配、直接忽略。
5) 只输出一个 JSON 对象，不要 Markdown 或解释。"""


def extract_multi_task(digest_with_lines: str) -> list | None:
    """从带编号的证据里拆出多个任务；失败返回 None。"""
    d = _call_ai_extract(f"屏幕活动证据（每行开头的[数字]是行编号）：\n{digest_with_lines}\n\n{_MULTI_TASK_SCHEMA}",
                         max_tokens=900)
    if isinstance(d, dict) and isinstance(d.get("tasks"), list):
        tasks = [t for t in d["tasks"] if isinstance(t, dict) and t.get("title")]
        return _merge_similar_tasks(tasks)
    return None


def _should_multi_task(session: list) -> bool:
    """只在「大且主题多样」的 session 上做多任务拆分，避免小 session 碎片化 + 浪费调用。"""
    if len(session) < 4:
        return False
    # summary 去重后的主题数：至少 3 种不同动作才值得拆
    topics = set()
    for r in session:
        s = _TOOL_PREFIX_RE.sub("", (r.get("summary") or "").strip())
        s = re.sub(r"^(使用|查看|浏览|分析|在)", "", s).strip()[:8]
        if s:
            topics.add(s)
    return len(topics) >= 3


def _merge_similar_tasks(tasks: list) -> list:
    """合并标题相似的任务（如"查看功能实现文档"/"查看功能实现界面"），防过度拆分。"""
    if len(tasks) <= 1:
        return tasks
    import difflib
    merged = []

    def norm(t):
        s = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", str(t))
        return re.sub(r"^(查看|使用|浏览|分析|了解)", "", s)

    for t in tasks:
        key = norm(t.get("title", ""))
        hit = None
        for m in merged:
            mk = norm(m.get("title", ""))
            # 相似度 > 0.6 或核心词互相包含 → 视为同一任务
            sim = difflib.SequenceMatcher(None, key, mk).ratio() if key and mk else 0
            if sim > 0.6 or (key and mk and (key in mk or mk in key)):
                hit = m
                break
        if hit:
            if len(str(t.get("title", ""))) > len(str(hit.get("title", ""))):
                hit["title"] = t["title"]
            hit["line_refs"] = list(dict.fromkeys(
                list(hit.get("line_refs") or []) + list(t.get("line_refs") or [])))
            hit["skills"] = list(dict.fromkeys(
                list(hit.get("skills") or []) + list(t.get("skills") or [])))
        else:
            merged.append(dict(t))
    return merged


# summary 里常见的「工具名 - 」前缀，生成标题前剥掉
_TOOL_PREFIX_RE = re.compile(
    r"^(DeepSeek Harness|Google Chrome|Chrome|WorkBuddy|微信|Weixin|文件资源管理器|"
    r"Explorer|Electron|Visual Studio Code|VS Code|Cursor)\s*[-—:：|]\s*", re.I,
)


def _rule_extract(session: list, project: str) -> dict:
    """规则兜底：从 session 得到最保守的经历（标题宁短勿脏）。"""
    cats = Counter(r.get("category") or "其他" for r in session)
    top_cat = cats.most_common(1)[0][0] if cats else "其他"
    # 清洗 summary：剥工具前缀、去噪声、去纯数字/括号残留
    candidates = []
    for r in session:
        s = _TOOL_PREFIX_RE.sub("", (r.get("summary") or "").strip()).strip()
        if not s or _NOISE_RE.search(s) or len(s) < 3:
            continue
        if re.match(r"^[（(\d\s]*$", s):  # 纯 "(10" 之类
            continue
        candidates.append(s)
    # 取中位数长度的候选（避免超长串也避免碎片），并截成完整短语
    if candidates:
        candidates.sort(key=len)
        best = candidates[len(candidates) // 2]
        # 去掉尾部被截断的半个词：按常见标点/空格收尾
        best = re.split(r"[，,。；;]", best)[0].strip()
        best = best[:24]
    else:
        best = ""
    skill = _CATEGORY_SKILL.get(top_cat, "")
    title = best if best and not _TOOL_PREFIX_RE.match(best) else f"{top_cat}相关工作"
    return {
        "match_existing": "",
        "title": title[:24],
        "summary": f"在 {project} 上进行 {top_cat} 相关工作，共 {len(session)} 段采集。",
        "skills": [skill] if skill else [],
        "collaborators": [],
        "status": "open",
        "evidence": [],
        "category": top_cat,
        "_source": "rule",
    }


# ── 合并写库 ───────────────────────────────────────────────
def _upsert_project(name: str, cat: str, minutes: float, ts: str) -> int:
    from db import get_conn
    if not name or name == "主体待确认":
        return 0
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO exp_project (name,total_min,first_seen,last_seen,confidence) VALUES (?,?,?,?,0.3) "
            "ON CONFLICT(name) DO UPDATE SET total_min=total_min+excluded.total_min, "
            "last_seen=excluded.last_seen, confidence=MIN(1.0, confidence+0.05)",
            (name, minutes, ts, ts),
        )
        row = conn.execute("SELECT id FROM exp_project WHERE name=?", (name,)).fetchone()
        conn.commit()
        return row["id"] if row else 0


def _merge_episode(project_id: int, project: str, d: dict, session: list) -> int:
    from db import get_conn
    title = (d.get("title") or "未命名经历").strip()[:40]
    fp = hashlib.md5(f"{project}|{title}".encode("utf-8")).hexdigest()
    cat = d.get("category") or (session[0].get("category") if session else "其他") or "其他"
    minutes = round(len(session) * 1.0, 1)  # 每条约 1 分钟
    ts = session[-1].get("timestamp") if session else _now()
    summary = (d.get("summary") or "")[:400]
    skills = d.get("skills") or []
    collabs = d.get("collaborators") or []
    evidence = d.get("evidence") or []
    source = d.get("_source", "ai")
    conf = 0.6 if source == "ai" else 0.35

    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM exp_task_episode WHERE project_id=? AND fingerprint=?",
            (project_id, fp),
        ).fetchone()
        if row:
            eid = row["id"]
            conn.execute(
                "UPDATE exp_task_episode SET total_min=total_min+?, sessions=sessions+1, "
                "end_ts=?, confidence=MIN(1.0,confidence+0.05), updated_at=? WHERE id=?",
                (minutes, ts, _now(), eid),
            )
        else:
            cur = conn.execute(
                "INSERT INTO exp_task_episode "
                "(project_id,title,summary,status,category,skills_json,collaborators_json,"
                "start_ts,end_ts,total_min,sessions,evidence_json,confidence,source,fingerprint) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?,?,?)",
                (project_id, title, summary, d.get("status", "open"), cat,
                 json.dumps(skills, ensure_ascii=False),
                 json.dumps(collabs, ensure_ascii=False),
                 session[0].get("timestamp") if session else ts, ts, minutes,
                 json.dumps(evidence, ensure_ascii=False), conf, source, fp),
            )
            eid = cur.lastrowid
        # 技能
        for sk in skills[:5]:
            sk = str(sk).strip()[:30]
            if not sk:
                continue
            conn.execute(
                "INSERT INTO exp_skill (name,category,total_min,episode_cnt,first_seen,last_seen) "
                "VALUES (?,?,?,1,?,?) ON CONFLICT(name) DO UPDATE SET "
                "total_min=total_min+excluded.total_min, episode_cnt=episode_cnt+1, last_seen=excluded.last_seen",
                (sk, cat, minutes, ts, ts),
            )
        # 协作对象（只存称呼）
        for cb in collabs[:5]:
            cb = str(cb).strip()[:30]
            if not cb:
                continue
            conn.execute(
                "INSERT INTO exp_collaborator (name,kind,category,interact_cnt,total_min,last_seen) "
                "VALUES (?,'person',?,1,?,?) ON CONFLICT(name) DO UPDATE SET "
                "interact_cnt=interact_cnt+1, total_min=total_min+excluded.total_min, last_seen=excluded.last_seen",
                (cb, cat, minutes, ts),
            )
        # 活动关联
        for r in session:
            conn.execute(
                "INSERT OR IGNORE INTO exp_activity_link (activity_id,episode_id,project_id,extracted) "
                "VALUES (?,?,?,1)", (r["id"], eid, project_id),
            )
        conn.commit()
        return eid


def _update_habits(rows: list) -> None:
    """规则更新工作习惯（零 AI）：高峰时段 + 分类专注度。"""
    if not rows:
        return
    hour_cnt = Counter()
    cat_cnt = Counter()
    for r in rows:
        ts = r.get("timestamp", "")
        if len(ts) >= 13:
            try:
                hour_cnt[int(ts[11:13])] += 1
            except ValueError:
                pass
        cat_cnt[r.get("category") or "其他"] += 1
    from db import get_conn
    with get_conn() as conn:
        if hour_cnt:
            peak = hour_cnt.most_common(3)
            val = json.dumps([{"hour": h, "count": n} for h, n in peak], ensure_ascii=False)
            conn.execute(
                "INSERT INTO exp_work_habit (habit_key,habit_type,value_json,evidence_cnt,confidence) "
                "VALUES ('peak_hours','rhythm',?,?,0.5) ON CONFLICT(habit_key) DO UPDATE SET "
                "value_json=excluded.value_json, evidence_cnt=evidence_cnt+excluded.evidence_cnt, updated_at=?",
                (val, sum(hour_cnt.values()), _now()),
            )
        top_cat = cat_cnt.most_common(1)[0][0] if cat_cnt else ""
        if top_cat:
            conn.execute(
                "INSERT INTO exp_work_habit (habit_key,habit_type,value_json,evidence_cnt,confidence) "
                "VALUES ('dominant_category','focus',?,?,0.5) ON CONFLICT(habit_key) DO UPDATE SET "
                "value_json=excluded.value_json, evidence_cnt=evidence_cnt+excluded.evidence_cnt, updated_at=?",
                (json.dumps({"category": top_cat}, ensure_ascii=False), sum(cat_cnt.values()), _now()),
            )
        conn.commit()


# ── 主入口 ─────────────────────────────────────────────────
def run_once(force: bool = False) -> dict:
    min_id = 0 if force else int(get_state("last_activity_id", "0") or 0)
    rows = collect_pending(min_id, limit=0 if force else 800)
    stats = {"scanned": len(rows), "sessions": 0, "episodes": 0, "ai": 0, "rule": 0}
    if not rows:
        return stats
    sessions = build_sessions(rows)
    stats["sessions"] = len(sessions)
    max_id = 0
    for sess in sessions:
        project = _project_of(sess[0])
        try:
            from db import get_conn
            with get_conn() as conn:
                open_rows = conn.execute(
                    "SELECT title FROM exp_task_episode WHERE status='open' "
                    "ORDER BY updated_at DESC LIMIT 15"
                ).fetchall()
            existing = [r["title"] for r in open_rows]
        except Exception:
            existing = []
        # 大且主题多样的 session 才做多任务拆分（防碎片化 + 省调用）
        digest_lines, idx_map = build_digest(sess, existing, number=True)
        tasks = extract_multi_task(digest_lines) if _should_multi_task(sess) else None
        pid = _upsert_project(project, sess[0].get("category", ""), round(len(sess), 1),
                              sess[-1].get("timestamp") or _now())
        if tasks:
            stats["ai"] += 1
            assigned = set()
            for t in tasks:
                # 按 line_refs 把证据行分配给该任务；无有效分配则跳过，避免全量归属
                refs = [int(x) for x in (t.get("line_refs") or []) if str(x).isdigit()]
                task_acts = [idx_map[i] for i in refs if i in idx_map and i not in assigned]
                for i in refs:
                    if i in idx_map:
                        assigned.add(i)
                if not task_acts:
                    continue  # 没有归属证据的任务不落库，防幻觉
                t = dict(t)
                t["_source"] = "ai"
                t["evidence"] = [f"{idx_map[i].get('timestamp','')[11:16]} {_clean_ai_detail(idx_map[i].get('ai_detail'), 40)}"
                                 for i in refs if i in idx_map][:3]
                _merge_episode(pid, project, t, task_acts)
                stats["episodes"] += 1
        else:
            # AI 整体失败 → 单任务归纳 → 再失败 → 规则兜底
            d = extract_with_ai(build_digest(sess, existing))
            if d:
                stats["ai"] += 1
                d = dict(d); d["_source"] = "ai"
            else:
                d = _rule_extract(sess, project)
                stats["rule"] += 1
            _merge_episode(pid, project, d, sess)
            stats["episodes"] += 1
        max_id = max(max_id, max(r["id"] for r in sess))
    _update_habits(rows)
    if max_id:
        set_state("last_activity_id", max_id)
    return stats


# ── 供各功能消费的上下文 ────────────────────────────────────
def get_experience_profile(days: int = 90) -> dict:
    from db import get_conn
    cutoff = (datetime.now() - __import__("datetime").timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        projects = [dict(r) for r in conn.execute(
            "SELECT name,total_min,status,confidence,last_seen FROM exp_project "
            "WHERE last_seen>=? ORDER BY total_min DESC LIMIT 20", (cutoff,))]
        episodes = [dict(r) for r in conn.execute(
            "SELECT e.id,e.title,e.summary,e.status,e.category,e.total_min,e.sessions,e.end_ts,"
            "e.evidence_json,e.skills_json,e.source,p.name project FROM exp_task_episode e "
            "LEFT JOIN exp_project p ON p.id=e.project_id "
            "WHERE e.end_ts>=? ORDER BY e.end_ts DESC LIMIT 50", (cutoff,))]
        skills = [dict(r) for r in conn.execute(
            "SELECT name,category,level,total_min,episode_cnt FROM exp_skill "
            "ORDER BY total_min DESC LIMIT 20")]
        collabs = [dict(r) for r in conn.execute(
            "SELECT name,kind,interact_cnt,total_min FROM exp_collaborator "
            "ORDER BY interact_cnt DESC LIMIT 15")]
        habits = [dict(r) for r in conn.execute(
            "SELECT habit_key,habit_type,value_json,confidence FROM exp_work_habit "
            "ORDER BY evidence_cnt DESC LIMIT 10")]
    for e in episodes:
        e["evidence"] = _jsond(e.get("evidence_json"), [])
        e["skills"] = _jsond(e.get("skills_json"), [])
        e.pop("evidence_json", None)
        e.pop("skills_json", None)
    return {"projects": projects, "episodes": episodes, "skills": skills,
            "collaborators": collabs, "habits": habits,
            "generated_at": _now()}


def get_experience_context(max_chars: int = 1500) -> str:
    p = get_experience_profile(90)
    lines = ["【任务经历档案 · 近90天】"]
    if p["projects"]:
        lines.append("重点项目：" + "、".join(
            f"{x['name']}({round(x['total_min'])}min,{x['status']})" for x in p["projects"][:5]))
    open_eps = [e for e in p["episodes"] if e["status"] == "open"][:5]
    if open_eps:
        lines.append("在推进的经历：")
        for e in open_eps:
            lines.append(f"  - [{e.get('project') or '主体待确认'}] {e['title']}（{e['sessions']}次，{round(e['total_min'])}min）")
    if p["skills"]:
        lines.append("技能图谱：" + " · ".join(
            f"{s['name']}({round(s['total_min'])}min/{s['episode_cnt']}段)" for s in p["skills"][:8]))
    if p["collaborators"]:
        lines.append("协作画像：" + " · ".join(
            f"{c['name']}({c['interact_cnt']}次)" for c in p["collaborators"][:5]))
    for h in p["habits"]:
        if h["habit_key"] == "dominant_category":
            v = _jsond(h["value_json"], {})
            if v.get("category"):
                lines.append(f"工作习惯：主要分类 {v['category']}")
    text = "\n".join(lines)
    return text[:max_chars] if len(text) > 40 else ""


# ── 历史活动 workspace 回填（启发式，仅补空值）─────────────────
def backfill_workspace(limit: int = 0) -> dict:
    """给 workspace 为空的历史活动补工作区信号（从 ai_detail 里的路径/工程名推断）。

    保守策略：只在证据明确时补，猜不到保持空；已填的不覆盖。
    limit=0 表示全量。
    """
    from db import get_conn
    # 已知工作区特征：ai_detail 里出现的路径片段 -> workspace 名（与 workspace.json 对齐）
    # 用纯字符串包含匹配（避免正则里反斜杠字符集的转义坑）
    patterns = [
        ("d:\\project\\daily", "daily"),
        ("deepseek-harness\\default-workspace", "default-workspace"),
        (".dsh-fish\\home", "大肥鱼的家"),
    ]
    with get_conn() as conn:
        if limit > 0:
            rows = conn.execute(
                "SELECT id,ai_detail,window_title FROM activities "
                "WHERE (workspace IS NULL OR workspace='') AND ai_detail<>'' LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id,ai_detail,window_title FROM activities "
                "WHERE (workspace IS NULL OR workspace='') AND ai_detail<>''"
            ).fetchall()
    stats = {"scanned": len(rows), "filled": 0}
    with get_conn() as conn:
        for r in rows:
            blob = (r["ai_detail"] or "") + " " + (r["window_title"] or "")
            hit = ""
            low = blob.lower()
            for needle, name in patterns:
                if needle.lower() in low:
                    hit = name
                    break
            if hit:
                conn.execute("UPDATE activities SET workspace=? WHERE id=?", (hit, r["id"]))
                stats["filled"] += 1
        conn.commit()
    return stats


# ── AI 全量升级：把规则版经历分批重归纳成 AI 版 ──────────────
def upgrade_rule_episodes_with_ai(batch: int = 20, max_per_day: int = 40) -> dict:
    """挑 source='rule' 的经历，用其原始活动证据重调 AI，成功后原地升级。

    - 每天限量 max_per_day（复用日预算计数，分批多天跑完，避免一次烧爆）
    - 只升级 title/summary/skills/collaborators/status/source，保留 sessions/total_min/时长
    - 失败保持原样，下次可重试；可随时中断（每次处理一条即提交）
    """
    stats = {"picked": 0, "upgraded": 0, "failed": 0, "skipped_budget": 0}
    today = datetime.now().strftime("%Y-%m-%d")
    used = int(get_state(f"daily_call_count:{today}", "0") or 0)
    if used >= max_per_day:
        stats["skipped_budget"] = 1
        return stats

    from db import get_conn
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT e.id, e.title, e.category, e.total_min, e.sessions, p.name project "
            "FROM exp_task_episode e LEFT JOIN exp_project p ON p.id=e.project_id "
            "WHERE e.source='rule' ORDER BY e.total_min DESC LIMIT ?",
            (batch,),
        ).fetchall()
    for row in rows:
        if used >= max_per_day:
            stats["skipped_budget"] = 1
            break
        stats["picked"] += 1
        eid = row["id"]
        # 取该经历关联的活动证据，重建 digest
        with get_conn() as conn:
            acts = conn.execute(
                "SELECT a.timestamp,a.window_title,a.category,a.summary,a.ai_detail "
                "FROM exp_activity_link l JOIN activities a ON a.id=l.activity_id "
                "WHERE l.episode_id=? ORDER BY a.timestamp DESC LIMIT 10", (eid,)).fetchall()
        if not acts:
            stats["failed"] += 1
            continue
        sess = [dict(a) for a in acts]
        digest = build_digest(sess, [])
        ai = extract_with_ai(digest)  # 内部已计预算/熔断
        used = int(get_state(f"daily_call_count:{today}", "0") or 0)
        if not ai or not (ai.get("title") or "").strip():
            stats["failed"] += 1
            continue
        # 原地升级：只改语义字段，不动数值统计
        title = str(ai["title"]).strip()[:40]
        fp = hashlib.md5(f"{row['project'] or '主体待确认'}|{title}".encode("utf-8")).hexdigest()
        with get_conn() as conn:
            conn.execute(
                "UPDATE exp_task_episode SET title=?, summary=?, status=?, category=?, "
                "skills_json=?, collaborators_json=?, evidence_json=?, confidence=0.7, "
                "source='ai', fingerprint=?, updated_at=? WHERE id=?",
                (title, str(ai.get("summary", ""))[:400],
                 ai.get("status", "open") if ai.get("status") in ("open", "done") else "open",
                 ai.get("category") if ai.get("category") in __import__("config").CATEGORIES else row["category"],
                 json.dumps((ai.get("skills") or [])[:5], ensure_ascii=False),
                 json.dumps((ai.get("collaborators") or [])[:5], ensure_ascii=False),
                 json.dumps((ai.get("evidence") or [])[:3], ensure_ascii=False),
                 fp, _now(), eid),
            )
            conn.commit()
        # 补写新技能到 exp_skill（不重复计 episode_cnt，只登记名字）
        for sk in (ai.get("skills") or [])[:5]:
            sk = str(sk).strip()[:30]
            if not sk:
                continue
            with get_conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO exp_skill (name,category,first_seen,last_seen) VALUES (?,?,?,?)",
                    (sk, row["category"] or "", _now(), _now()),
                )
                conn.commit()
        stats["upgraded"] += 1
    return stats


# ── 反证闭环：其它功能的产出回写档案 ─────────────────────────
def mark_episodes_done_from_text(text: str) -> int:
    """日报/首页确认『完成』的经历 → 标记对应 open episode 为 done。

    只在文本明确提到经历标题（或其核心短语）时才标记，避免误判。
    返回标记数量。
    """
    if not text or len(text) < 10:
        return 0
    from db import get_conn
    with get_conn() as conn:
        eps = conn.execute(
            "SELECT id,title FROM exp_task_episode WHERE status='open' AND length(title)>=4"
        ).fetchall()
    # 只认明确完成句式，避免"在推进 XX"被误判成完成
    done_re = re.search(r"(已完成|完成了|成功完成|解决了|已修复|发布上线|已交付)", text)
    if not done_re:
        return 0
    # 截取完成句式附近的上下文（前后 60 字）作为匹配范围
    pos = done_re.start()
    context = text[max(0, pos - 60): pos + 100]
    changed = 0
    with get_conn() as conn:
        for e in eps:
            title = (e["title"] or "").strip()
            core = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", title)[:12]
            if len(core) >= 4 and core in context:
                conn.execute(
                    "UPDATE exp_task_episode SET status='done', updated_at=? WHERE id=?",
                    (_now(), e["id"]),
                )
                changed += 1
        if changed:
            conn.commit()
    return changed


def record_cognition_habit(atype: str, result_json: dict, confidence: float = 0.0) -> None:
    """AI 自我认知结论 → 写入 exp_work_habit 的性格维度，给档案加一层性格画像。"""
    if not result_json:
        return
    key = f"cognition:{atype}"
    # 只保留可展示的关键字段，压缩存 JSON
    keep = {}
    for k in ("mbti_type", "ei_label", "sn_label", "tf_label", "jp_label",
              "dominant_function", "wa_label", "vi_label", "ri_label", "narrative"):
        if k in result_json:
            keep[k] = result_json[k]
    if atype == "big_five":
        for k in ("openness_score", "conscientiousness_score", "extraversion_score",
                  "agreeableness_score", "neuroticism_score"):
            if k in result_json:
                keep[k] = result_json[k]
    if not keep:
        return
    from db import get_conn
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO exp_work_habit (habit_key,habit_type,value_json,confidence,source) "
            "VALUES (?,'cognition',?,?,'cognition') ON CONFLICT(habit_key) DO UPDATE SET "
            "value_json=excluded.value_json, confidence=excluded.confidence, "
            "evidence_cnt=evidence_cnt+1, updated_at=?",
            (key, json.dumps(keep, ensure_ascii=False), round(float(confidence), 2), _now()),
        )
        conn.commit()
