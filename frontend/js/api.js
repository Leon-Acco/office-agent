/**
 * Office_Agent 前端 API 连接模块
 * 封装所有后端 API 调用
 */
const API_BASE = 'http://localhost:8000/api';

async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`API ${path} 返回 ${res.status}`);
  return res.json();
}

async function apiPost(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API POST ${path} 返回 ${res.status}`);
  return res.json();
}

/* ─── 各模块 API ─────────────────────────────── */

// 仪表盘
export async function fetchDashboard() { return apiGet('/dashboard'); }
export async function fetchAgentSummary() { return apiGet('/agents/summary'); }

// 员工
export async function fetchAgents(deptId) {
  const q = deptId ? `?departmentId=${deptId}` : '';
  return apiGet(`/agents${q}`);
}
export async function fetchAgentDetail(id) { return apiGet(`/agents/${id}`); }

// 总前台
export async function askQuestion(text) { return apiPost('/frontdesk/ask', { question: text }); }
export async function fetchQuickQuestions() { return apiGet('/frontdesk/quick-questions'); }

// 知识库
export async function fetchKnowledge(params) {
  const q = new URLSearchParams(params || {}).toString();
  return apiGet(`/knowledge?${q}`);
}

// 协作任务
export async function fetchTasks(status) {
  const q = status ? `?status=${status}` : '';
  return apiGet(`/tasks${q}`);
}

// 关系图谱
export async function fetchGraph() { return apiGet('/graph'); }
export async function fetchGraphStats() { return apiGet('/graph/stats'); }

// 管理后台
export async function fetchAdminAgents() { return apiGet('/admin/agents'); }
export async function fetchAdminStats() { return apiGet('/admin/stats'); }
export async function fetchAdminSteps() { return apiGet('/admin/steps'); }

// 登录
export async function login(email, password) {
  return apiPost('/auth/login', { email, password });
}
