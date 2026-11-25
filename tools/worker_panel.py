#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ChallengeWorker 图形面板 —— 远程工作节点客户端。

界面：
  - 顶部：云端地址 / 节点 ID / 连接状态指示灯
  - 中部：任务日志（滚动）
  - 底部：启动/停止 按钮、开机自启勾选、清空日志

单文件打包：PyInstaller --onefile --noconsole --name ChallengeWorker
依赖：仅 Python 标准库（tkinter + urllib + subprocess）
"""
import os
import sys
import json
import time
import uuid
import socket
import threading
import subprocess
import queue
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

try:
    from urllib.request import Request, build_opener, ProxyHandler
    from urllib.error import HTTPError, URLError
except ImportError:
    from urllib2 import Request, build_opener, ProxyHandler, HTTPError, URLError

EXE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
CONFIG_FILE = os.path.join(EXE_DIR, "worker_config.json")
OPENER = build_opener(ProxyHandler({}))  # 绕过失效系统代理

DEFAULT_CFG = {
    "server": "http://193.112.246.85",
    "worker_id": "",
    "workdir": "",
    "poll_interval": 2,
    "timeout": 300,
    "auto_start": True,
}

# 配色
C_BG = "#1e1e2e"
C_CARD = "#252538"
C_TEXT = "#e4e4e7"
C_DIM = "#8b8b9a"
C_GREEN = "#22c55e"
C_RED = "#ef4444"
C_YELLOW = "#eab308"
C_ACCENT = "#8b5cf6"


def gen_worker_id():
    return "%s-%012x" % (socket.gethostname(), uuid.getnode())


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    if not cfg.get("worker_id"):
        cfg["worker_id"] = gen_worker_id()
        save_cfg(cfg)
    return cfg


def save_cfg(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class WorkerPanel:
    def __init__(self, root):
        self.root = root
        self.cfg = load_cfg()
        self.running = False
        self.worker_thread = None
        self.stop_event = threading.Event()
        self.log_queue = queue.Queue()
        self.task_count = 0

        self._build_ui()
        self._pump_logs()
        # 自动启动：配置 auto_start 为真时（开机自启场景）直接开始工作，
        # 无需用户手动点「启动节点」。
        if self.cfg.get("auto_start"):
            self.root.after(600, self.start)

    # ─── UI ───────────────────────────────────────────
    def _build_ui(self):
        self.root.title("ChallengeWorker — 远程工作节点")
        self.root.geometry("640x560")
        self.root.minsize(560, 460)
        self.root.configure(bg=C_BG)

        # ── 顶部配置卡 ──
        top = tk.Frame(self.root, bg=C_CARD, padx=16, pady=14)
        top.pack(fill="x", padx=12, pady=(12, 8))

        tk.Label(top, text="云端地址", bg=C_CARD, fg=C_DIM,
                 font=("Microsoft YaHei UI", 9)).grid(row=0, column=0, sticky="w")
        self.var_server = tk.StringVar(value=self.cfg["server"])
        e1 = tk.Entry(top, textvariable=self.var_server, bg=C_BG, fg=C_TEXT,
                      insertbackground=C_TEXT, relief="flat", font=("Consolas", 10))
        e1.grid(row=1, column=0, columnspan=3, sticky="we", pady=(2, 10), ipady=5)

        tk.Label(top, text="节点 ID", bg=C_CARD, fg=C_DIM,
                 font=("Microsoft YaHei UI", 9)).grid(row=2, column=0, sticky="w")
        self.var_id = tk.StringVar(value=self.cfg["worker_id"])
        e2 = tk.Entry(top, textvariable=self.var_id, bg=C_BG, fg=C_TEXT,
                      insertbackground=C_TEXT, relief="flat", font=("Consolas", 10))
        e2.grid(row=3, column=0, columnspan=3, sticky="we", pady=(2, 0), ipady=5)

        top.columnconfigure(0, weight=1)

        # ── 状态栏 ──
        st = tk.Frame(self.root, bg=C_BG)
        st.pack(fill="x", padx=12, pady=(0, 8))

        self.dot = tk.Canvas(st, width=12, height=12, bg=C_BG, highlightthickness=0)
        self.dot.pack(side="left", padx=(4, 6))
        self.dot_id = self.dot.create_oval(2, 2, 11, 11, fill=C_DIM, outline="")

        self.lbl_status = tk.Label(st, text="未启动", bg=C_BG, fg=C_DIM,
                                   font=("Microsoft YaHei UI", 10, "bold"))
        self.lbl_status.pack(side="left")

        self.lbl_stat = tk.Label(st, text="", bg=C_BG, fg=C_DIM,
                                 font=("Microsoft YaHei UI", 9))
        self.lbl_stat.pack(side="right")

        # ── 日志区 ──
        wrap = tk.Frame(self.root, bg=C_CARD)
        wrap.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        tk.Label(wrap, text="运行日志", bg=C_CARD, fg=C_DIM,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=12, pady=(10, 4))

        self.log = scrolledtext.ScrolledText(
            wrap, bg=C_BG, fg=C_TEXT, insertbackground=C_TEXT, relief="flat",
            font=("Consolas", 9), wrap="word", state="disabled", padx=10, pady=8)
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log.tag_configure("ok", foreground=C_GREEN)
        self.log.tag_configure("err", foreground=C_RED)
        self.log.tag_configure("warn", foreground=C_YELLOW)
        self.log.tag_configure("dim", foreground=C_DIM)

        # ── 底部按钮 ──
        bot = tk.Frame(self.root, bg=C_BG)
        bot.pack(fill="x", padx=12, pady=(0, 14))

        self.btn_toggle = tk.Button(
            bot, text="启动节点", command=self.toggle,
            bg=C_GREEN, fg="#0b1a10", relief="flat", cursor="hand2",
            font=("Microsoft YaHei UI", 10, "bold"), padx=22, pady=8,
            activebackground="#16a34a", activeforeground="#0b1a10", bd=0)
        self.btn_toggle.pack(side="left")

        self.btn_clear = tk.Button(
            bot, text="清空日志", command=self.clear_log,
            bg=C_CARD, fg=C_TEXT, relief="flat", cursor="hand2",
            font=("Microsoft YaHei UI", 9), padx=14, pady=8,
            activebackground="#33334a", activeforeground=C_TEXT, bd=0)
        self.btn_clear.pack(side="left", padx=(10, 0))

        self.var_save = tk.BooleanVar(value=True)
        tk.Checkbutton(bot, text="保存配置", variable=self.var_save,
                       bg=C_BG, fg=C_DIM, selectcolor=C_CARD,
                       activebackground=C_BG, activeforeground=C_TEXT,
                       font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(14, 0))

        self.btn_auto = tk.Button(
            bot, text="开机自启", command=self.toggle_autostart,
            bg=C_CARD, fg=C_TEXT, relief="flat", cursor="hand2",
            font=("Microsoft YaHei UI", 9), padx=12, pady=8,
            activebackground="#33334a", activeforeground=C_TEXT, bd=0)
        self.btn_auto.pack(side="left", padx=(10, 0))
        self._refresh_autostart_label()

        tk.Label(bot, text="v1.0.1", bg=C_BG, fg="#4b4b5a",
                 font=("Consolas", 8)).pack(side="right")

    # ─── 开机自启 ──────────────────────────────────────
    def _autostart_cmd(self):
        return 'schtasks /Query /TN "ChallengeWorker" >nul 2>&1'

    def _is_autostart_on(self):
        try:
            return subprocess.run(self._autostart_cmd(), shell=True,
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL).returncode == 0
        except Exception:
            return False

    def _refresh_autostart_label(self):
        try:
            on = self._is_autostart_on()
            self.btn_auto.configure(
                text="自启:开" if on else "开机自启",
                bg=C_GREEN if on else C_CARD,
                fg="#0b1a10" if on else C_TEXT)
        except Exception:
            pass

    def toggle_autostart(self):
        exe = os.path.abspath(sys.argv[0])
        if self._is_autostart_on():
            subprocess.run('schtasks /Delete /TN "ChallengeWorker" /F',
                           shell=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            self.log_line("已关闭开机自启", "warn")
        else:
            tr = '"%s"' % exe
            r = subprocess.run(
                'schtasks /Create /TN "ChallengeWorker" /TR %s /SC ONLOGON /RL HIGHEST /F /DELAY 0000:20' % tr,
                shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if r.returncode == 0:
                self.log_line("已开启开机自启（登录后 20 秒自动运行）", "ok")
            else:
                self.log_line("自启设置失败，请用管理员身份运行", "err")
        self._refresh_autostart_label()

    # ─── 日志 ──────────────────────────────────────────
    def log_line(self, msg, tag=None):
        self.log_queue.put((msg, tag))

    def _pump_logs(self):
        try:
            while True:
                msg, tag = self.log_queue.get_nowait()
                self.log.configure(state="normal")
                ts = datetime.now().strftime("%H:%M:%S")
                self.log.insert("end", "[%s] %s\n" % (ts, msg), tag or ())
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(120, self._pump_logs)

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _set_status(self, text, color):
        self.lbl_status.configure(text=text, fg=color)
        self.dot.itemconfigure(self.dot_id, fill=color)

    # ─── 启停 ──────────────────────────────────────────
    def toggle(self):
        if self.running:
            self.stop()
        else:
            self.start()

    def start(self):
        self.cfg["server"] = self.var_server.get().strip().rstrip("/")
        self.cfg["worker_id"] = self.var_id.get().strip()
        if not self.cfg["server"]:
            messagebox.showerror("配置错误", "请填写云端地址")
            return
        if not self.cfg["worker_id"]:
            self.cfg["worker_id"] = gen_worker_id()
            self.var_id.set(self.cfg["worker_id"])
        if self.var_save.get():
            save_cfg(self.cfg)

        self.stop_event.clear()
        self.running = True
        self.btn_toggle.configure(text="停止节点", bg=C_RED,
                                  activebackground="#dc2626", fg="#fff5f5")
        self._set_status("连接中…", C_YELLOW)

        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def stop(self):
        self.stop_event.set()
        self.running = False
        self.btn_toggle.configure(text="启动节点", bg=C_GREEN,
                                  activebackground="#16a34a", fg="#0b1a10")
        self._set_status("已停止", C_DIM)
        self.log_line("节点已停止", "warn")

    # ─── 网络 ──────────────────────────────────────────
    def _api(self, path, data=None, timeout=40):
        url = self.cfg["server"] + path
        if data is None:
            req = Request(url, headers={"User-Agent": "cd-worker/1.0"})
        else:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            req = Request(url, data=body, headers={
                "Content-Type": "application/json", "User-Agent": "cd-worker/1.0"})
        with OPENER.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def _run_cmd(self, cmd, workdir, timeout):
        try:
            p = subprocess.run(cmd, shell=True, cwd=workdir or None,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=timeout)
            return {"stdout": p.stdout.decode("utf-8", "replace")[-20000:],
                    "stderr": p.stderr.decode("utf-8", "replace")[-20000:],
                    "code": p.returncode}
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": "TIMEOUT after %ss" % timeout, "code": -1}
        except Exception as e:
            return {"stdout": "", "stderr": repr(e), "code": -2}

    def _worker_loop(self):
        wid = self.cfg["worker_id"]
        workdir = self.cfg.get("workdir") or EXE_DIR
        poll = max(1, int(self.cfg.get("poll_interval", 2)))
        timeout = int(self.cfg.get("timeout", 300))

        # 注册
        try:
            self._api("/api/worker/register", {"worker_id": wid})
            self.log_line("已注册节点: " + wid, "ok")
            self._set_status("在线 · 等待任务", C_GREEN)
        except Exception as e:
            self.log_line("注册失败: " + str(e)[:120], "err")
            self._set_status("注册失败", C_RED)

        while not self.stop_event.is_set():
            try:
                resp = self._api("/api/worker/poll?worker_id=" + wid, timeout=35)
                task = resp.get("task")
                if not task:
                    self._set_status("在线 · 等待任务", C_GREEN)
                    time.sleep(poll)
                    continue

                tid = task.get("tid", "")
                cmd = task.get("cmd", "")
                self.task_count += 1
                self.log_line("收到任务 #%d: %s" % (self.task_count, cmd), "warn")

                # 关键：命令放到独立线程执行，绝不阻塞 poll 循环。
                # 否则长命令（如启动常驻服务）会占住心跳，节点被判离线。
                threading.Thread(
                    target=self._exec_task,
                    args=(tid, wid, cmd, workdir, int(task.get("timeout") or timeout)),
                    daemon=True).start()
            except Exception as e:
                if self.stop_event.is_set():
                    break
                msg = str(e)
                self.log_line("连接异常: " + msg[:120], "dim")
                self._set_status("连接中断，重试中…", C_RED)
                time.sleep(max(3, poll))

    def _exec_task(self, tid, wid, cmd, workdir, timeout):
        """在独立线程里执行任务并回传，不阻塞 poll 心跳循环。"""
        try:
            self._set_status("执行中…", C_YELLOW)
            result = self._run_cmd(cmd, workdir, timeout)
            self._api("/api/worker/result", {
                "task_id": tid, "worker_id": wid,
                "result": result, "ok": result.get("code") == 0,
            })
            out = (result.get("stdout") or "").strip()
            if out:
                for line in out.splitlines()[:8]:
                    self.log_line("  │ " + line[:200])
            if result.get("code") == 0:
                self.log_line("  └ 完成 (exit 0)", "ok")
            else:
                self.log_line("  └ 结束 (exit %s)" % result.get("code"), "err")
                err = (result.get("stderr") or "").strip()
                if err:
                    for line in err.splitlines()[:4]:
                        self.log_line("  ! " + line[:200], "err")
            self.lbl_stat.configure(text="已完成 %d 个任务" % self.task_count)
            self._set_status("在线 · 等待任务", C_GREEN)
        except Exception as e:
            self.log_line("任务执行异常: " + str(e)[:120], "err")
            self._set_status("在线 · 等待任务", C_GREEN)


def main():
    root = tk.Tk()
    try:
        root.iconbitmap(default="")
    except Exception:
        pass
    WorkerPanel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
