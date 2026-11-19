"""用户画像 + 每日画像 + 纠正记录 API"""
import logging

from flask import Blueprint, jsonify, request

from routes.deps import safe_error
import config

logger = logging.getLogger(__name__)

bp = Blueprint('profile', __name__)


@bp.route("/api/profile", methods=["GET"])
def get_profile():
    """获取用户画像"""
    from context_manager import get_user_profile, get_user_corrections
    profile = get_user_profile()
    corrections = get_user_corrections()
    return jsonify({"profile": profile, "corrections": corrections})


@bp.route("/api/profile", methods=["POST"])
def save_profile():
    """保存用户画像"""
    data = request.get_json(force=True) if request.is_json else {}
    if not data:
        return jsonify({"error": "No data provided"}), 400
    from context_manager import save_user_profile
    save_user_profile(data)
    return jsonify({"ok": True})


@bp.route("/api/profile/correction", methods=["POST"])
def add_correction():
    """添加一条分类纠正"""
    data = request.get_json(force=True) if request.is_json else {}
    app_name = data.get("app_name", "")
    if not app_name:
        return jsonify({"error": "app_name is required"}), 400
    from context_manager import add_user_correction
    add_user_correction(
        app_name=app_name,
        correct_category=data.get("correct_category", ""),
        correct_desc=data.get("correct_desc", ""),
        notes=data.get("notes", ""),
    )

    # 自进化：纠正自动转化为分类规则，下次不再犯同样的错
    correct_category = data.get("correct_category", "")
    if correct_category:
        try:
            from db import upsert_app_category_rule
            upsert_app_category_rule(
                app_name=app_name,
                primary_category=correct_category,
                tags=[correct_category],
                display_name=data.get("correct_desc", "") or app_name,
            )
            # 刷新分类器缓存
            from classifier import invalidate_rule_cache
            invalidate_rule_cache()
        except Exception as e:
            logger.warning(f"纠正自动写规则失败: {e}")

    return jsonify({"ok": True})


@bp.route("/api/profile/correction/<int:correction_id>", methods=["DELETE"])
def delete_correction(correction_id):
    """删除一条纠正"""
    from context_manager import delete_user_correction
    delete_user_correction(correction_id)
    return jsonify({"ok": True})


@bp.route("/api/profile/daily/<date_str>")
def get_daily_profile(date_str):
    """获取某天的日画像"""
    from context_manager import get_daily_profile as _get
    profile = _get(date_str)
    if not profile:
        return jsonify({"profile": None})
    return jsonify({"profile": profile})


@bp.route("/api/profile/daily/<date_str>/generate", methods=["POST"])
def generate_daily_profile(date_str):
    """手动触发生成某天的日画像"""
    from context_manager import generate_daily_profile as _gen, save_daily_profile as _save
    profile = _gen(date_str)
    if profile:
        _save(date_str, profile)
        return jsonify({"ok": True, "profile": profile})
    return jsonify({"ok": False, "error": "No data for this date"}), 404


@bp.route("/api/profile/weekly-context")
def get_weekly_context():
    """获取周上下文（供前端调试查看）"""
    days = request.args.get("days", 7, type=int)
    from context_manager import build_weekly_context
    context = build_weekly_context(days)
    return jsonify({"context": context})


@bp.route("/api/profile/distilled", methods=["GET"])
def get_distilled_profile_route():
    """返回聚合后的全周期用户画像（工作习惯、常用软件、工作内容、行为模式、效率趋势）"""
    from context_manager import get_distilled_profile
    return jsonify(get_distilled_profile())


# ─── AI 自我认知分析（累积理解系统） ─────────────────────────

@bp.route("/api/profile/analysis", methods=["GET"])
def get_all_analyses():
    """获取所有 AI 自我认知分析结果"""
    try:
        from db import get_all_profile_analyses
        analyses = get_all_profile_analyses()
        return jsonify({"analyses": analyses})
    except Exception as e:
        logger.error(f"获取分析结果失败: {e}")
        return jsonify({"analyses": [], "error": str(e)}), 500


@bp.route("/api/profile/analysis/<analysis_type>", methods=["GET"])
def get_analysis(analysis_type):
    """获取特定类型的 AI 自我认知分析结果"""
    try:
        from db import get_profile_analysis
        result = get_profile_analysis(analysis_type)
        if not result:
            return jsonify({"analysis": None})
        return jsonify({"analysis": result})
    except Exception as e:
        logger.error(f"获取分析结果失败: {e}")
        return jsonify({"analysis": None, "error": str(e)}), 500


