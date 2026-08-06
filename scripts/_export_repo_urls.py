# -*- coding: utf-8 -*-
"""导出 workspaces 下所有 git 仓的 origin 完整地址（供生成服务器 clone 脚本）"""
import subprocess, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 脚本位于 scripts/ 下,workspaces 在上一级(项目根)
ws = Path(__file__).resolve().parent.parent / "workspaces"
for d in sorted(ws.iterdir()):
    if not d.is_dir() or not (d / ".git").exists():
        continue
    r = subprocess.run(["git", "-C", str(d), "config", "--get", "remote.origin.url"],
                       capture_output=True, text=True, timeout=10)
    url = r.stdout.strip() if r.returncode == 0 else ""
    # 默认分支
    b = subprocess.run(["git", "-C", str(d), "rev-parse", "--abbrev-ref", "HEAD"],
                       capture_output=True, text=True, timeout=10)
    branch = b.stdout.strip() if b.returncode == 0 else ""
    print(f"{d.name}\t{url or '(无 origin)'}\t{branch}")
