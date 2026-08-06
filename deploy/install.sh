#!/bin/bash
# ============================================================
# Office_Agent 一键安装脚本（裸机 + systemd）
# 用法：bash deploy/install.sh
# 假设：
#   1. 本项目已完整上传到服务器（git clone 或 scp/rsync）
#   2. 服务器可访问 172.16.8.225（MySQL 30316 / Redis 30689）
#   3. 脚本以 root 或 sudo 权限运行
# 完成后：systemctl status office-agent
# ============================================================
set -euo pipefail

# ── 定位项目根（本脚本在 deploy/ 下）──────────────────────
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="${APP_DIR:-/opt/office-agent}"
VENV_DIR="$APP_DIR/.venv"

echo "==> [1/6] 检查系统依赖（python3>=3.10, git, ensurepip）"
need_install=""
command -v git >/dev/null 2>&1 || need_install="$need_install git"
if command -v python3 >/dev/null 2>&1; then
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
        || { echo "ERROR: python3 版本 $PY_VER 过低，代码使用 3.10+ 语法（str | None）"; exit 1; }
    # Debian/Ubuntu 的 python3 默认不带 ensurepip,venv 会创建失败,需单独的 python3-venv 包
    if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
        if command -v apt-get >/dev/null 2>&1; then
            need_install="$need_install python3-venv"
        else
            echo "ERROR: python3 缺 ensurepip 模块，请手动安装 venv 支持后重跑"; exit 1
        fi
    fi
else
    need_install="$need_install python3"
fi
if [ -n "$need_install" ]; then
    if command -v yum >/dev/null 2>&1; then
        yum install -y $need_install
    elif command -v apt-get >/dev/null 2>&1; then
        apt-get update && apt-get install -y $need_install
    else
        echo "ERROR: 无法自动安装依赖：$need_install，请手动安装后重跑"; exit 1
    fi
fi
echo "    python3: $(python3 --version)  git: $(git --version)"

echo "==> [2/6] 同步项目代码到 $APP_DIR"
if [ "$PROJECT_ROOT" != "$APP_DIR" ]; then
    mkdir -p "$APP_DIR"
    rsync -a --exclude '.venv' --exclude '__pycache__' --exclude 'workspaces' \
          "$PROJECT_ROOT/" "$APP_DIR/" \
        || { echo "    rsync 不可用，改用 cp"; cp -a "$PROJECT_ROOT/." "$APP_DIR/"; }
fi

echo "==> [3/6] 创建 venv 并安装依赖（根 requirements.txt 为权威清单）"
# 以 bin/pip 为准判断 venv 完整性:上次 ensurepip 失败的半成品有 bin/python 无 bin/pip,
# 若按 bin/python 判断会跳过创建后直接调 pip 报错;不完整则清掉重建
if [ ! -x "$VENV_DIR/bin/pip" ]; then
    [ -d "$VENV_DIR" ] && rm -rf "$VENV_DIR"
    python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"
echo "    依赖安装完成"

echo "==> [4/6] 准备环境变量文件"
if [ ! -f "$APP_DIR/deploy/office-agent.env" ]; then
    cp "$APP_DIR/deploy/office-agent.env.example" "$APP_DIR/deploy/office-agent.env"
    chmod 600 "$APP_DIR/deploy/office-agent.env"
    echo "    已生成 $APP_DIR/deploy/office-agent.env（请编辑填入真实密钥）"
else
    echo "    已存在 office-agent.env，跳过（保留现有配置）"
fi

echo "==> [5/6] 注册 systemd 服务"
# 按实际部署路径与工作目录替换 unit 模板中的占位路径
sed "s|/opt/office-agent|$APP_DIR|g" "$APP_DIR/deploy/office-agent.service" \
    > /etc/systemd/system/office-agent.service
systemctl daemon-reload
systemctl enable office-agent
echo "    unit 已写入 /etc/systemd/system/office-agent.service"

echo "==> [6/6] 创建工作区目录"
mkdir -p "$APP_DIR/workspaces"

echo ""
echo "============================================================"
echo "安装完成！后续步骤："
echo "  1. 编辑密钥：vi $APP_DIR/deploy/office-agent.env"
echo "  2. 启动服务：systemctl start office-agent"
echo "  3. 查看日志：journalctl -u office-agent -f"
echo "  4. 健康检查：curl http://127.0.0.1:8000/api/health"
echo "  5. clone 仓库：bash $APP_DIR/deploy/clone_repos.sh"
echo "     （前置：服务器需配置可访问 gitlab.dstcar.com 的 SSH key）"
echo "============================================================"
