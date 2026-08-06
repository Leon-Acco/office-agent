#!/usr/bin/env python3
"""
Office Agent 启动脚本
功能：
1. 自动杀掉占用端口 8000 的旧进程
2. 固定端口启动（不换端口）
3. 启动前环境自检
4. 启动后自动验证
"""
import os
import sys
import time
import signal
import subprocess
import requests

PORT = 8000
HOST = "0.0.0.0"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def log(msg, level="INFO"):
    colors = {"INFO": "\033[36m", "OK": "\033[32m", "WARN": "\033[33m", "ERROR": "\033[31m"}
    reset = "\033[0m"
    print(f"{colors.get(level, '')}{'='*50}{reset}")
    print(f"{colors.get(level, '')}[{level}] {msg}{reset}")

def kill_port(port):
    """杀掉占用指定端口的进程"""
    log(f"检查端口 {port} 占用情况...")
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.split("\n"):
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        pid = parts[-1]
                        log(f"发现旧进程 PID={pid}，正在终止...", "WARN")
                        subprocess.run(["taskkill", "//F", "//PID", pid],
                                       capture_output=True, timeout=5)
                        time.sleep(1)
        else:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, timeout=5
            )
            pids = result.stdout.strip().split("\n")
            for pid in pids:
                if pid:
                    log(f"发现旧进程 PID={pid}，正在终止...", "WARN")
                    os.kill(int(pid), signal.SIGTERM)
                    time.sleep(1)
    except Exception as e:
        log(f"端口清理异常（可忽略）: {e}", "WARN")

def check_environment():
    """启动前环境自检"""
    log("环境自检...")

    # 1. Python 版本
    py_ver = sys.version_info
    log(f"Python {py_ver.major}.{py_ver.minor}.{py_ver.micro}")
    if py_ver < (3, 10):
        log("需要 Python 3.10+", "ERROR")
        return False

    # 2. 检查必要依赖
    try:
        import fastapi, uvicorn, sqlalchemy, aiomysql
        log("依赖检查通过")
    except ImportError as e:
        log(f"缺少依赖: {e}", "ERROR")
        return False

    # 3. 检查 Git
    try:
        result = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
        log(f"Git: {result.stdout.strip()}")
    except FileNotFoundError:
        log("Git 未安装（代码仓库功能不可用）", "WARN")

    # 4. 检查 workspaces 目录
    ws = os.path.join(BASE_DIR, "workspaces")
    os.makedirs(ws, exist_ok=True)
    log(f"Workspaces: {ws}")

    # 5. 检查 uploads 目录
    up = os.path.join(BASE_DIR, "uploads")
    os.makedirs(up, exist_ok=True)
    log(f"Uploads: {up}")

    return True

def verify_startup():
    """启动后验证"""
    log("等待服务启动...")
    for i in range(15):
        try:
            r = requests.get(f"http://127.0.0.1:{PORT}/api/health", timeout=2)
            if r.status_code == 200:
                log(f"服务启动成功！ http://127.0.0.1:{PORT}", "OK")

                # 验证关键端点
                endpoints = [
                    ("/api/dashboard", "仪表盘"),
                    ("/api/agents", "员工"),
                    ("/api/admin/org", "组织管理"),
                    ("/api/repos/env", "仓库环境"),
                ]
                for path, name in endpoints:
                    try:
                        r = requests.get(f"http://127.0.0.1:{PORT}{path}", timeout=3)
                        status = "OK" if r.status_code < 400 else f"FAIL({r.status_code})"
                        log(f"  {name}: {status}")
                    except Exception as e:
                        log(f"  {name}: ERROR - {e}", "WARN")

                return True
        except Exception:
            time.sleep(1)

    log("服务启动超时！", "ERROR")
    return False

def main():
    log("Office Agent 启动脚本", "INFO")
    print()

    # 1. 杀掉旧进程
    kill_port(PORT)

    # 2. 环境自检
    if not check_environment():
        log("环境检查失败，退出", "ERROR")
        sys.exit(1)

    # 3. 启动服务
    log(f"启动服务 {HOST}:{PORT}...")
    os.chdir(BASE_DIR)

    # 使用 subprocess 启动 uvicorn(日志统一落 logs/,保持根目录整洁)
    os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", HOST, "--port", str(PORT)],
        stdout=open(os.path.join(BASE_DIR, "logs", "server.log"), "w"),
        stderr=subprocess.STDOUT,
    )

    # 4. 验证启动
    if verify_startup():
        log(f"PID={proc.pid}，服务运行中", "OK")
        log("按 Ctrl+C 停止服务")
        try:
            proc.wait()
        except KeyboardInterrupt:
            log("正在停止服务...", "WARN")
            proc.terminate()
            log("服务已停止", "OK")
    else:
        log("服务启动失败，查看 logs/server.log 获取详情", "ERROR")
        proc.terminate()
        sys.exit(1)

if __name__ == "__main__":
    main()
