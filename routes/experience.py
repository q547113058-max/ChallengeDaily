"""任务经历档案 API：供前端展示与各功能消费。"""
from flask import Blueprint, jsonify, request

logger_bp = Blueprint('experience', __name__)


@logger_bp.route('/api/experience/profile', methods=['GET'])
def exp_profile():
    try:
        from experience_pipeline import get_experience_profile
        try:
            days = int(request.args.get('days', '90'))
        except ValueError:
            days = 90
        return jsonify({"ok": True, "profile": get_experience_profile(days)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:120]}), 500


@logger_bp.route('/api/experience/context', methods=['GET'])
def exp_context():
    try:
        from experience_pipeline import get_experience_context
        return jsonify({"ok": True, "context": get_experience_context(2000)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:120]}), 500


@logger_bp.route('/api/experience/rebuild', methods=['POST'])
def exp_rebuild():
    """手动触发增量提炼；?full=1 全量回扫。"""
    try:
        from experience_pipeline import run_once
        full = request.args.get('full', '') == '1'
        stats = run_once(force=full)
        return jsonify({"ok": True, "stats": stats})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:120]}), 500