@bp.route("/api/profile/analysis/trigger", methods=["POST"])
def trigger_analysis():
    """触发自我认知分析（优先 AI，失败回退规则），结果写入缓存表。

    分析类型：mbti_inference, jungian_functions, big_five, cognitive_style
    基于近 7 天活动聚合；AI 分析会把上一次结论作为上下文，形成累积理解。
    """
    import json
    from datetime import date as _date, timedelta
    from db import (
        get_activities, _flush_pending_commits, upsert_profile_analysis,
        get_profile_analysis,
    )
    import config

    data = request.get_json(force=True) if request.is_json else {}
    # 默认计算所有4种类型，也可指定单个
    target_types = data.get("types", ["mbti_inference", "jungian_functions", "big_five", "cognitive_style"])
    if isinstance(target_types, str):
        target_types = [target_types]

    try:
        _flush_pending_commits()

        # 获取近7天活动数据（更大数据量=更准确推断）
        today = _date.today()
        start = (today - timedelta(days=7)).isoformat()
        end = today.isoformat()
        activities = get_activities(start, end)

        if not activities:
            return jsonify({"ok": False, "error": "没有足够的数据进行分析", "results": {}})

        # 转为 dict 列表
        act_dicts = []
        for a in activities:
            act_dicts.append({
                "category": a.get("category", ""),
                "app_name": a.get("app_name", ""),
                "timestamp": a.get("timestamp", ""),
            })

        # 构造给 AI 的紧凑数据摘要：分类时长 / 应用 / 时段分布 / 切换次数
        from collections import Counter
        cat_min = Counter()
        app_cnt = Counter()
        hour_cnt = Counter()
        for a in act_dicts:
            cat_min[a["category"] or "其他"] += 1
            if a["app_name"]:
                app_cnt[a["app_name"]] += 1
            ts = a["timestamp"]
            if len(ts) >= 13 and ts[10] == " ":
                try:
                    hour_cnt[int(ts[11:13])] += 1
                except ValueError:
                    pass
        interval_min = config.SCREENSHOT_INTERVAL_SEC / 60
        cat_text = "、".join(
            f"{c}{round(n * interval_min)}分钟" for c, n in cat_min.most_common(8)
        )
        app_text = "、".join(f"{k}({n}次)" for k, n in app_cnt.most_common(8))
        hour_text = "、".join(f"{h}点({n}次)" for h, n in sorted(hour_cnt.items()))
        switch_count = sum(
            1 for i in range(1, len(act_dicts))
            if act_dicts[i]["category"] != act_dicts[i - 1]["category"]
        )
        data_summary = (
            f"活动总数：{len(act_dicts)} 条（近7天，每条约 {interval_min:g} 分钟）\n"
            f"分类分布：{cat_text or '无'}\n"
            f"常用应用：{app_text or '无'}\n"
            f"时段分布：{hour_text or '无'}\n"
            f"分类切换次数：{switch_count}\n"
        )
        # 叠加任务经历档案：项目跨度/技能广度/协作多样度为性格推断提供语义证据
        try:
            from experience_pipeline import get_experience_context
            exp_ctx = get_experience_context(900)
            if exp_ctx:
                data_summary += "\n" + exp_ctx + "\n"
        except Exception:
            pass

        from deep_insight_engine import (
            compute_mbti_metrics, compute_jungian_metrics,
            compute_big_five_metrics, compute_cognitive_style_metrics,
        )
        from ai_client import analyze_cognition

        interval_sec = config.SCREENSHOT_INTERVAL_SEC
        results = {}

        compute_map = {
            "mbti_inference": compute_mbti_metrics,
            "jungian_functions": compute_jungian_metrics,
            "big_five": compute_big_five_metrics,
            "cognitive_style": compute_cognitive_style_metrics,
        }

        for atype in target_types:
            fn = compute_map.get(atype)
            if not fn:
                continue
            try:
                # ① 优先 AI：带上一次结论作为累积上下文
                prev_row = get_profile_analysis(atype)
                previous = json.dumps(prev_row["result_json"], ensure_ascii=False) if prev_row else ""
                metrics = analyze_cognition(atype, data_summary, previous)
                source = "ai"
                if not metrics:
                    # ② AI 不可用/失败 → 回退规则计算（保证功能不中断）
                    if atype in ("mbti_inference", "jungian_functions", "big_five"):
                        metrics = fn(act_dicts, interval_sec, [])
                    else:
                        metrics = fn(act_dicts, interval_sec)
                    source = "rule"

                # 置信度：AI 给的自报优先，否则按数据量估算
                confidence = metrics.get("confidence", 0.0)
                if not isinstance(confidence, (int, float)):
                    confidence = min(1.0, len(act_dicts) / 200)
                confidence = round(float(confidence), 2)

                # 标注数据来源，便于前端/排查识别 AI vs 规则结果
                metrics["_source"] = source

                # 写入缓存
                upsert_profile_analysis(
                    analysis_type=atype,
                    result_json=metrics,
                    confidence=confidence,
                    data_points=len(act_dicts),
                )
                # 反证闭环：认知结论回写经历档案的性格维度
                try:
                    from experience_pipeline import record_cognition_habit
                    record_cognition_habit(atype, metrics, confidence)
                except Exception:
                    pass

                results[atype] = {
                    "metrics": metrics,
                    "confidence": confidence,
                    "data_points": len(act_dicts),
                    "source": source,
                }
            except Exception as e:
                logger.error(f"分析 {atype} 失败: {e}", exc_info=True)
                results[atype] = {"error": str(e)}

        return jsonify({"ok": True, "results": results})

    except Exception as e:
        logger.error(f"触发分析失败: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500
