"""
数据库连接与会话管理
MySQL 8.0 + SQLAlchemy 2.x 异步引擎
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.config import DATABASE_URL

# 异步引擎（pool 参数在引擎层管理）
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,    # 连接前检测存活
    pool_recycle=3600,      # 每小时回收连接
    pool_size=10,           # 连接池大小
    max_overflow=20,        # 最大溢出连接
)

# 异步会话工厂
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类"""
    pass


async def get_db():
    """FastAPI 依赖注入：获取数据库会话"""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def ensure_columns():
    """
    轻量列迁移：检查缺列则 ALTER TABLE ADD COLUMN（幂等，可重复启动）
    项目未启用 alembic，create_all 不会给已有表加列，用此函数兜底
    """
    from sqlalchemy import inspect, text

    # (表名, 列名, ADD COLUMN DDL)
    required = [
        ("agent", "agents_md", "ALTER TABLE agent ADD COLUMN agents_md TEXT NULL"),
        ("agent", "skills", "ALTER TABLE agent ADD COLUMN skills JSON NULL"),
        ("skill", "instructions", "ALTER TABLE skill ADD COLUMN instructions TEXT NULL"),
        ("task_card", "result_doc_path", "ALTER TABLE task_card ADD COLUMN result_doc_path VARCHAR(500) NULL"),
        ("task_assignment", "discussion_note", "ALTER TABLE task_assignment ADD COLUMN discussion_note TEXT NULL"),
        ("repository", "auto_refresh_minutes", "ALTER TABLE repository ADD COLUMN auto_refresh_minutes INT NULL"),
        ("repository", "last_sync_at", "ALTER TABLE repository ADD COLUMN last_sync_at DATETIME NULL"),
    ]
    async with engine.begin() as conn:
        def _check(sync_conn):
            insp = inspect(sync_conn)
            for table, col, ddl in required:
                try:
                    cols = {c["name"] for c in insp.get_columns(table)}
                except Exception:
                    continue  # 表不存在（极端情况）跳过
                if col not in cols:
                    print(f"[migrate] {table} 缺列 {col}，执行: {ddl}")
                    sync_conn.execute(text(ddl))
        await conn.run_sync(_check)


async def init_db():
    """初始化数据库：建表 + 列迁移 + 填充种子数据"""
    # 导入所有模型，确保 Base.metadata 知道它们
    from backend.models import company, agent, session as sess, task, knowledge, evidence  # noqa: F401
    from backend.models import resource  # noqa: F401 — Resource / Skill / Tool / AuditLog
    from backend.models import governance  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 已有表的轻量列迁移（幂等）
    await ensure_columns()

    # 填充种子数据
    from backend.db_seed import run_seed
    await run_seed()
