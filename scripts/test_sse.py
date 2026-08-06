"""测试 SSE 问答端点"""
import httpx

resp = httpx.post(
    "http://localhost:8094/api/frontdesk/chat",
    json={"question": "订单接口幂等怎么处理"},
    timeout=30,
)
print(f"Status: {resp.status_code}")
print(f"Content-Type: {resp.headers.get('content-type')}")
lines = resp.text.split("\n")
for line in lines[:30]:
    print(line)
