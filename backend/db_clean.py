"""
清空所有业务数据（保留表结构）
用于从零开始逐模块测试
"""
import asyncio
from sqlalchemy import text
from backend.database import engine

# 按外键依赖顺序（先删子表再删父表）
TABLES_TO_CLEAN = [
    "message",
    "session",
    "task_assignment",
    "task_card",
    "knowledge_candidate",
    "agent_repo_binding",
    "agent",
    "role_pack_version",
    "role_pack",
    "change_approval",
    "change_request",
    "policy_rule",
    "gov_role",
    "repository",
    "tool",
    "skill",
    "resource",
    "domain",
    "department",
    "company",
    "audit_log",
    "evidence",
]


async def clean_all():
    """清空所有业务表数据"""
    async with engine.begin() as conn:
        # 临时禁用外键检查
        await conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))

        total_deleted = 0
        for table in TABLES_TO_CLEAN:
            result = await conn.execute(text(f"DELETE FROM `{table}`"))
            count = result.rowcount
            if count > 0:
                print(f"  [DELETE] {table}: {count} 行")
                total_deleted += count

        # 重新启用外键检查
        await conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

        print(f"\n共删除 {total_deleted} 行数据")
        print("所有业务表已清空（表结构保留）")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    asyncio.run(clean_all())
