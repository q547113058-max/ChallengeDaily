#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ChallengeWorker 主控台（Controller）

部署在主控节点（如 auto）上，通过云端 hub 控制其他所有 worker 节点。
功能：列节点 / 单播下发 / 广播下发 / 等待结果 / 查结果 / 交互菜单。

用法：
  python worker_controller.py list                    列出所有节点
  python worker_controller.py run <target> <command>  下发任务到指定节点
  python worker_controller.py run '*' <command>       广播到所有在线节点
  python worker_controller.py wait <task_id> [秒]     等待并打印结果
  python worker_controller.py result <task_id>        查结果
  python worker_controller.py shell                   进入交互主控台

环境变量：
  WORKER_SERVER   云端地址，默认 http://193.112.246.85
  WORKER_TOKEN    控制 token（不设则读同目录 sync_agent.json）
"""
import os
import sys
import json
import time
import urllib.request

SERVER = os.environ.get("WORKER_SERVER", "http://193.112.246.85").rstrip("/")
HERE = os.path.dirname(os.path.abspath(__file__))


def control_token():
    t = os.environ.get("WORKER_TOKEN", "")
    if t:
        return t
    for p in [os.path.join(HERE, "sync_agent.json"),
              r"D:\project\daily\deploy\sync_agent.json"]:
        try:
            return json.load(open(p, encoding="utf-8")).get("token", "")
        except Exception:
            pass
    return ""


def _req(path, data=None, token_header=None, timeout=30):
    if data is None:
        req = urllib.request.Request(SERVER + path, headers={"User-Agent": "cd-controller/1.0"})
    else:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        h = {"Content-Type": "application/json", "User-Agent": "cd-controller/1.0"}
        if token_header:
            h[token_header] = control_token()
        req = urllib.request.Request(SERVER + path, data=body, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def nodes():
    """返回在线节点 ID 列表。"""
    d = _req("/api/worker/list")
    ws = d.get("workers", [])
    return [w["wid"] for w in ws], ws


def list_nodes():
    d = _req("/api/worker/list")
    from datetime import datetime
    now = datetime.now()
    ws = d.get("workers", [])
    print("\n=== 在线节点 ===")
    online = 0
    for w in ws:
        try:
            age = (now - datetime.fromisoformat(w.get("last_seen", ""))).total_seconds()
            ok = age < 120
        except Exception:
            ok = False
        if ok:
            online += 1
        mark = "ONLINE" if ok else "OFFLINE"
        print("  %-30s %-7s ip=%s last=%s" % (
            w.get("wid"), mark, w.get("ip", ""), str(w.get("last_seen", ""))[:19]))
    print("  合计 %d 个节点，%d 个在线" % (len(ws), online))
    return d


def dispatch(cmd, target="*"):
    r = _req("/api/worker/task", {"cmd": cmd, "target": target}, token_header="X-Worker-Token")
    return r.get("task_id")


def wait_result(task_id, sec=120, quiet=False):
    deadline = time.time() + sec
    while time.time() < deadline:
        r = _req("/api/worker/result?task_id=" + task_id)
        if r.get("status") == "done":
            if not quiet:
                res = r.get("result") or {}
                print("\n任务 %s 完成 (by %s)" % (task_id[:8], r.get("done_by")))
                out = (res.get("stdout") or "").rstrip()
                err = (res.get("stderr") or "").rstrip()
                if out:
                    print("--- stdout ---\n" + out)
                if err:
                    print("--- stderr ---\n" + err)
                print("exit code:", res.get("code"))
            return r
        time.sleep(2)
    if not quiet:
        print("等待超时（%ds），任务可能仍在执行" % sec)
    return None


def broadcast(cmd, wait_sec=0):
    ids, ws = nodes()
    online = [w["wid"] for w in ws]
    print("广播到 %d 个节点: %s" % (len(online), ", ".join(online)))
    tids = {}
    for wid in online:
        tid = dispatch(cmd, wid)
        tids[wid] = tid
        print("  -> %-28s task=%s" % (wid, str(tid)[:8]))
    if wait_sec > 0:
        for wid, tid in tids.items():
            print("\n### %s" % wid)
            wait_result(tid, wait_sec)
    return tids


def shell():
    print("ChallengeWorker 主控台（输入 help 查看命令，exit 退出）")
    while True:
        try:
            line = input("\ncontroller> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        parts = line.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        if cmd in ("exit", "quit"):
            break
        elif cmd == "help":
            print("  list                    列出节点")
            print("  run <target> <cmd>      下发任务（target=节点ID 或 *）")
            print("  broadcast <cmd>         广播给所有在线节点")
            print("  wait <task_id> [秒]     等待结果")
            print("  result <task_id>        查结果")
        elif cmd == "list":
            list_nodes()
        elif cmd == "run":
            sp = arg.split(None, 1)
            if len(sp) < 2:
                print("  用法: run <target> <cmd>")
                continue
            tid = dispatch(sp[1], sp[0])
            print("  task_id:", tid)
            if tid:
                wait_result(tid, 120)
        elif cmd == "broadcast":
            if not arg:
                print("  用法: broadcast <cmd>")
                continue
            broadcast(arg, 120)
        elif cmd in ("wait", "result"):
            sp = arg.split()
            if not sp:
                print("  用法: %s <task_id> [秒]" % cmd)
                continue
            if cmd == "result":
                print(json.dumps(_req("/api/worker/result?task_id=" + sp[0]),
                                 ensure_ascii=False, indent=2))
            else:
                wait_result(sp[0], int(sp[1]) if len(sp) > 1 else 120)
        else:
            print("  未知命令:", cmd)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "shell"
    if cmd == "list":
        list_nodes()
    elif cmd == "run":
        if len(sys.argv) < 4:
            print("用法: worker_controller.py run <target> <command>")
            return
        tid = dispatch(" ".join(sys.argv[3:]), sys.argv[2])
        print("task_id:", tid)
        if tid:
            wait_result(tid)
    elif cmd == "broadcast":
        broadcast(" ".join(sys.argv[2:]), 120)
    elif cmd == "wait":
        wait_result(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 120)
    elif cmd == "result":
        print(json.dumps(_req("/api/worker/result?task_id=" + sys.argv[2]),
                         ensure_ascii=False, indent=2))
    elif cmd == "shell":
        shell()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
