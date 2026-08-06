"""创建基础测试数据（部门 + 领域 + 员工）"""
import requests, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:8000"

print("=== 1. 创建部门 ===")
r = requests.post(f"{BASE}/api/admin/departments",
                   json={"name": "研发部", "emoji": "💻", "description": "负责产品研发"})
print(f"  {r.status_code}: {r.text[:100]}")
dept_id = r.json().get("id", "")

print("\n=== 2. 创建领域 ===")
domains = [
    {"name": "订单域", "description": "订单创建/查询/状态流转"},
    {"name": "支付域", "description": "支付/退款/回调"},
    {"name": "后端域", "description": "后端接口与服务"},
]
domain_ids = {}
for d in domains:
    r = requests.post(f"{BASE}/api/admin/domains",
                       json={"name": d["name"], "department_id": dept_id, "description": d["description"]})
    domain_ids[d["name"]] = r.json().get("id", "")
    print(f"  {d['name']}: {r.status_code}")

print("\n=== 3. 创建员工 ===")
agents = [
    {"name": "林向阳", "title": "订单域研发员工", "emoji": "🧑‍💻", "domain": "订单域",
     "description": "订单创建、查询、状态流转相关接口的发现与调用指导"},
    {"name": "陈雨晴", "title": "支付域研发员工", "emoji": "👩‍💻", "domain": "支付域",
     "description": "支付接口、退款流程、回调处理相关问题"},
    {"name": "赵启明", "title": "后端研发员工", "emoji": "👨‍💻", "domain": "后端域",
     "description": "后端服务接口、数据库操作、缓存策略"},
]
for a in agents:
    r = requests.post(f"{BASE}/api/admin/agents", json={
        "name": a["name"], "title": a["title"], "emoji": a["emoji"],
        "department_id": dept_id, "domain_id": domain_ids[a["domain"]],
        "status": "online", "owner": "admin", "description": a["description"],
    })
    print(f"  {a['name']} ({a['domain']}): {r.status_code}")

print("\n=== 4. 验证 ===")
r = requests.get(f"{BASE}/api/admin/org")
print(f"组织树: {len(r.json())} 个部门")
for dept in r.json():
    print(f"  {dept['emoji']} {dept['name']}: {len(dept.get('domains', []))} 个领域")
r = requests.get(f"{BASE}/api/admin/agents")
print(f"员工数: {len(r.json())}")
for a in r.json():
    print(f"  {a['emoji']} {a['name']} ({a['role']}) - {a['lifecycle']}")

print("\n[OK] 基础数据创建完成")
