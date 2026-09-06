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
        results = me.hybrid_search(query, limit=limit)
        return jsonify({"results": results, "count": len(results), "query": query})
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

    Body:
        {"content": "...", "source_type": "manual", "source_id": "xxx"}
    """
    if not check_token(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(force=True, silent=True) or {}
    try:
        me = _memory_engine()
        content = (data.get('content') or '').strip()
        if not content:
            return jsonify({"error": "content 不能为空"}), 400
        source_type = (data.get('source_type') or 'manual').strip()
        source_id = (data.get('source_id') or '').strip()
        facts = me.extract_facts(content, source_type=source_type, source_id=source_id)
        added_ids = []
        for f in facts:
            mid = me.add_memory(f, source_type=source_type, source_id=source_id)
            if mid:
                added_ids.append(mid)
        return jsonify({"facts": facts, "memory_ids": added_ids})
    except Exception as e:
        return jsonify({"error": safe_error(e, "事实抽取失败")}), 500

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
