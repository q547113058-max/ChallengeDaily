"""记忆生产者：把已有数据源的事实写入记忆库
==============================================

背景：记忆系统此前「有引擎、有 API、有 UI，但没有生产者」，
memories / doc_chunks 常年为 0 行，前端两个按钮也因参数不匹配必然 400。

本模块补齐「生产者」这一层：

1) extract_from_source()  —— 从已有数据源（日报 / 日记 / 反思 / 画像 / 活动记录）
   批量抽取原子事实写入 memories，按 source_id 幂等去重。
2) auto_extract_async()   —— 写入型操作（如日报生成）后的异步自动抽取钩子，
   不阻塞主流程，失败仅记日志。

抽取能力复用 memory_engine.extract_facts（LLM 优先，失败降级关键词抽取）。
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional

from db import get_conn

logger = logging.getLogger(__name__)

# 支持的数据源
SUPPORTED_SOURCES = ("report", "diary", "reflection", "profile", "activity")

SOURCE_LABELS = {
    "report": "日报",
    "diary": "日记",
    "reflection": "每日反思",
    "profile": "每日画像",
    "activity": "活动记录",
}

# 单条源文本抽取上限（extract_facts 内部还会再截断一次）
_MAX_TEXT_LEN = 4000
# 活动记录：每天最多聚合的条数，避免文本过长
_ACTIVITY_PER_DAY = 60


def _since(days: int) -> str:
    try:
        days = max(1, min(3650, int(days)))
    except (TypeError, ValueError):
        days = 7
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")


def _existing_source_ids(prefix: str) -> set[str]:
    """已抽取过的 source_id 集合（用于幂等去重，排除软删除）"""
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT source_id FROM memories "
                "WHERE source_id LIKE ? AND (deleted_at IS NULL OR deleted_at = '')",
                (f"{prefix}:%",),
            ).fetchall()
        return {r[0] for r in rows if r[0]}
    except Exception as e:
        logger.warning(f"[memory] 查询已抽取 source_id 失败（按未抽取处理）: {e}")
        return set()


def _fetch_source_texts(source: str, days: int, limit: int) -> list[tuple[str, str]]:
    """从指定数据源读取文本，返回 [(source_id, text), ...]（按时间倒序）"""
    since = _since(days)
    try:
        limit = max(1, min(200, int(limit)))
    except (TypeError, ValueError):
        limit = 7

    out: list[tuple[str, str]] = []
    with get_conn() as conn:
        if source == "report":
            rows = conn.execute(
                "SELECT report_date, content FROM reports "
                "WHERE report_date >= ? ORDER BY report_date DESC LIMIT ?",
                (since, limit),
            ).fetchall()
            for r in rows:
                txt = (r[1] or "").strip()
                if txt:
                    out.append((f"report:{r[0]}", txt[:_MAX_TEXT_LEN]))

        elif source == "diary":
            rows = conn.execute(
                "SELECT diary_date, content, highlights, gratitude, mood FROM diaries "
                "WHERE diary_date >= ? ORDER BY diary_date DESC LIMIT ?",
                (since, limit),
            ).fetchall()
            for r in rows:
                parts = [r[1] or "", r[2] or "", r[3] or ""]
                if r[4]:
                    parts.append(f"心情：{r[4]}")
                txt = "\n".join(p.strip() for p in parts if p and p.strip()).strip()
                if txt:
                    out.append((f"diary:{r[0]}", txt[:_MAX_TEXT_LEN]))

        elif source == "reflection":
            rows = conn.execute(
                "SELECT date, good_thing, improve_thing, ai_insights_json FROM daily_reflections "
                "WHERE date >= ? ORDER BY date DESC LIMIT ?",
                (since, limit),
            ).fetchall()
            for r in rows:
                parts = [r[1] or "", r[2] or ""]
                raw = r[3]
                if raw:
                    try:
                        ins = json.loads(raw)
                        if isinstance(ins, list):
                            parts += [str(x) for x in ins]
                        elif isinstance(ins, dict):
                            parts.append(json.dumps(ins, ensure_ascii=False))
                        else:
                            parts.append(str(ins))
                    except Exception:
                        parts.append(str(raw))
                txt = "\n".join(p.strip() for p in parts if p and str(p).strip()).strip()
                if txt:
                    out.append((f"reflection:{r[0]}", txt[:_MAX_TEXT_LEN]))

        elif source == "profile":
            rows = conn.execute(
                "SELECT date, daily_summary, key_insights, work_patterns, behavior_tags "
                "FROM daily_profiles WHERE date >= ? ORDER BY date DESC LIMIT ?",
                (since, limit),
            ).fetchall()
            for r in rows:
                parts = [r[1] or "", r[2] or "", r[3] or "", r[4] or ""]
                txt = "\n".join(p.strip() for p in parts if p and str(p).strip()).strip()
                if txt:
                    out.append((f"profile:{r[0]}", txt[:_MAX_TEXT_LEN]))

        elif source == "activity":
            rows = conn.execute(
                "SELECT substr(timestamp, 1, 10) AS d, summary FROM activities "
                "WHERE timestamp >= ? AND COALESCE(trim(summary), '') <> '' "
                "ORDER BY timestamp DESC",
                (since,),
            ).fetchall()
            by_day: dict[str, list[str]] = {}
            for d, s in rows:
                if not d:
                    continue
                bucket = by_day.setdefault(d, [])
                if len(bucket) < _ACTIVITY_PER_DAY:
                    bucket.append((s or "").strip())
            for d in sorted(by_day, reverse=True)[:limit]:
                # dict.fromkeys 去重且保持顺序
                txt = "\n".join(x for x in dict.fromkeys(by_day[d]) if x).strip()
                if txt:
                    out.append((f"activity:{d}", txt[:_MAX_TEXT_LEN]))

    return out


def extract_from_source(source: str = "report", days: int = 7, limit: int = 7,
                        force: bool = False) -> dict:
    """从指定数据源批量抽取事实写入记忆库（幂等）。

    返回 {source, scanned, added, facts, skipped, memory_ids, label}
    """
    src = (source or "report").strip()
    if src not in SUPPORTED_SOURCES:
        return {"error": f"不支持的数据源: {src}（可选 {', '.join(SUPPORTED_SOURCES)}）"}

    # 惰性导入，避免 memory_engine 导入失败影响调用方
    import memory_engine

    items = _fetch_source_texts(src, days, limit)
    if not items:
        return {
            "source": src, "label": SOURCE_LABELS.get(src, src),
            "scanned": 0, "added": 0, "facts": 0, "skipped": 0,
            "memory_ids": [], "message": "该数据源暂无可用文本",
        }

    done = set() if force else _existing_source_ids(src)
    added_ids: list[str] = []
    facts_total = 0
    skipped = 0

    for source_id, text in items:
        if source_id in done:
            skipped += 1
            continue
        try:
            facts = memory_engine.extract_facts(text, source_type=src, source_id=source_id)
        except Exception as e:
            logger.warning(f"[memory] 抽取失败 source={source_id}: {e}")
            facts = []
        facts_total += len(facts)
        for f in facts:
            try:
                mid = memory_engine.add_memory(f, source_type=src, source_id=source_id)
                if mid:
                    added_ids.append(mid)
            except Exception as e:
                logger.warning(f"[memory] 写入记忆失败 source={source_id}: {e}")

        # 同步把源文本索引进 doc_chunks（供文档片段检索使用）
        # index_document 基于 content_hash 增量同步，重复调用幂等
        try:
            memory_engine.index_document(src, source_id, text, title=source_id)
        except Exception as e:
            logger.debug(f"[memory] 源文本索引失败（不影响事实抽取）source={source_id}: {e}")

    return {
        "source": src,
        "label": SOURCE_LABELS.get(src, src),
        "scanned": len(items),
        "added": len(added_ids),
        "facts": facts_total,
        "skipped": skipped,
        "memory_ids": added_ids,
    }


def auto_extract_async(text: str, source_type: str, source_id: str) -> None:
    """异步自动抽取（写入型操作后调用，不阻塞主流程）。

    已抽取过的 source_id 会自动跳过，避免日报覆盖式保存导致重复灌入。
    """
    if not text or not text.strip():
        return

    def _run():
        try:
            if source_id in _existing_source_ids(source_type):
                logger.debug(f"[memory] 已抽取过，跳过: {source_id}")
                return
            import memory_engine
            facts = memory_engine.extract_facts(
                text[:_MAX_TEXT_LEN], source_type=source_type, source_id=source_id
            )
            n = 0
            for f in facts:
                if memory_engine.add_memory(f, source_type=source_type, source_id=source_id):
                    n += 1
            logger.info(f"[memory] 自动抽取完成 {source_id}: {len(facts)} 条事实，写入 {n} 条")
        except Exception as e:
            logger.warning(f"[memory] 自动抽取失败 {source_id}: {e}")

    threading.Thread(target=_run, daemon=True, name="memory-auto-extract").start()
