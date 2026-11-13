"""前台管理子进程：Ctrl+C 停止本次启动的服务；生产交给 systemd。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

from service import ROOT, bind_socket, deployment_values, load_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("qa", "kms", "all"), nargs="?", default="all")
    parser.add_argument("--qa-env", default=str(ROOT / ".env"))
    parser.add_argument("--kms-env", default=str(ROOT / ".env.kms"))
    args = parser.parse_args()
    roles = ("qa", "kms") if args.mode == "all" else (args.mode,)
    processes = []
    stopping = False

    def stop_handler(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    try:
        if "kms" in roles:
            deployment_values(args.qa_env, args.kms_env)
        endpoints = []
        for role in roles:
            env = args.qa_env if role == "qa" else args.kms_env
            values = load_values(env)
            port = int(values.get("QA_PORT" if role == "qa" else "KMS_PORT", "6341" if role == "qa" else "6342"))
            host = values.get("QA_HOST" if role == "qa" else "KMS_HOST", "0.0.0.0" if role == "qa" else "127.0.0.1")
            for sock in bind_socket(role, host, port):
                sock.close()
            endpoints.append(f"http://127.0.0.1:{port}/readyz")
        for role in roles:
            env = args.qa_env if role == "qa" else args.kms_env
            cmd = [sys.executable, str(ROOT / "scripts/service.py"), role, "--env", str(Path(env).resolve()), "--qa-env", str(Path(args.qa_env).resolve())]
            processes.append(subprocess.Popen(cmd, cwd=ROOT,
                              creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        pending = set(endpoints)
        deadline = time.monotonic() + 300
        while pending and not stopping:
            if any(p.poll() is not None for p in processes):
                raise RuntimeError("服务在就绪前退出")
            for url in list(pending):
                try:
                    with opener.open(url, timeout=2) as response:
                        if response.status == 200 and json.load(response).get("ready") is True:
                            pending.remove(url)
                except Exception:
                    pass
            if time.monotonic() > deadline:
                raise RuntimeError("HTTP 就绪检查超时；未宣告启动成功")
            time.sleep(1)
        if not stopping:
            print("所选服务 HTTP 就绪。此窗口保持运行；Ctrl+C 停止。模型可用性须另做授权问答验收。", flush=True)
        while not stopping:
            if any(p.poll() is not None for p in processes):
                raise RuntimeError("受管服务已退出，停止同次启动的其他服务")
            time.sleep(1)
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        return 1
    finally:
        for process in processes:
            if process.poll() is None:
                if os.name == "nt":
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    process.terminate()
        for process in processes:
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                print("子进程未在 60 秒内退出；不强杀，请由运维检查。", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
