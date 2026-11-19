"""任务经历档案增量提炼调度：启动后延迟跑一次，之后每 10 分钟。"""
import logging
import threading

logger = logging.getLogger(__name__)
_stop = threading.Event()
_thread = None
_INTERVAL_SEC = 10 * 60


def _loop():
    if _stop.wait(30):  # 启动 30 秒后首次，避开初始化高峰
        return
    while not _stop.is_set():
        try:
            from experience_pipeline import run_once
            stats = run_once(force=False)
            if stats.get("scanned"):
                logger.info(f"经历档案增量: 扫描{stats['scanned']} 会话{stats['sessions']} "
                            f"AI{stats['ai']} 规则{stats['rule']}")
        except Exception as e:
            logger.warning(f"经历档案提炼失败(非致命): {e}")
        if _stop.wait(_INTERVAL_SEC):
            break


def init_experience_scheduler():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="ExperiencePipeline")
    _thread.start()
    logger.info("任务经历档案调度已启动（每 10 分钟）")


def stop_experience_scheduler():
    _stop.set()
