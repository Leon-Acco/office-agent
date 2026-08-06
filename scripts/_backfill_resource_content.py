# -*- coding: utf-8 -*-
"""
回填资源正文到 DB(resource.content)
背景:共享 MySQL + 各机本地盘架构下,上传文档解析出的 .md 文件只存在于上传时那台机器的
workspaces/uploads/ 目录。resource.content 列上线前的历史资源 content 为空,
需要在「持有 md 文件的那台机器」上执行本脚本完成回填,回填后任意机器可读。

用法(在持有 workspaces/uploads/*.md 文件的机器上,项目根目录执行):
    python -X utf8 scripts/_backfill_resource_content.py
幂等:只回填 content 为空的资源,可重复执行。
"""
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from backend.database import async_session, engine
# 显式导入全部模型模块,避免 relationship 字符串解析失败(KeyError: 'Domain')
from backend.models import company, agent, governance, resource, session as m_session  # noqa: F401
from backend.models.resource import Resource
from backend.services import file_service


async def main():
    async with async_session() as db:
        rows = (await db.execute(select(Resource))).scalars().all()
        filled, skipped, missing = 0, 0, 0
        for r in rows:
            if r.content:
                skipped += 1
                continue
            if not (r.url or "").endswith("/md"):
                skipped += 1
                continue
            md = file_service.read_upload_md(r.id)
            if md:
                r.content = md
                filled += 1
                print(f"[fill] {r.name} <- 本机 md 文件({len(md)} 字)")
            else:
                missing += 1
                print(f"[miss] {r.name}: 本机无 md 文件,需在持有文件的机器上执行")
        await db.commit()
        print(f"[DONE] 回填 {filled} 条,已有内容跳过 {skipped} 条,本机缺文件 {missing} 条")
    await engine.dispose()


asyncio.run(main())
