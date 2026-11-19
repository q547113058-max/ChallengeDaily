# -*- coding: utf-8 -*-
"""
activity_sync —— 把采集端的结构化活动记录上传到服务端，供多设备时间线合并。

设计：
- 只上传结构化文字（时间/应用/活动/任务/项目/证据/置信度/idle 标记），**不传截图**
- 后台批量：攒够 BATCH 条或每 FLUSH_SEC 秒发一次，避免每条一次 HTTP
- 失败只记日志、不阻断本地 append_record（本地 activity.jsonl 始终是完整副本）
- 客户端按 (tenant, client_id, ts) 幂等，重启后重发不会重复
- 纯本地模式（未配 TODO_SYNC_URL）自动禁用

环境变量：
  TODO_SYNC_URL / TODO_SYNC_TOKEN   与 todo_sync.py / presence.py 共用
  TODO_ACTIVITY_BATCH               批量条数，默认 5
  TODO_ACTIVITY_FLUSH               最长缓冲秒数，默认 30
"""
import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request

URL = os.environ.get("TODO_SYNC_URL", "").strip().rstrip("/")
TOKEN = os.environ.get("TODO_SYNC_TOKEN", "").strip()
TIMEOUT = float(os.environ.get("TODO_SYNC_TIMEOUT", "8") or "8")
BATCH = int(os.environ.get("TODO_ACTIVITY_BATCH", "5") or "5")
FLUSH_SEC = int(os.environ.get("TODO_ACTIVITY_FLUSH", "30") or "30")

_q = queue.Queue(maxsize=500)
_started = False
_client_id = ""
_host = ""
_stats = {"sent": 0, "failed": 0, "dropped": 0}


def enabled() -> bool:
    return bool(URL)


def start(client_id: str, host: str, log=print):
    """启动后台上传线程。重复调用无副作用。"""
    global _started, _client_id, _host
    if _started or not enabled():
        return
    _client_id = client_id
    _host = host
    _started = True

    def _send_batch(items):
        payload = {"client_id": _client_id, "host": _host, "activities": items}
        req = urllib.request.Request(
            URL + "/api/activities",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"X-Todo-Token": TOKEN,
                     "Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))

    def loop():
        buf = []
        last = time.monotonic()
        while True:
            wait = max(0.1, FLUSH_SEC - (time.monotonic() - last))
            try:
                item = _q.get(timeout=wait)
                if item is None:  # stop 哨兵
                    if buf:
                        _flush(buf, _send_batch, log)
                    return
                buf.append(item)
            except queue.Empty:
                pass
            if buf and (len(buf) >= BATCH or (time.monotonic() - last) >= FLUSH_SEC):
                _flush(buf, _send_batch, log)
                buf = []
                last = time.monotonic()

    def _flush(items, sender, logf):
        try:
            r = sender(items)
            _stats["sent"] += len(items)
            if not r.get("ok"):
                _stats["failed"] += len(items)
                logf(f"[activity-sync] 服务端返回异常: {str(r)[:100]}")
        except Exception as e:
            _stats["failed"] += len(items)
            logf(f"[activity-sync] 上传失败（本地记录不受影响）: {str(e)[:120]}")

    t = threading.Thread(target=loop, daemon=True, name="activity-sync")
    t.start()
    log(f"[activity-sync] 已启动 client_id={client_id} host={host} "
        f"batch={BATCH} flush={FLUSH_SEC}s")


def upload(rec: dict):
    """提交一条活动记录（非阻塞）。未启用/队列满时静默丢弃，不影响采集。"""
    if not (_started and enabled()):
        return
    try:
        _q.put_nowait(dict(rec))
    except queue.Full:
        _stats["dropped"] += 1


def stats() -> dict:
    return dict(_stats)


def stop():
    """优雅停止（尽力 flush 缓冲）。"""
    if _started:
        try:
            _q.put_nowait(None)
        except queue.Full:
            pass
