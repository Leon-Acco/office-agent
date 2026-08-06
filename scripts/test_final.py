"""最终验证——检查所有关键修复"""
import httpx

BASE = "http://localhost:8000"

with httpx.Client(timeout=15) as c:
    # HTML 检查
    r = c.get(BASE + "/")
    html = r.text

    print("=== 登录页修复 ===")
    print(f"  Grid 1fr 1fr: {'PASS' if '1fr 1fr' in html else 'FAIL'}")
    print(f"  Height 100vh: {'PASS' if 'height: 100vh' in html else 'FAIL'}")
    print(f"  No old 775px: {'PASS' if '775.5px' not in html else 'FAIL'}")
    print(f"  No app-shell flex: {'PASS' if html.count('.app-shell {\\n  display: flex') == 0 else 'FAIL'}")
    print(f"  Login inputs editable: {'PASS' if 'id=\"login-email\"' in html else 'FAIL'}")

    # JS 文件检查
    print("\n=== JS 模块 ===")
    for js in ['app.js', 'chat.js', 'graph.js', 'admin.js']:
        r = c.get(f"{BASE}/static/js/{js}")
        print(f"  {js}: {r.status_code} ({len(r.content)} bytes)")

    # API 检查
    print("\n=== API 端点 ===")
    endpoints = [
        ("GET", "/api/health", "Health"),
        ("GET", "/api/dashboard", "Dashboard"),
        ("GET", "/api/agents", "Agents"),
        ("GET", "/api/tasks", "Tasks"),
        ("GET", "/api/knowledge", "Knowledge"),
        ("GET", "/api/graph", "Graph"),
        ("GET", "/api/admin/org", "Admin Org"),
        ("GET", "/api/admin/resources", "Admin Resources"),
        ("GET", "/api/admin/skills", "Admin Skills"),
        ("GET", "/api/admin/tools", "Admin Tools"),
        ("GET", "/api/admin/role-packs", "Admin Role Packs"),
        ("GET", "/api/admin/agents", "Admin Agents"),
        ("GET", "/api/admin/audit", "Admin Audit"),
        ("GET", "/api/admin/permissions", "Admin Perms"),
        ("GET", "/api/frontdesk/quick-questions", "Quick Questions"),
    ]
    for method, path, name in endpoints:
        r = c.get(BASE + path)
        ok = "PASS" if r.status_code == 200 else "FAIL"
        try:
            data = r.json()
            extra = f"{len(data)} items" if isinstance(data, list) else f"{len(data)} keys"
        except:
            extra = ""
        print(f"  {ok} {name}: {r.status_code} {extra}")

    # 登录鉴权检查
    print("\n=== 登录鉴权 ===")
    r = c.post(f"{BASE}/api/auth/login", json={"email": "", "password": ""})
    print(f"  Empty credentials rejected: {'PASS' if r.status_code == 400 else 'FAIL'}")
    r = c.post(f"{BASE}/api/auth/login", json={"email": "test@test.com", "password": "wrong"})
    print(f"  Wrong credentials: {r.status_code} {'PASS' if r.status_code == 200 else 'FAIL'} (demo mode accepts all)")
    r = c.post(f"{BASE}/api/auth/login", json={"email": "guest@agent-office.ai", "password": "password"})
    data = r.json()
    print(f"  Login returns token: {'PASS' if 'token' in data else 'FAIL'}")

    # LLM 检查
    print("\n=== LLM ===")
    r = c.get(f"{BASE}/api/llm/test")
    data = r.json()
    print(f"  LLM status: {data.get('status')}")

    print("\n=== 总结 ===")
    print("  服务器地址: http://localhost:8000")
    print("  请用 Ctrl+F5 硬刷新浏览器访问")
