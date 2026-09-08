"""记忆系统 API
================
提供 /api/memory/* 接口：
  POST /api/memory/search         混合检索（BM25 + 向量 RRF）
  POST /api/memory/index          手动向量化（提供 content 直接索引）
  GET  /api/memory/status         向量化状态
  POST /api/memory/extract        手动触发事实抽取（提供 content）
  GET  /api/memory/list           列出所有记忆
  DELETE /api/memory/<memory_id>  删除记忆
  POST /api/memory/query          AI 对话记忆注入
"""
import logging
import re
import threading

from flask import Blueprint, request, jsonify

from routes.deps import check_token, safe_error

logger = logging.getLogger(__name__)

# 记忆系统独立蓝图
memory_bp = Blueprint('memory', __name__, url_prefix='/api/memory')

# memory_id 安全校验：仅允许 UUID 格式（防止 SQL 注入 / 路径穿越）
_MEMORY_ID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")
def _memory_engine():
    """惰性加载 memory_engine，避免模块导入失败影响整个蓝图注册"""
    import memory_engine
    return memory_engine


@memory_bp.route('/search', methods=['POST'])
def memory_search():
    """混合检索（BM25 + 向量 RRF）

    Body: {"query": "搜索词", "limit": 10}
    """
    if not check_token(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(force=True, silent=True) or {}
    query = (data.get('query') or '').strip()
    if not query:
        return jsonify({"error": "query 不能为空"}), 400
    if len(query) > 500:
        return jsonify({"error": "query 过长（上限 500 字符）"}), 400
    try:
        limit = max(1, min(50, int(data.get('limit', 10))))
    except (TypeError, ValueError):
        limit = 10
    try:
        me = _memory_engine()
        # 记忆条目检索（memories 表）+ 文档片段检索（doc_chunks 表）双路合并。
        # 此前只走 hybrid_search（doc_chunks），而记忆实际存在 memories 表，
        # 导致「记忆明明有数据却搜不到」。
        mem_hits = []
        try:
            mem_hits = me.search_memories(query, limit=limit)
        except Exception as e:
            logger.debug(f"记忆条目检索失败: {e}")
        doc_hits = []
        try:
            doc_hits = me.hybrid_search(query, limit=limit)
        except Exception as e:
            logger.debug(f"文档片段检索失败: {e}")

        merged: list[dict] = []
        seen: set[str] = set()
        for hit in list(mem_hits) + list(doc_hits):
            key = (hit.get("id") or "") or (hit.get("content") or "")[:80]
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append({
                "id": hit.get("id") or "",
                "content": hit.get("content") or hit.get("snippet") or "",
                "source": hit.get("source") or hit.get("source_type") or "",
                "source_type": hit.get("source_type") or hit.get("source") or "",
                "score": hit.get("score"),
                "snippet": hit.get("snippet"),
                "created_at": hit.get("created_at"),
            })
            if len(merged) >= limit:
                break
        return jsonify({"results": merged, "count": len(merged), "query": query})
    except Exception as e:
        return jsonify({"error": safe_error(e, "检索失败")}), 500


@memory_bp.route('/index', methods=['POST'])
def memory_index():
    """手动触发向量化

    Body:
        {"source": "manual", "source_id": "xxx", "content": "正文", "title": "标题"}
    """
    if not check_token(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(force=True, silent=True) or {}
    try:
        me = _memory_engine()
        source = (data.get('source') or 'manual').strip()
        source_id = (data.get('source_id') or '').strip()
        content = (data.get('content') or '').strip()
        title = (data.get('title') or '').strip()
        if not source_id:
            return jsonify({"error": "source_id 不能为空"}), 400
        if not content:
            return jsonify({"error": "content 不能为空"}), 400
        n = me.index_document(source, source_id, content, title=title, force=bool(data.get('force', False)))
        return jsonify({"status": "ok", "source": source, "source_id": source_id, "chunks_written": n})
    except Exception as e:
        return jsonify({"error": safe_error(e, "索引失败")}), 500

@memory_bp.route('/status', methods=['GET'])
def memory_status():
    """向量化状态"""
    try:
        me = _memory_engine()
        return jsonify(me.get_indexing_status())
    except Exception as e:
        return jsonify({"error": safe_error(e, "状态获取失败")}), 500


@memory_bp.route('/extract', methods=['POST'])
def memory_extract():
    """手动触发事实抽取

    两种模式：
      1) 提供 content：{"content": "...", "source_type": "manual", "source_id": "xxx"}
      2) 不提供 content，改为从数据源批量抽取：
         {"source": "report|diary|reflection|profile|activity", "days": 7, "limit": 7}
         —— 此前前端按钮只发 {}，后端强制要 content 导致必然 400，此处兼容修复。
    """
    if not check_token(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(force=True, silent=True) or {}

    # ── 模式 2：从数据源批量抽取（无需 content）──
    if not (data.get('content') or '').strip() and data.get('source'):
        try:
            import memory_producer
        except Exception as e:
            return jsonify({"error": safe_error(e, "记忆生产者不可用")}), 500
        try:
            days = int(data.get('days', 7))
        except (TypeError, ValueError):
            days = 7
        try:
            limit = int(data.get('limit', 7))
        except (TypeError, ValueError):
            limit = 7
        res = memory_producer.extract_from_source(
            source=str(data.get('source') or 'report'),
            days=days,
            limit=limit,
            force=bool(data.get('force', False)),
        )
        if res.get('error'):
            return jsonify({"error": res["error"]}), 400
        res["status"] = "ok"
        return jsonify(res)

    # ── 模式 1：显式文本抽取 ──
    try:
        me = _memory_engine()
        content = (data.get('content') or '').strip()
        if not content:
            return jsonify({
                "error": "content 不能为空；若要从数据源批量抽取，请改传 "
                         "{\"source\": \"report|diary|reflection|profile|activity\", \"days\": 7}",
                "supported_sources": ["report", "diary", "reflection", "profile", "activity"],
            }), 400
        source_type = (data.get('source_type') or 'manual').strip()
        source_id = (data.get('source_id') or '').strip()
        facts = me.extract_facts(content, source_type=source_type, source_id=source_id)
        added_ids = []
        for f in facts:
            mid = me.add_memory(f, source_type=source_type, source_id=source_id)
            if mid:
                added_ids.append(mid)
        return jsonify({"facts": facts, "memory_ids": added_ids, "added": len(added_ids)})
    except Exception as e:
        return jsonify({"error": safe_error(e, "事实抽取失败")}), 500


@memory_bp.route('/auto-extract', methods=['POST'])
def memory_auto_extract():
    """从已有数据源自动抽取事实入库（记忆生产者）

    Body: {"source": "report", "days": 30, "limit": 7, "force": false}

    source 可选：report(日报) / diary(日记) / reflection(反思) / profile(画像) / activity(活动记录)
    幂等：同一 source_id 已抽取过会自动跳过（force=true 可强制重跑）。
    """
    if not check_token(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(force=True, silent=True) or {}
    try:
        import memory_producer
    except Exception as e:
        return jsonify({"error": safe_error(e, "记忆生产者不可用")}), 500
    try:
        days = int(data.get('days', 30))
    except (TypeError, ValueError):
        days = 30
    try:
        limit = int(data.get('limit', 7))
    except (TypeError, ValueError):
        limit = 7
    res = memory_producer.extract_from_source(
        source=str(data.get('source') or 'report'),
        days=days,
        limit=limit,
        force=bool(data.get('force', False)),
    )
    if res.get('error'):
        return jsonify({"error": res["error"]}), 400
    res["status"] = "ok"
    return jsonify(res)


@memory_bp.route('/sources', methods=['GET'])
def memory_sources():
    """列出可抽取的数据源及其可用文本条数（供前端下拉展示）"""
    try:
        import memory_producer
    except Exception:
        return jsonify({"sources": []})
    days = request.args.get('days', '30')
    try:
        days = max(1, min(3650, int(days)))
    except (TypeError, ValueError):
        days = 30
    out = []
    for s in memory_producer.SUPPORTED_SOURCES:
        try:
            items = memory_producer._fetch_source_texts(s, days, 50)
            out.append({
                "source": s,
                "label": memory_producer.SOURCE_LABELS.get(s, s),
                "available": len(items),
            })
        except Exception:
            out.append({"source": s, "label": memory_producer.SOURCE_LABELS.get(s, s), "available": 0})
    return jsonify({"sources": out, "days": days})

@memory_bp.route('/list', methods=['GET'])
def memory_list():
    """列出所有记忆

    Query: source_type=xxx&limit=100&include_deleted=0
    """
    try:
        me = _memory_engine()
        source_type = request.args.get('source_type') or None
        try:
            limit = max(1, min(500, int(request.args.get('limit', 100))))
        except (TypeError, ValueError):
            limit = 100
        include_deleted = request.args.get('include_deleted', '0') in ('1', 'true', 'yes')
        items = me.list_memories(source_type=source_type, limit=limit, include_deleted=include_deleted)
        return jsonify({"memories": items, "count": len(items)})
    except Exception as e:
        return jsonify({"error": safe_error(e, "列表查询失败")}), 500


@memory_bp.route('/<memory_id>', methods=['DELETE'])
def memory_delete(memory_id):
    """删除记忆（软删除）"""
    if not check_token(request):
        return jsonify({"error": "Unauthorized"}), 401
    if not memory_id or not _MEMORY_ID_RE.match(memory_id):
        return jsonify({"error": "memory_id 格式非法"}), 400
    try:
        me = _memory_engine()
        ok = me.delete_memory(memory_id)
        if not ok:
            return jsonify({"error": "记忆不存在或已删除"}), 404
        return jsonify({"status": "ok", "memory_id": memory_id})
    except Exception as e:
        return jsonify({"error": safe_error(e, "删除失败")}), 500


@memory_bp.route('/query', methods=['POST'])
def memory_query():
    """AI 对话记忆注入——返回与 query 相关的记忆 + 文档片段上下文

    Body: {"query": "用户提问", "max_tokens": 2000}
    """
    if not check_token(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(force=True, silent=True) or {}
    query = (data.get('query') or '').strip()
    if not query:
        return jsonify({"error": "query 不能为空"}), 400
    if len(query) > 1000:
        return jsonify({"error": "query 过长（上限 1000 字符）"}), 400
    try:
        max_tokens = max(200, min(8000, int(data.get('max_tokens', 2000))))
    except (TypeError, ValueError):
        max_tokens = 2000
    try:
        me = _memory_engine()
        context = me.build_memory_context(query, max_tokens=max_tokens)
        # 同时返回结构化检索结果，方便前端展示
        memories = me.search_memories(query, limit=5)
        chunks = me.hybrid_search(query, limit=8)
        return jsonify({
            "query": query,
            "context": context,
            "memories": memories,
            "chunks": chunks,
        })
    except Exception as e:
        return jsonify({"error": safe_error(e, "记忆查询失败")}), 500
