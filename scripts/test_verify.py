"""验证全部修复"""
import httpx

BASE = "http://localhost:8096"

with httpx.Client(timeout=15) as c:
    # 1. 登录鉴权
    r = c.post(f"{BASE}/api/auth/login", json={"email":"", "password":""})
    print(f"  [空密码] {r.status_code} -> {'OK' if r.status_code == 400 else 'BUG'}")

    r = c.post(f"{BASE}/api/auth/login", json={"email":"guest@agent-office.ai","password":"password"})
    data = r.json()
    print(f"  [登录] {r.status_code} token={'yes' if 'token' in data else 'no'}")

    # 2. 前端
    r = c.get(BASE + "/")
    html = r.text
    print(f"  [Frontend] {r.status_code} {len(html)} bytes")
    has_grid = "1fr 1fr" in html
    has_js = all(x in html for x in ["app.js", "chat.js", "graph.js", "admin.js"])
    no_flex = "display: flex" not in html.split(".app-shell")[1][:50] if ".app-shell" in html else True
    print(f"  [Grid 1fr] {has_grid}")
    print(f"  [JS modules] {has_js}")
    print(f"  [No display:flex in app-shell] {no_flex}")

    # 3. API endpoints
    r = c.get(f"{BASE}/api/frontdesk/quick-questions")
    print(f"  [Quick Q] {r.status_code} {len(r.json())} items")

    for tab in ["org", "resources", "skills", "tools", "role-packs", "agents", "audit"]:
        r = c.get(f"{BASE}/api/admin/{tab}")
        data = r.json()
        cnt = len(data) if isinstance(data, list) else 0
        print(f"  [Admin {tab}] {r.status_code} {cnt} items")

    # 4. Agent CRUD
    r = c.post(f"{BASE}/api/admin/agents", json={
        "name": "test", "title": "test", "department_id": "x", "domain_id": "x"
    })
    print(f"  [Create Agent] {r.status_code}")

    # 5. LLM
    r = c.get(f"{BASE}/api/llm/test")
    data = r.json()
    print(f"  [LLM] {data.get('status')}")
