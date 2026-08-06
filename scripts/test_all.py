"""全面验证所有 API 端点"""
import httpx
import json

BASE = "http://localhost:8095"

tests = [
    ("Health",        "GET",  "/api/health",              None),
    ("LLM Test",      "GET",  "/api/llm/test",            None),
    ("Dashboard",     "GET",  "/api/dashboard",           None),
    ("Agents",        "GET",  "/api/agents",              None),
    ("Tasks",         "GET",  "/api/tasks",               None),
    ("Knowledge",     "GET",  "/api/knowledge",           None),
    ("Graph",         "GET",  "/api/graph",               None),
    ("Admin Stats",   "GET",  "/api/admin/stats",         None),
    ("Admin Org",     "GET",  "/api/admin/org",           None),
    ("Admin Resources","GET", "/api/admin/resources",     None),
    ("Admin Skills",  "GET",  "/api/admin/skills",        None),
    ("Admin Tools",   "GET",  "/api/admin/tools",         None),
    ("Admin RolePacks","GET", "/api/admin/role-packs",    None),
    ("Admin Agents",  "GET",  "/api/admin/agents",        None),
    ("Admin Audit",   "GET",  "/api/admin/audit",         None),
    ("Admin Perms",   "GET",  "/api/admin/permissions",   None),
    ("Frontdesk QQ",  "GET",  "/api/frontdesk/quick-questions", None),
    ("Frontend",      "GET",  "/",                        None),
    ("JS: app.js",    "GET",  "/static/js/app.js",        None),
    ("JS: chat.js",   "GET",  "/static/js/chat.js",       None),
    ("JS: graph.js",  "GET",  "/static/js/graph.js",      None),
    ("JS: admin.js",  "GET",  "/static/js/admin.js",      None),
]

with httpx.Client(timeout=15) as c:
    for name, method, path, body in tests:
        try:
            if method == "GET":
                r = c.get(BASE + path)
            else:
                r = c.post(BASE + path, json=body)

            status = r.status_code
            ok = "OK" if status == 200 else "FAIL"

            # 特殊处理：获取数据长度
            try:
                data = r.json()
                if isinstance(data, list):
                    extra = f"({len(data)} items)"
                elif isinstance(data, dict):
                    extra = f"({len(data)} keys)"
                else:
                    extra = ""
            except:
                extra = f"({len(r.content)} bytes)"

            print(f"  [{ok}] {name:20s} {method} {path:40s} {status} {extra}")
        except Exception as e:
            print(f"  [ERR] {name:20s} {method} {path:40s} {e}")
