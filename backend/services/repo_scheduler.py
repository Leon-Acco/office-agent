"""
仓库定时自动刷新调度器(第 7 轮需求:代码仓库定时刷新)

每 60s 轮询一次 repository 表:
- auto_refresh_minutes 为 NULL/0 的仓库跳过(未开启)
- 距上次同步(last_sync_at)不足间隔的跳过
- 到期仓库执行 git pull --ff-only 并更新 last_sync_at

挂在 FastAPI lifespan 上随服务启停(见 main.py)
"""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.database import async_session, now_cn


async def auto_refresh_loop():
    """调度主循环:异常兜底,永不退出"""
    from backend.services import git_service
    from backend.models.governance import Repository

    while True:
        try:
            async with async_session() as db:
                rows = (await db.execute(
                    select(Repository).where(
                        Repository.auto_refresh_minutes.isnot(None),
                        Repository.auto_refresh_minutes > 0,
                    )
                )).scalars().all()

                # MySQL DATETIME 不带时区,统一用东八区 naive 时间比较
                now = now_cn()

                for r in rows:
                    # 未到刷新时间的跳过
                    if r.last_sync_at and now - r.last_sync_at < timedelta(minutes=r.auto_refresh_minutes):
                        continue
                    # 本地目录不存在(未拉取/已删除)的跳过
                    repo_path = git_service.get_repo_path(r.name)
                    if not (repo_path / ".git").exists():
                        continue

                    result = await git_service.pull_repo(r.name)
                    r.last_sync_at = now
                    if result.get("success"):
                        print(f"[repo-scheduler] 仓库 {r.name} 定时拉取成功")
                    else:
                        print(f"[repo-scheduler] 仓库 {r.name} 定时拉取失败: {result.get('error', '')[:120]}")

                await db.commit()
        except asyncio.CancelledError:
            raise  # 服务关停时正常退出
        except Exception as e:
            print(f"[repo-scheduler] 刷新异常: {e}")

        await asyncio.sleep(60)
