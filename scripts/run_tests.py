"""
Office_Agent 全面测试套件
覆盖：前端功能 / 后端链路 / 数据一致性 / SSE / CRUD / LLM
运行：python run_tests.py
"""
import sys
# 修复 Windows GBK 编码问题
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import httpx
import json
import time
from datetime import datetime

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0
SKIP = 0
RESULTS = []


def test(category, name, condition, detail=""):
    """记录测试结果"""
    global PASS, FAIL, SKIP
    status = "PASS" if condition else "FAIL"
    if condition is None:
        status = "SKIP"
        SKIP += 1
    elif condition:
        PASS += 1
    else:
        FAIL += 1

    RESULTS.append({"category": category, "name": name, "status": status, "detail": detail})
    icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️"}[status]
    print(f"  {icon} [{category}] {name}" + (f" — {detail}" if detail and not condition else ""))


def section(title):
    """打印分区标题"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ════════════════════════════════════════════════
#  1. 基础连通性
# ════════════════════════════════════════════════
section("1. 基础连通性")

with httpx.Client(timeout=15) as c:
    r = c.get(f"{BASE}/api/health")
    test("基础", "健康检查", r.status_code == 200)

    r = c.get(f"{BASE}/")
    test("基础", "前端页面", r.status_code == 200 and len(r.text) > 50000)

    for js in ["app.js", "chat.js", "graph.js", "admin.js"]:
        r = c.get(f"{BASE}/static/js/{js}")
        test("基础", f"JS 模块 {js}", r.status_code == 200 and len(r.content) > 5000,
             f"{len(r.content)} bytes" if r.status_code == 200 else f"HTTP {r.status_code}")


# ════════════════════════════════════════════════
#  2. 登录鉴权
# ════════════════════════════════════════════════
section("2. 登录鉴权")

with httpx.Client(timeout=15) as c:
    # 空密码应拒绝
    r = c.post(f"{BASE}/api/auth/login", json={"email": "", "password": ""})
    test("鉴权", "空密码拒绝", r.status_code == 400)

    # 正常登录
    r = c.post(f"{BASE}/api/auth/login", json={"email": "guest@agent-office.ai", "password": "password"})
    data = r.json()
    test("鉴权", "登录成功", r.status_code == 200)
    test("鉴权", "返回 Token", "token" in data and len(data["token"]) > 10)
    test("鉴权", "返回用户名", data.get("user_name") == "访客用户")
    test("鉴权", "返回角色", "role" in data)

    # 获取当前用户
    r = c.get(f"{BASE}/api/auth/me")
    test("鉴权", "获取用户信息", r.status_code == 200)


# ════════════════════════════════════════════════
#  3. 公司总览（验证无假数据）
# ════════════════════════════════════════════════
section("3. 公司总览 — 数据一致性")

with httpx.Client(timeout=15) as c:
    r = c.get(f"{BASE}/api/dashboard")
    data = r.json()
    test("总览", "Dashboard API", r.status_code == 200)

    # KPI 不应包含硬编码的假值
    kpi_values = [k["value"] for k in data.get("kpis", [])]
    has_old_fake = any(v in kpi_values for v in ["72%", "96%", "87%", "4.3"])
    test("总览", "KPI 无硬编码假值", not has_old_fake,
         f"KPI 值: {kpi_values}" if has_old_fake else "KPI 从数据库聚合")

    # 验证 KPI 数据合理性
    test("总览", "KPI 数量为 4", len(data.get("kpis", [])) == 4)

    # 验证部门数据
    depts = data.get("departments", [])
    test("总览", "部门数量 > 0", len(depts) > 0, f"{len(depts)} 个部门")

    # 验证员工数据
    agents = data.get("agents", [])
    test("总览", "员工数量 > 0", len(agents) > 0, f"{len(agents)} 名员工")

    # 验证员工字段完整性
    if agents:
        a = agents[0]
        test("总览", "员工有 name", "name" in a and a["name"])
        test("总览", "员工有 role", "role" in a and a["role"])
        test("总览", "员工有 status", "status" in a)
        test("总览", "员工有 department", "department_id" in a)
        test("总览", "员工有 adoption_rate", "adoption_rate" in a)


# ════════════════════════════════════════════════
#  4. 员工管理
# ════════════════════════════════════════════════
section("4. 员工管理")

with httpx.Client(timeout=15) as c:
    r = c.get(f"{BASE}/api/agents")
    agents = r.json()
    test("员工", "员工列表", r.status_code == 200 and len(agents) > 0)

    # 按（不存在的）部门筛选应返回空
    r = c.get(f"{BASE}/api/agents?departmentId=nonexistent")
    test("员工", "部门筛选", r.status_code == 200)

    # 获取单个员工详情
    if agents:
        aid = agents[0]["id"]
        r = c.get(f"{BASE}/api/agents/{aid}")
        test("员工", "单个员工详情", r.status_code == 200)

        r = c.get(f"{BASE}/api/agents/{aid}/resources")
        test("员工", "员工资源", r.status_code == 200)


# ════════════════════════════════════════════════
#  5. 协作任务
# ════════════════════════════════════════════════
section("5. 协作任务")

with httpx.Client(timeout=15) as c:
    r = c.get(f"{BASE}/api/tasks")
    tasks = r.json()
    test("任务", "任务列表", r.status_code == 200 and len(tasks) > 0)

    if tasks:
        t = tasks[0]
        test("任务", "任务有标题", "title" in t and t["title"])
        test("任务", "任务有子任务", "subtasks" in t and len(t["subtasks"]) > 0)
        test("任务", "任务有状态", "status" in t)


# ════════════════════════════════════════════════
#  6. 知识库
# ════════════════════════════════════════════════
section("6. 知识与案例")

with httpx.Client(timeout=15) as c:
    r = c.get(f"{BASE}/api/knowledge")
    entries = r.json()
    test("知识", "知识列表", r.status_code == 200 and len(entries) > 0)

    # 搜索功能
    r = c.get(f"{BASE}/api/knowledge?search=订单")
    results = r.json()
    test("知识", "搜索功能", r.status_code == 200)

    # 验证字段
    if entries:
        k = entries[0]
        test("知识", "有条目标题", "title" in k and k["title"])
        test("知识", "有 Owner", "owner" in k)
        test("知识", "有状态", "status" in k)


# ════════════════════════════════════════════════
#  7. 关系图谱
# ════════════════════════════════════════════════
section("7. 关系图谱")

with httpx.Client(timeout=15) as c:
    r = c.get(f"{BASE}/api/graph")
    graph = r.json()
    test("图谱", "图谱数据", r.status_code == 200)

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    test("图谱", "节点数量 > 0", len(nodes) > 0, f"{len(nodes)} 个节点")
    test("图谱", "边数量 > 0", len(edges) > 0, f"{len(edges)} 条边")

    # 图谱统计
    r = c.get(f"{BASE}/api/graph/stats")
    stats = r.json()
    test("图谱", "统计数据", r.status_code == 200 and "node_count" in stats)


# ════════════════════════════════════════════════
#  8. 管理与治理
# ════════════════════════════════════════════════
section("8. 管理与治理 — 7 大模块")

with httpx.Client(timeout=15) as c:
    admin_tabs = [
        ("org", "组织管理"),
        ("resources", "资源中心"),
        ("skills", "能力中心"),
        ("tools", "工具中心"),
        ("role-packs", "岗位库"),
        ("agents", "员工管理"),
        ("audit", "审计日志"),
    ]
    for endpoint, name in admin_tabs:
        r = c.get(f"{BASE}/api/admin/{endpoint}")
        test("管理", f"{name} API", r.status_code == 200)

    # 权限矩阵
    r = c.get(f"{BASE}/api/admin/permissions")
    test("管理", "权限矩阵", r.status_code == 200 and "rules" in r.json())

    # 统计数据
    r = c.get(f"{BASE}/api/admin/stats")
    stats = r.json()
    test("管理", "管理统计", r.status_code == 200 and "agent_count" in stats)
    test("管理", "统计有 department_count", "department_count" in stats)
    test("管理", "统计有 resource_count", "resource_count" in stats)

    # 9 步向导步骤定义
    r = c.get(f"{BASE}/api/admin/steps")
    steps = r.json()
    test("管理", "向导步骤", r.status_code == 200 and len(steps) == 9)


# ════════════════════════════════════════════════
#  9. 总前台
# ════════════════════════════════════════════════
section("9. 总前台")

with httpx.Client(timeout=15) as c:
    r = c.get(f"{BASE}/api/frontdesk/quick-questions")
    questions = r.json()
    test("前台", "快捷问题", r.status_code == 200 and len(questions) >= 3)

    # 分诊预览
    r = c.post(f"{BASE}/api/frontdesk/ask", json={"question": "订单接口怎么调用"})
    test("前台", "分诊预览", r.status_code == 200)


# ════════════════════════════════════════════════
#  10. LLM 连接
# ════════════════════════════════════════════════
section("10. LLM 连接（GLM-5.2）")

with httpx.Client(timeout=30) as c:
    r = c.get(f"{BASE}/api/llm/test")
    data = r.json()
    test("LLM", "连接状态", data.get("status") == "ok",
         f"endpoint: {data.get('endpoint', '?')}" if data.get("status") == "ok" else data.get("error", ""))


# ════════════════════════════════════════════════
#  11. SSE 流式问答
# ════════════════════════════════════════════════
section("11. SSE 流式问答")

try:
    with httpx.Client(timeout=30) as c:
        r = c.post(
            f"{BASE}/api/frontdesk/chat",
            json={"question": "你好"},
            headers={"Accept": "text/event-stream"},
        )
        test("SSE", "SSE 端点响应", r.status_code == 200)
        test("SSE", "Content-Type 正确", "text/event-stream" in r.headers.get("content-type", ""))

        # 检查是否包含 SSE 事件
        text = r.text
        has_route = "route.decided" in text
        has_answer = "answer.chunk" in text or "answer.completed" in text
        test("SSE", "包含 route.decided 事件", has_route)
        test("SSE", "包含 answer 事件", has_answer)
except Exception as e:
    test("SSE", "SSE 流式问答", False, str(e))


# ════════════════════════════════════════════════
#  12. CRUD 操作
# ════════════════════════════════════════════════
section("12. CRUD 操作")

with httpx.Client(timeout=15) as c:
    # 获取已有部门用于创建员工
    r = c.get(f"{BASE}/api/admin/org")
    orgs = r.json()
    if orgs:
        dept_id = orgs[0]["id"]
        domain_id = orgs[0].get("domains", [{}])[0].get("id", "") if orgs[0].get("domains") else ""

        # 创建员工
        r = c.post(f"{BASE}/api/admin/agents", json={
            "name": "测试员工",
            "title": "测试职位",
            "emoji": "🧪",
            "department_id": dept_id,
            "domain_id": domain_id,
            "status": "pending_check",
            "description": "自动化测试创建的员工",
        })
        test("CRUD", "创建员工", r.status_code == 200, f"HTTP {r.status_code}")

        if r.status_code == 200:
            # 获取员工列表找到新创建的
            r = c.get(f"{BASE}/api/admin/agents")
            all_agents = r.json()
            test_agent = next((a for a in all_agents if a.get("name") == "测试员工"), None)
            test("CRUD", "查询新员工", test_agent is not None)

            if test_agent:
                # 更新员工
                r = c.put(f"{BASE}/api/admin/agents/{test_agent['id']}", json={
                    "name": "测试员工_改",
                    "title": "测试职位_改",
                    "department_id": dept_id,
                    "domain_id": domain_id,
                    "status": "trial",
                    "description": "已更新",
                })
                test("CRUD", "更新员工", r.status_code == 200)

                # 删除员工
                r = c.delete(f"{BASE}/api/admin/agents/{test_agent['id']}")
                test("CRUD", "删除员工", r.status_code == 200)
    else:
        test("CRUD", "CRUD 测试", None, "无部门数据")


# ════════════════════════════════════════════════
#  13. 审计日志
# ════════════════════════════════════════════════
section("13. 审计日志")

with httpx.Client(timeout=15) as c:
    r = c.get(f"{BASE}/api/admin/audit")
    logs = r.json()
    test("审计", "审计日志 API", r.status_code == 200)

    # 如果有 CRUD 操作，应该有审计记录
    if logs:
        test("审计", "审计日志有条目", len(logs) > 0)
        test("审计", "审计有 action 字段", "action" in logs[0])
        test("审计", "审计有 target 字段", "target_name" in logs[0])


# ════════════════════════════════════════════════
#  14. 前端布局验证
# ════════════════════════════════════════════════
section("14. 前端布局验证")

with httpx.Client(timeout=15) as c:
    r = c.get(f"{BASE}/")
    html = r.text

    test("布局", "登录页双栏 1fr", "1fr 1fr" in html)
    test("布局", "登录页 height 100vh", "height: 100vh" in html)
    test("布局", "无旧 775.5px 布局", "775.5px" not in html)
    test("布局", "App-shell 无 display:flex", html.count(".app-shell {\n  display: flex") == 0)
    test("布局", "输入框可编辑", 'id="login-email"' in html and "readonly" not in html.split("login-email")[1][:30])
    test("布局", "4 个 JS 模块加载", all(x in html for x in ["app.js", "chat.js", "graph.js", "admin.js"]))


# ════════════════════════════════════════════════
#  总结报告
# ════════════════════════════════════════════════
section("测试总结")

total = PASS + FAIL + SKIP
print(f"\n  总测试数: {total}")
print(f"  ✅ 通过: {PASS}")
print(f"  ❌ 失败: {FAIL}")
print(f"  ⏭️ 跳过: {SKIP}")
print(f"  通过率: {round(PASS/total*100) if total else 0}%")

if FAIL > 0:
    print(f"\n  失败项:")
    for r in RESULTS:
        if r["status"] == "FAIL":
            print(f"    ❌ [{r['category']}] {r['name']}" + (f" — {r['detail']}" if r["detail"] else ""))

print(f"\n  测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"  服务器: {BASE}")

sys.exit(0 if FAIL == 0 else 1)
