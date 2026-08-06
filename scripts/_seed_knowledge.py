"""一次性脚本:为车联网团队种子 6 条已发布知识(每个职能领域一条)"""
import asyncio
import sys
from pathlib import Path

# 脚本位于 scripts/ 下,把项目根目录加入 path 才能 import backend
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from backend.database import async_session
import backend.models.agent, backend.models.company, backend.models.knowledge
import backend.models.resource, backend.models.session, backend.models.task, backend.models.governance
from backend.models.knowledge import KnowledgeCandidate

# (领域, 作者, 图标, 标题, 正文)
ITEMS = [
    ("产品域", "王杰", "📋", "车机 App 需求评审 Checklist",
     "## 评审要点\n\n- 用户故事必须包含车载场景(行驶中/驻车)的状态说明\n- 交互稿需标注语音与触控双通道的降级策略\n- 涉及车辆控制的需求必须附安全合规确认\n- 验收标准量化到可测试指标(响应时长、成功率)"),
    ("架构域", "肖何", "🏛️", "车联网平台高可用架构设计原则",
     "## 核心原则\n\n- TSP 平台与车端通信链路双通道冗余(MQTT + HTTP 兜底)\n- 轨迹数据写多读少,按时间分片 + 冷热分层存储\n- 所有外部依赖(TSP、地图服务)必须有熔断与降级开关\n- 核心链路可用性目标 99.95%,跨机房容灾 RPO < 1min"),
    ("后端域", "张朝", "⚙️", "车辆轨迹数据批量写入优化实践",
     "## 实践结论\n\n- 批量插入每批 500~1000 条,配合异步队列削峰\n- 经纬度索引使用空间索引,范围查询先框后算\n- 轨迹补传接口必须幂等(按 vin + timestamp 去重)\n- 实测写入吞吐从 3k/s 提升到 18k/s"),
    ("前端域", "吴志宇", "🖥️", "监控大屏地图组件选型与接入指南",
     "## 选型结论\n\n- 大屏主地图选用 Mapbox GL,万级车辆点位用聚合图层\n- 轨迹回放采用抽稀播放(1s 粒度),避免全量点位卡顿\n- 深色主题下地图样式需单独配置,避免默认亮色刺眼\n- 组件封装见前端仓库 components/VehicleMap"),
    ("测试域", "许露", "🧪", "V2X 消息一致性测试用例设计规范",
     "## 用例设计要点\n\n- 覆盖消息丢失、乱序、重复、延迟四大异常场景\n- 车端模拟器与真实 T-Box 双环境各跑一轮\n- 断言以最终一致性为准,允许 3s 内的状态收敛窗口\n- 性能用例单独归档,不混入功能回归集"),
    ("管理域", "陈学位", "📅", "版本列车排期与发布节奏约定",
     "## 节奏约定\n\n- 每两周一个版本列车,周三封版、周四预发、下周二正式发布\n- 错过当班列车的需求默认顺延,紧急需求走特批流程\n- 封版后只允许合入缺陷修复,且需测试负责人确认\n- 发布日当天值班:后端 + 前端 + 测试各一人"),
]


async def main():
    async with async_session() as db:
        existing = (await db.execute(select(KnowledgeCandidate))).scalars().all()
        if existing:
            print(f"已有 {len(existing)} 条知识,跳过种子")
            return
        for domain, owner, icon, title, body in ITEMS:
            db.add(KnowledgeCandidate(
                title=title,
                domain=domain,
                department="车联网团队",
                icon=icon,
                status="published",      # 旧字段:看板统计依据
                state="APPROVED",        # 新状态机:审核通过才参与共享检索
                owner=owner,
                confidence="HIGH",
                published_at="2026-08-04",
                scope="DEPARTMENT",
                body_md=body,
                reviewed_by="陈学位",
            ))
        await db.commit()
        print(f"已插入 {len(ITEMS)} 条已发布知识")


asyncio.run(main())
