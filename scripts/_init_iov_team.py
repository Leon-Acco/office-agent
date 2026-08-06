# -*- coding: utf-8 -*-
"""
车联网团队一键初始化脚本
1. 清空全部业务表（保留表结构）
2. 重建 公司/部门/6 领域
3. 创建 7 名员工（status=online，agents_md 从 workspaces/agents/*.md 读取注入）
4. 登记 workspaces 下所有 git 仓库
5. 建立员工-仓库绑定（张朝/彭云林/肖何/吴志宇）
6. 重登记上传文档资源（新车联网平台接口对接指引）
"""
import asyncio
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 脚本位于 scripts/ 下,把项目根目录加入 path 才能 import backend
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text, select
from backend.database import engine, async_session
from backend.db_clean import TABLES_TO_CLEAN
from backend.models.company import Company, Department, Domain
from backend.models.agent import Agent
from backend.models.governance import Repository, AgentRepoBinding
from backend.models.resource import Resource

# 脚本位于 scripts/ 下,项目根目录为上一级
ROOT = Path(__file__).resolve().parent.parent
WORKSPACES = ROOT / "workspaces"
AGENTS_MD_DIR = WORKSPACES / "agents"

# ── 7 名员工定义 ─────────────────────────────────────────
EMPLOYEES = [
    {"name": "王杰", "title": "产品经理", "emoji": "🧑‍💼", "domain": "产品域",
     "desc": "车联网平台产品负责人：需求分析、PRD 与产品文档维护、功能边界与优先级、验收标准定义。"},
    {"name": "张朝", "title": "后端开发工程师", "emoji": "🧑‍💻", "domain": "后端域",
     "desc": "后端开发（控制/影子方向）：dst-iot-shadow-service 设备影子、dst-iot-control-service 指令控制的接口答疑、链路排查与表结构说明。"},
    {"name": "彭云林", "title": "后端开发工程师", "emoji": "👨‍💻", "domain": "后端域",
     "desc": "后端开发（32960/网关方向）：GB/T 32960 国标数据接入、平台网关转发、T-Box 协议解析的接口答疑与链路排查。"},
    {"name": "肖何", "title": "架构师", "emoji": "🧑‍🚀", "domain": "架构域",
     "desc": "团队技术架构负责人：整体技术蓝图、跨系统链路设计、架构评审、技术选型与演进路线，视野覆盖全部仓库。"},
    {"name": "陈学位", "title": "团队领导", "emoji": "🧑‍✈️", "domain": "管理域",
     "desc": "车联网团队负责人：目标与排期、任务分派、跨团队协调、团队流程制度，全局视角兜底答疑。"},
    {"name": "许露", "title": "测试工程师", "emoji": "👩‍🔬", "domain": "测试域",
     "desc": "测试工程师：测试计划、用例设计（含 32960 报文级用例）、接口验证与缺陷跟进，交付质量把关。"},
    {"name": "吴志宇", "title": "前端工程师", "emoji": "🧑‍🎨", "domain": "前端域",
     "desc": "前端工程师：iov.dstcar.com 平台前端开发，页面组件、portalApi 联调（加签/环境切换）、前端问题排查。"},
]

# ── 员工-仓库绑定（按记忆 agent-binding-routing-design 落地明细）──
BINDINGS = {
    "张朝": ["dst-iot-control-service", "dst-iot-shadow-service"],
    "彭云林": ["dst-iot-32960-gateway-service", "dst-iot-32960-platform-gateway-service", "dst-iot-protocol-tbox"],
    "吴志宇": ["iov.dstcar.com"],
    "肖何": ["*"],  # 架构师绑定全部仓库
}

DEPT_NAME = "车联网部"
COMPANY_NAME = "车联网团队"
DOMAINS = {
    "产品域": "需求分析、PRD、验收标准",
    "后端域": "后端服务、接口、数据库、32960/影子/控车/V2X",
    "架构域": "架构设计、技术选型、跨系统链路",
    "前端域": "iov 平台前端、页面、可视化",
    "测试域": "测试计划、用例、缺陷、验收",
    "管理域": "排期、进度、资源协调、团队流程",
}

UPLOADED_DOC = {
    "id": "6d0fb5407f67",
    "name": "新车联网平台接口对接指引",
    "type": "document",
    "icon": "📄",
    "description": "新车联网平台对外接口对接指引：网关环境地址（测试/生产/预生产 portalApi）、appkey/secretId 授权码申请、DstSignatureUtil.sign4Gateway 加签说明。",
    "url": "/api/admin/resources/6d0fb5407f67/md",
    "status": "ready",
    "owner": "张朝",
}


def _git_origin(repo_dir: Path) -> str:
    """读取仓库 origin 地址，失败返回空串"""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


