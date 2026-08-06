"""验证服务器返回的 HTML 是否包含修复"""
import httpx

r = httpx.get("http://localhost:8000/")
html = r.text

checks = {
    "grid 1fr 1fr": "1fr 1fr" in html,
    "height 100vh": "height: 100vh" in html,
    "no 775.5px": "775.5px" not in html,
    "app-shell no display:flex": html.count(".app-shell {\n  display: flex") == 0,
    "has app.js": "/static/js/app.js" in html,
    "has chat.js": "/static/js/chat.js" in html,
    "has graph.js": "/static/js/graph.js" in html,
    "has admin.js": "/static/js/admin.js" in html,
    "has login-email id": 'id="login-email"' in html,
    "no readonly on email": 'readonly' not in html.split('id="login-email"')[1][:50] if 'id="login-email"' in html else True,
    "has Enter handler": "event.key==='Enter'" in html,
}

print(f"HTML size: {len(html)} bytes")
for k, v in checks.items():
    print(f"  {'PASS' if v else 'FAIL'} {k}")
