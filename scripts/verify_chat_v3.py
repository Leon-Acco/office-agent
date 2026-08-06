"""验证新版聊天界面前后端链路"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import httpx

BASE = "http://localhost:8000"

with httpx.Client(timeout=15) as c:
    # 1. 验证 chat.js 加载
    r = c.get(f"{BASE}/static/js/chat.js")
    chat_js = r.text
    print("=== chat.js 加载 ===")
    print(f"  HTTP: {r.status_code}, 大小: {len(r.content)} bytes")
    print(f"  包含单列居中布局: {'PASS' if '单列居中' in chat_js else 'FAIL'}")
    print(f"  包含会话抽屉: {'PASS' if 'chat-drawer' in chat_js else 'FAIL'}")
    print(f"  无旧版 200px 侧边栏: {'PASS' if 'width:200px' not in chat_js else 'FAIL'}")
    print(f"  包含空状态居中: {'PASS' if '你想问点什么' in chat_js else 'FAIL'}")
    print(f"  包含 SVG 图标: {'PASS' if 'viewBox' in chat_js else 'FAIL'}")

    # 2. 验证前端首页
    r = c.get(f"{BASE}/")
    html = r.text
    print("\n=== 前端首页 ===")
    print(f"  HTTP: {r.status_code}, 大小: {len(r.content)} bytes")
    print(f"  4 个 JS 模块加载: {'PASS' if all(x in html for x in ['app.js', 'chat.js', 'graph.js', 'admin.js']) else 'FAIL'}")

    # 3. 验证快捷问题 API
    r = c.get(f"{BASE}/api/frontdesk/quick-questions")
    questions = r.json()
    print("\n=== 快捷问题 ===")
    print(f"  HTTP: {r.status_code}, 数量: {len(questions)}")
    for q in questions[:3]:
        print(f"    - {q}")

    # 4. 验证 SSE 流式问答
    print("\n=== SSE 流式问答 ===")
    try:
        with httpx.Client(timeout=30) as sc:
            r = sc.post(
                f"{BASE}/api/frontdesk/chat",
                json={"question": "你好"},
                headers={"Accept": "text/event-stream"},
            )
            print(f"  HTTP: {r.status_code}")
            print(f"  Content-Type: {r.headers.get('content-type', '?')}")
            text = r.text
            print(f"  包含 route.decided: {'PASS' if 'route.decided' in text else 'FAIL'}")
            print(f"  包含 answer 事件: {'PASS' if ('answer.chunk' in text or 'answer.completed' in text) else 'FAIL'}")
            # 打印路由结果
            for line in text.split('\n'):
                if 'agent_name' in line and 'data:' in line:
                    print(f"  路由信息: {line.strip()[:120]}")
                    break
    except Exception as e:
        print(f"  FAIL: {e}")

    # 5. 验证 LLM 连通
    print("\n=== LLM 连通 ===")
    r = c.get(f"{BASE}/api/llm/test")
    data = r.json()
    print(f"  status: {data.get('status')}")
    print(f"  endpoint: {data.get('endpoint', '?')}")

print("\n=== 总结 ===")
print("  访问 http://localhost:8000 查看新版总前台")
print("  请用 Ctrl+F5 硬刷新浏览器")
