#!/bin/bash
# ============================================================
# 车联网团队 15 个代码仓库批量 clone 脚本
# 用法：bash deploy/clone_repos.sh [workspaces目录]
# 默认 clone 到 <项目根>/workspaces/
#
# 前置条件（必须手动完成）：
#   服务器 SSH key 已添加到 gitlab.dstcar.com 账户：
#     ssh-keygen -t ed25519 -C "office-agent-server"
#     cat ~/.ssh/id_ed25519.pub   # 粘贴到 GitLab -> Preferences -> SSH Keys
#     ssh -T git@gitlab.dstcar.com   # 验证连通（首次需 yes 信任指纹）
#
# 数据清单来源：本地开发机各仓 remote.origin.url + 当前分支（2026-08 导出）
# 注意：以下 2 个目录在本地无 origin，无法自动 clone，需手动 scp 上传：
#   - business adas
#   - dst-iot-da
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
WS_ROOT="${1:-${WORKSPACE_ROOT:-$PROJECT_ROOT/workspaces}}"

mkdir -p "$WS_ROOT"
cd "$WS_ROOT"

# 格式：目录名|origin URL|分支
REPOS=(
"dst-iot-32960-gateway-service|git@gitlab.dstcar.com:FlyBees/vds/Device-connectivity-management-platform/migrate-to-szidc/dst-iot-32960-gateway-service.git|prod"
"dst-iot-32960-platform-gateway-service|git@gitlab.dstcar.com:FlyBees/vds/Device-connectivity-management-platform/migrate-to-szidc/dst-iot-32960-platform-gateway-service.git|prod"
"dst-iot-adas-gateway-service|git@gitlab.dstcar.com:FlyBees/vds/Device-connectivity-management-platform/migrate-to-szidc/dst-iot-adas-gateway-service.git|prod"
"dst-iot-control-service|git@gitlab.dstcar.com:FlyBees/vds/Device-connectivity-management-platform/migrate-to-szidc/dst-iot-control-service.git|prod"
"dst-iot-protocol-adas|git@gitlab.dstcar.com:FlyBees/vds/Device-connectivity-management-platform/migrate-to-szidc/dst-iot-protocol-adas.git|prod"
"dst-iot-protocol-tbox|git@gitlab.dstcar.com:FlyBees/vds/Device-connectivity-management-platform/migrate-to-szidc/dst-iot-protocol-tbox.git|v1.0.0"
"dst-iot-shadow-service|git@gitlab.dstcar.com:FlyBees/vds/Device-connectivity-management-platform/migrate-to-szidc/dst-iot-shadow-service.git|prod"
"dst-v2x-api-service|git@gitlab.dstcar.com:FlyBees/vds/iot-device-ecosystem-management-platform/dst-v2x-api-service.git|prod"
"dst-v2x-business-adas-service|git@gitlab.dstcar.com:FlyBees/vds/iot-device-ecosystem-management-platform/dst-v2x-business-adas-service.git|prod"
"dst-v2x-business-service|git@gitlab.dstcar.com:FlyBees/vds/iot-device-ecosystem-management-platform/dst-v2x-business-service.git|prod"
"dst-v2x-export-service|git@gitlab.dstcar.com:FlyBees/vds/iot-device-ecosystem-management-platform/dst-v2x-export-service.git|prod"
"dst-v2x-gateway|git@gitlab.dstcar.com:FlyBees/vds/iot-device-ecosystem-management-platform/dst-v2x-gateway.git|prod"
"dst-v2x-lock-service|git@gitlab.dstcar.com:FlyBees/vds/iot-device-ecosystem-management-platform/dst-v2x-lock-service.git|prod"
"dst-v2x-manager-service|git@gitlab.dstcar.com:FlyBees/vds/iot-device-ecosystem-management-platform/dst-v2x-manager-service.git|prod"
"iov.dstcar.com|git@gitlab.dstcar.com:FlyBees/vds/iot-device-ecosystem-management-platform/iov.dstcar.com.git|prod"
)

ok=0; skip=0; fail=0
for entry in "${REPOS[@]}"; do
    name="${entry%%|*}"
    rest="${entry#*|}"
    url="${rest%%|*}"
    branch="${rest#*|}"

    if [ -d "$name/.git" ]; then
        echo "[跳过] $name 已存在（如需更新请手动 git pull）"
        skip=$((skip+1)); continue
    fi

    echo "[clone] $name (分支 $branch)"
    if git clone --branch "$branch" --single-branch "$url" "$name" >/dev/null 2>&1; then
        ok=$((ok+1))
    else
        echo "  !! clone 失败：$name（检查 SSH key 与 GitLab 权限）"
        rm -rf "$name"  # 清理 clone 失败的残留目录
        fail=$((fail+1))
    fi
done

echo ""
echo "============================================================"
echo "完成：成功 $ok，跳过 $skip，失败 $fail"
echo ""
echo "⚠ 以下 2 个目录无远程 origin，请从开发机手动 scp 上传："
echo "    business adas/"
echo "    dst-iot-da/"
echo "  例：scp -r 'D:\\code\\my_workspace_python\\Office_Agent\\workspaces\\business adas' root@<服务器>:$WS_ROOT/"
echo "============================================================"
[ "$fail" -eq 0 ]
