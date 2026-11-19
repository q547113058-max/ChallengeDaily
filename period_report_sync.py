"""周报/月报自动落库同步（供云端只读节点读取完整报告）。

背景：云端只读节点没有 AI，无法生成完整报告；本机 Windows 后端才有 AI 能力。
同步器（deploy/sync_agent.py）已把 reports 表推送到云端，因此只要本机把
周报/月报写进 reports 表（键 WEEK:<周一> / MONTH:<YYYY-MM>），云端
/api/report/weekly|monthly 就能读到完整报告；否则回退到云端数据摘要。

本模块在后端启动时后台跑一次，之后每 6 小时刷新一次，保证：
- 用户不必先在本机点「一键生成」，云端也能看到完整周报/月报
- 数据更新后（新增活动）报告会在几小时内刷新

生成的是「基础正文」（report.py 的 generate_weekly_report / generate_monthly_report），
不含 routes/reports.py 里的 AI 增强段落；用户手动点生成时会用增强版覆盖同一键。
"""
import logging
import threading
from datetime import date, timedelta

logger = logging.getLogger(__name__)

_REFRESH_INTERVAL_SEC = 6 * 3600
_stop = threading.Event()
_thread = None


def _week_monday() -> str:
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()


def _exists(key: str) -> bool:
    """该周期的 reports 键是否已有内容（避免后台基础版覆盖用户手动生成的 AI 增强版）。"""
    try:
        from db import get_conn
        with get_conn() as conn:
            r = conn.execute(
                "SELECT 1 FROM reports WHERE report_date=? AND content IS NOT NULL AND content<>''",
                (key,),
            ).fetchone()
        return r is not None
    except Exception:
        return False


def _generate_and_save():
    """生成并落库本周周报、本月月报。已存在完整版则跳过，失败只记日志。"""
    try:
        from report import generate_weekly_report, generate_monthly_report
        from db import save_report
        monday = _week_monday()
        ym = date.today().strftime("%Y-%m")
        wk, mk = f"WEEK:{monday}", f"MONTH:{ym}"
        try:
            if _exists(wk):
                logger.info(f"周报已存在，跳过自动落库: {wk}")
            else:
                w = generate_weekly_report(monday)
                if w:
                    save_report(wk, w)
                    logger.info(f"周报自动落库: {wk} ({len(w)} 字符)")
        except Exception as e:
            logger.warning(f"周报自动生成失败(非致命): {e}")
        try:
            if _exists(mk):
                logger.info(f"月报已存在，跳过自动落库: {mk}")
            else:
                m = generate_monthly_report(ym)
                if m:
                    save_report(mk, m)
                    logger.info(f"月报自动落库: {mk} ({len(m)} 字符)")
        except Exception as e:
            logger.warning(f"月报自动生成失败(非致命): {e}")
    except Exception as e:
        logger.warning(f"周期性报告同步初始化失败(非致命): {e}")


def _loop():
    # 启动时延迟 20 秒，避开后端初始化高峰（DB 迁移、采集器启动）
    if _stop.wait(20):
        return
    while not _stop.is_set():
        _generate_and_save()
        if _stop.wait(_REFRESH_INTERVAL_SEC):
            break


def init_period_report_sync():
    """启动周报/月报自动落库线程（幂等）。"""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="PeriodReportSync")
    _thread.start()
    logger.info("周报/月报自动落库同步已启动（每 6 小时）")


def stop_period_report_sync():
    _stop.set()