async def init_team():
    # ── Step 1: 清库 ──
    print("=" * 50)
    print("Step 1: 清空全部业务表")
    async with engine.begin() as conn:
        await conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in TABLES_TO_CLEAN:
            await conn.execute(text(f"DELETE FROM `{table}`"))
        await conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    print("  已清空")

    async with async_session() as db:
        # ── Step 2: 公司/部门/领域 ──
        print("\nStep 2: 重建组织架构")
        company = Company(name=COMPANY_NAME, description="车联网团队（IoV）：设备接入（T-Box/GB/T 32960）、设备影子、指令控制、V2X 业务与 iov 平台。")
        db.add(company)
        await db.flush()
        dept = Department(company_id=company.id, name=DEPT_NAME, emoji="🚗", description="车联网部：覆盖产品、架构、后端、前端、测试、管理六个职能领域。")
        db.add(dept)
        await db.flush()
        domain_map = {}
        for dname, ddesc in DOMAINS.items():
            d = Domain(department_id=dept.id, name=dname, description=ddesc)
            db.add(d)
            domain_map[dname] = d
        await db.flush()
        print(f"  公司={company.name} 部门={dept.name} 领域={list(DOMAINS)}")

        # ── Step 3: 7 名员工 ──
        print("\nStep 3: 创建 7 名员工")
        agent_map = {}
        for emp in EMPLOYEES:
            md_file = AGENTS_MD_DIR / f"{emp['name']}.md"
            agents_md = md_file.read_text(encoding="utf-8") if md_file.exists() else ""
            if not agents_md:
                print(f"  ⚠️ 未找到 agent.md: {md_file}")
            elif len(agents_md) > 3900:
                print(f"  ⚠️ {emp['name']} 的 agents_md 超 3900 字符（{len(agents_md)}），注入时会被 4000 截断")
            agent = Agent(
                name=emp["name"],
                title=emp["title"],
                emoji=emp["emoji"],
                department_id=dept.id,
                domain_id=domain_map[emp["domain"]].id,
                status="online",
                owner="张朝",
                description=emp["desc"],
                tags=[DEPT_NAME, emp["domain"]],
                agents_md=agents_md,
                skills=[],
            )
            db.add(agent)
            agent_map[emp["name"]] = agent
            print(f"  ✅ {emp['emoji']} {emp['name']}（{emp['title']}·{emp['domain']}，agents_md {len(agents_md)} 字符）")
        await db.flush()

        # ── Step 4: 登记 git 仓库 ──
        print("\nStep 4: 登记 workspaces 下的 git 仓库")
        repo_map = {}
        for child in sorted(WORKSPACES.iterdir()):
            if not child.is_dir() or not (child / ".git").exists():
                continue
            origin = _git_origin(child)
            repo = Repository(
                name=child.name,
                provider="git",
                clone_url=origin,
                default_branch="main",
                state="READY",
                owner="local",
            )
            db.add(repo)
            repo_map[child.name] = repo
            print(f"  📦 {child.name}  origin={'(无)' if not origin else origin[:80]}")
        await db.flush()
        print(f"  共登记 {len(repo_map)} 个仓库")

        # ── Step 5: 员工-仓库绑定 ──
        print("\nStep 5: 建立员工-仓库绑定")
        for emp_name, repo_names in BINDINGS.items():
            agent = agent_map.get(emp_name)
            if not agent:
                continue
            targets = list(repo_map.values()) if repo_names == ["*"] else [
                repo_map[n] for n in repo_names if n in repo_map
            ]
            missing = [n for n in repo_names if n != "*" and n not in repo_map]
            for repo in targets:
                db.add(AgentRepoBinding(agent_id=agent.id, repo_id=repo.id))
            print(f"  🔗 {emp_name} ← {len(targets)} 个仓库" + (f"（⚠️ 未找到: {missing}）" if missing else ""))

        # ── Step 6: 重登记上传文档资源 ──
        print("\nStep 6: 重登记上传文档资源")
        md_path = WORKSPACES / "uploads" / f"{UPLOADED_DOC['id']}.md"
        if md_path.exists():
            db.add(Resource(**UPLOADED_DOC))
            print(f"  📄 {UPLOADED_DOC['name']}（{UPLOADED_DOC['id']}）")
        else:
            print(f"  ⚠️ 文档文件不存在，跳过: {md_path}")

        await db.commit()

    # ── 验证输出 ──
    print("\n" + "=" * 50)
    async with async_session() as db:
        agents = (await db.execute(select(Agent).order_by(Agent.created_at))).scalars().all()
        bindings = (await db.execute(select(AgentRepoBinding))).scalars().all()
        repos = (await db.execute(select(Repository))).scalars().all()
        resources = (await db.execute(select(Resource))).scalars().all()
        print(f"验证: 员工={len(agents)} 仓库={len(repos)} 绑定={len(bindings)} 资源={len(resources)}")
        for a in agents:
            nb = sum(1 for b in bindings if b.agent_id == a.id)
            print(f"  {a.emoji} {a.name} | {a.title} | status={a.status} | 绑仓={nb} | md={len(a.agents_md or '')}字符")


if __name__ == "__main__":
    asyncio.run(init_team())
