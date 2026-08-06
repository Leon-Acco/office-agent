"""
仓库登记协调服务
解决「本地 workspaces 有目录、repository 表无记录」的断链问题：
手工 git clone / 脚本导入的仓库不在 DB 中，导致员工编辑弹窗的绑定列表看不到、
AgentRepoBinding 无法建立，表现为「新加的仓库 Agent 没有生效」。

用法：在仓库列表类接口返回前调用 sync_workspace_repos(db) 做增量登记。
"""
import subprocess
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.governance import Repository
from backend.services import git_service


def _read_remote_url(repo_dir) -> str:
    """尽力读取本地仓库的 origin 地址（非 git 目录或读取失败返回空串）"""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


async def sync_workspace_repos(db: AsyncSession) -> list[str]:
    """
    把 workspaces 下存在但 repository 表缺失的本地目录登记入库
    返回新登记的目录名列表（已提交 flush，由调用方决定 commit 时机）
    同时清理「目录存在但不是 git 仓库」的脏登记行(如 collab_docs/uploads,
    历史遗留:早版本登记时未校验 .git),避免列表出现拉取/分支必失败的假仓库
    """
    root = git_service.WORKSPACE_ROOT
    if not root.exists():
        return []

    rows = (await db.execute(select(Repository))).scalars().all()
    existing = {r.name for r in rows}

    # 清理脏行:本地目录在但缺 .git(普通目录被误登记)
    pruned = 0
    for r in rows:
        d = root / r.name
        if d.is_dir() and not (d / ".git").exists():
            await db.delete(r)
            existing.discard(r.name)
            pruned += 1
    if pruned:
        await db.flush()
        print(f"[repo-registry] 清理 {pruned} 个非 git 脏登记")

    registered = []
    for d in sorted(root.iterdir()):
        # 只登记真正的 git 仓库，跳过 collab_docs/uploads/agents 等普通目录
        if not d.is_dir() or d.name in existing or not (d / ".git").exists():
            continue
        db.add(Repository(
            id=uuid.uuid4().hex,
            name=d.name,  # 目录名即检索用的 repo_id
            provider="git",
            clone_url=_read_remote_url(d),
            default_branch="main",
            state="READY",
            owner="local",
        ))
        registered.append(d.name)
    if registered:
        await db.flush()
    return registered
