# scripts/ —— 运维与验证脚本

从项目根目录归档而来的一次性/周期性脚本。**均在项目根目录下执行**(`python scripts/xxx.py`)。

## 数据初始化(直连数据库)

| 脚本 | 用途 |
|---|---|
| `_init_iov_team.py` | 车联网团队一键初始化:清业务表 → 重建公司/部门/6 领域 → 7 名员工 → 登记 git 仓库 → 员工-仓库绑定(幂等,可重跑) |
| `_seed_knowledge.py` | 为车联网团队种子 6 条已发布知识(每个职能领域一条) |
| `_export_repo_urls.py` | 导出 workspaces 下所有 git 仓的 origin 地址(供生成服务器 clone 脚本) |

## API 冒烟测试(打 HTTP 接口,需服务已启动)

| 脚本 | 用途 |
|---|---|
| `run_tests.py` | 全面测试套件:前端/后端链路/数据一致性/SSE/CRUD/LLM(localhost:8000) |
| `test_all.py` | 全 API 端点验证(localhost:8095) |
| `test_final.py` / `test_verify.py` / `verify_chat_v3.py` | 历轮功能验证脚本 |
| `test_html.py` / `test_sse.py` | 前端页面 / SSE 流式专项验证 |
| `_setup_data.py` | 通过 API 创建基础测试数据(部门+领域+员工) |
