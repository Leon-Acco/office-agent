/**
 * Office_Agent 前端 API 集成层
 * 负责从后端获取数据并动态渲染页面内容
 */

// ====== API 基础配置 ======
const API_BASE = '';  // 同源请求，无需指定 base URL

async function fetchJSON(url) {
  const res = await fetch(API_BASE + url);
  if (!res.ok) throw new Error(`API ${url} 返回 ${res.status}`);
  return res.json();
}

// ====== 状态映射 ======
const STATUS_MAP = {
  available: { label: '可用', class: 'available' },
  indexing: { label: '索引中', class: 'indexing' },
  restricted: { label: '受限', class: 'restricted' },
  maintenance: { label: '维护中', class: 'maintenance' },
};

const LIFECYCLE_MAP = {
  online: { label: '已上线', class: 'online' },
  indexing: { label: '索引中', class: 'indexing' },
  trial: { label: '试运行', class: 'trial' },
  pending_check: { label: '待校验', class: 'pending-check' },
};

const KNOWLEDGE_STATUS_MAP = {
  published: { label: '已发布', class: 'published' },
  expired: { label: '已过期', class: 'expired' },
  pending: { label: '待审核', class: 'pending' },
};

const TASK_STATUS_MAP = {
  in_progress: { label: '进行中', class: 'progress' },
  completed: { label: '已汇总', class: 'done' },
};

const SUBTASK_STATUS_MAP = {
  submitted: { label: '已提交', class: 'submitted' },
  analyzing: { label: '分析中', class: 'analyzing' },
  discussing: { label: '讨论中', class: 'analyzing' },
  discussed: { label: '已互评', class: 'submitted' },
  clarify: { label: '需澄清', class: 'clarify' },
};

// ====== 数据缓存 ======
let _cache = {};

/**
 * 并行加载所有页面数据。
 * 单个 API 失败时降级为空数组/对象，不影响其他页面渲染。
 */
async function loadData() {
  const results = await Promise.allSettled([
    fetchJSON('/api/dashboard'),
    fetchJSON('/api/agents'),
    fetchJSON('/api/tasks'),
    fetchJSON('/api/knowledge'),
    fetchJSON('/api/graph'),
    fetchJSON('/api/admin/agents'),
  ]);

  const [dashboard, agentsData, tasksData, knowledgeData, graphData, adminData] = results.map(r =>
    r.status === 'fulfilled' ? r.value : null
  );

  // 记录失败情况到控制台，便于排查
  results.forEach((r, i) => {
    if (r.status === 'rejected') {
      console.warn(`[loadData] API ${['dashboard','agents','tasks','knowledge','graph','admin'][i]} 加载失败:`, r.reason);
    }
  });

  _cache = {
    dashboard: dashboard || { kpis: [], daily_stats: [], departments: [], agents: [] },
    agents: agentsData || [],
    tasks: tasksData || [],
    knowledge: knowledgeData || [],
    graph: graphData || { nodes: [], edges: [] },
    adminAgents: adminData || [],
  };

  // 渲染各模块（加保护，单个失败不影响整体）
  try { renderDashboard(); } catch(e) { console.warn('renderDashboard:', e); }
  try { renderEmployees(); } catch(e) { console.warn('renderEmployees:', e); }
  try { renderTasks(); } catch(e) { console.warn('renderTasks:', e); }
  try { renderKnowledge(); } catch(e) { console.warn('renderKnowledge:', e); }
  try { renderGraphStats(); } catch(e) { console.warn('renderGraphStats:', e); }
  try { renderAdminTable(); } catch(e) { console.warn('renderAdminTable:', e); }
}


// ====== 可爱像素风头像（打工人牛马主题） ======
// 16×16 字符地图逐格生成 <rect>,crispEdges 保证像素锐利;
// 按姓名哈希分配牛或马及配色（同人固定形象）,完全离线可用
const COW_STYLES = [
  { bg: '#9d94d9', face: '#fdf6ec', spot: '#8a5a3b', snout: '#f9c6d0' },
  { bg: '#7fa8c9', face: '#ffffff', spot: '#3f3f46', snout: '#fbcfe8' },
  { bg: '#c9a2a8', face: '#fdf0e0', spot: '#b45309', snout: '#f9c6d0' },
];
const HORSE_STYLES = [
  { bg: '#7778c4', coat: '#d98e32', mane: '#5b3a1a' }, // 参考图同款紫底棕马
  { bg: '#6fae94', coat: '#b4763a', mane: '#4a2f16' },
  { bg: '#d9939d', coat: '#e3b778', mane: '#8a5a3b' },
];
// 像素字符 → 颜色（公共:G 眼镜框 / w 眼白 / P 瞳孔 / B 腮红 / e 耳内）
const PIXEL_COMMON = { G: '#26262e', w: '#ffffff', P: '#26262e', B: '#f2a0a0', e: '#f4a7a7' };
// 马:C 毛色 / m 鬃毛 / W 额头条 / Z 鼻口 / N 鼻孔 / O 鼻影
function _horseColors(s) {
  return { ...PIXEL_COMMON, C: s.coat, m: s.mane, W: '#fdf3e3', Z: '#f0d3a8', N: '#9c6742', O: '#7c4a21' };
}
// 牛:C 脸部 / E 耳廓 / S 花斑 / H 牛角 / p 鼻口 / N 鼻孔
function _cowColors(s) {
  return { ...PIXEL_COMMON, C: s.face, E: s.face, S: s.spot, H: '#e7d3b3', p: s.snout, N: '#d16b86' };
}
// 马脸像素地图(戴黑框眼镜的打工人马)
const HORSE_MAP = [
  '..C..........C..',
  '..Ce........eC..',
  '..CCmmmmmmmmCC..',
  '..CmmmWWWWmmmC..',
  '.CCCmmWWWWmmCCC.',
  '.CCCCCWWWWCCCCC.',
  '.CCCCCCWWCCCCCC.',
  '.GGGGGGGGGGGGGG.',
  '.GGwPwGGGGwPwGG.',
  '.GGwPPGGGGPPwGG.',
  '.BGGGGGCCGGGGGB.',
  '.BBCCCZZZZCCCBB.',
  '..CCCZNZZNZCCC..',
  '...CCZZOOZZCC...',
  '....CCZZZZCC....',
  '................',
];
// 牛脸像素地图(花斑奶牛,同款黑框眼镜)
const COW_MAP = [
  '..H..........H..',
  '..HH........HH..',
  'EECC........CCEE',
  'EeeECCCCCCCCEeeE',
  'EECSSSSCCCCCCCEE',
  '.CSSSSSCCCCCCCC.',
  '.CCSSSSCCCCCCCC.',
  '.GGGGGGGGGGGGGG.',
  '.GGwPwGGGGwPwGG.',
  '.GGwPPGGGGPPwGG.',
  '.BGGGGGCCGGGGGB.',
  '.BBCCppppppCCBB.',
  '..CCppNppNppCC..',
  '...CCppppppCC...',
  '....CCppppCC....',
  '................',
];
function _avatarHash(name) {
  let h = 0;
  for (const ch of String(name || '')) h = (h * 31 + ch.codePointAt(0)) >>> 0;
  return h;
}
/**
 * 按 16×16 字符地图生成像素 SVG 片段(逐格 <rect>)
 */
function _pixelSvg(map, colors, bg) {
  let out = `<rect width='16' height='16' fill='${bg}'/>`;
  for (let y = 0; y < map.length; y++) {
    const row = map[y];
    for (let x = 0; x < row.length; x++) {
      const fill = colors[row[x]];
      if (fill) out += `<rect x='${x}' y='${y}' width='1' height='1' fill='${fill}'/>`;
    }
  }
  return out;
}
/**
 * 员工头像：全员统一橘子吉祥物图，按姓名哈希做轻微差异化（色相/饱和度/亮度微调，同人固定）
 * （第 5 轮反馈：废弃像素牛马，但保留上方 _pixelSvg/COW_MAP/HORSE_MAP 备用）
 * @param {string} name 员工姓名（作哈希种子）
 * @param {string} _emoji 兼容旧签名，不再使用
 * @param {number} size 边长 px
 * @param {string} radius 圆角（默认圆形）
 */
function cuteAvatar(name, _emoji, size, radius) {
  const h = _avatarHash(name);
  const hue = (h % 41) - 20;                 // -20° ~ +20° 轻微色相偏移
  const sat = 0.92 + (h % 3) * 0.06;         // 0.92 ~ 1.04 饱和度微调
  const bri = 0.97 + (h % 5) * 0.015;        // 0.97 ~ 1.03 亮度微调
  const r = radius || '50%';
  return `<img src="/static/assets/avatar-orange.png" width="${size}" height="${size}" alt="${name || ''}" role="img"
    style="border-radius:${r};flex-shrink:0;display:block;object-fit:cover;filter:hue-rotate(${hue}deg) saturate(${sat.toFixed(2)}) brightness(${bri.toFixed(3)});">`;
}


// ====== 渲染：公司总览 ======
function renderDashboard() {
  const d = _cache.dashboard;
  if (!d) {
    console.warn('[renderDashboard] dashboard 数据为空');
    return;
  }

  // KPI 卡片
  const kpiGrid = document.getElementById('kpi-grid');
  if (kpiGrid) {
    if (!d.kpis || d.kpis.length === 0) {
      kpiGrid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:32px;color:#747878;">暂无 KPI 数据</div>`;
    } else {
      // 图标由后端 KPI 卡下发(与看板口径一致),兜底 trending_up
      // pastel 图标底色轮换，契合柔和 SaaS 风
      const kpiTints = [
        { bg: 'var(--teal-50)',       fg: 'var(--teal-700)' },
        { bg: 'var(--pastel-blue)',   fg: '#1D4ED8' },
        { bg: 'var(--pastel-pink)',   fg: '#BE185D' },
        { bg: 'var(--pastel-yellow)', fg: '#92400E' },
      ];
      kpiGrid.innerHTML = d.kpis.map((k, i) => {
        const tint = kpiTints[i % kpiTints.length];
        return `
        <div style="background:#fff;padding:24px;border-radius:20px;box-shadow:var(--shadow-soft);transition:all 0.3s;" onmouseover="this.style.boxShadow='0 12px 32px rgba(13,148,136,0.12)'" onmouseout="this.style.boxShadow='var(--shadow-soft)'">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
            <span style="font-size:12px;color:#5F7470;">${k.label || '—'}</span>
            <span style="width:36px;height:36px;border-radius:12px;background:${tint.bg};display:flex;align-items:center;justify-content:center;">
              <span class="material-symbols-outlined" style="font-size:18px;color:${tint.fg};">${k.icon || 'trending_up'}</span>
            </span>
          </div>
          <div style="display:flex;align-items:baseline;gap:8px;">
            <span style="font-family:var(--font-display);font-size:32px;font-weight:700;">${k.value ?? '—'}</span>
            ${k.change ? `<span style="font-size:12px;color:#059669;display:flex;align-items:center;"><span class="material-symbols-outlined" style="font-size:14px;">arrow_upward</span>${k.change}</span>` : ''}
          </div>
          <p style="margin-top:8px;font-size:10px;color:#8AA8A2;">${k.target || ''}</p>
        </div>`;
      }).join('');
    }
  }

  // 图表
  const chartBars = document.querySelector('#app-dashboard .chart-bars');
  if (chartBars) {
    if (!d.daily_stats || d.daily_stats.length === 0) {
      chartBars.innerHTML = `<div style="width:100%;text-align:center;color:#747878;font-size:13px;padding:40px 0;">暂无会话数据</div>`;
    } else {
      const maxVal = Math.max(...d.daily_stats.map(s => Math.max(s.sessions || 0, s.answered || 0)), 1);
      chartBars.innerHTML = d.daily_stats.map(s => {
        const sH = Math.max(((s.sessions || 0) / maxVal * 160), 4).toFixed(0);
        const aH = Math.max(((s.answered || 0) / maxVal * 160), 4).toFixed(0);
        // 柱顶直接标数值，高度留给数值行
        return `<div style="display:flex;flex-direction:column;align-items:center;gap:4px;flex:1;">
          <div style="display:flex;align-items:flex-end;gap:10px;">
            <div style="display:flex;flex-direction:column;align-items:center;gap:2px;">
              <span style="font-size:11px;font-weight:600;color:#1c1b1b;">${s.sessions || 0}</span>
              <div style="width:24px;background:var(--teal-600);border-radius:999px;height:${sH}px;transition:all 0.2s;"></div>
            </div>
            <div style="display:flex;flex-direction:column;align-items:center;gap:2px;">
              <span style="font-size:11px;font-weight:500;color:#8AA8A2;">${s.answered || 0}</span>
              <div style="width:24px;background:var(--pastel-blue);border-radius:999px;height:${aH}px;transition:all 0.2s;"></div>
            </div>
          </div>
        </div>`;
      }).join('');
    }
  }

  const labels = document.querySelector('#app-dashboard .chart-labels');
  if (labels) {
    if (!d.daily_stats || d.daily_stats.length === 0) {
      labels.innerHTML = '<span></span>';
    } else {
      labels.innerHTML = d.daily_stats.map(s => `<span style="flex:1;text-align:center;">${s.day || ''}</span>`).join('');
    }
  }

  // 部门列表
  const deptList = document.getElementById('dept-list');
  if (deptList) {
    if (!d.departments || d.departments.length === 0) {
      deptList.innerHTML = `<div style="text-align:center;padding:32px;color:#747878;">暂无部门数据</div>`;
    } else {
      const deptIcons = ['developer_board', 'inventory_2', 'support_agent', 'assignment_ind', 'hub', 'groups'];
      // pastel 图标底色轮换（与 KPI 卡同一套）
      const deptTints = ['var(--teal-50)', 'var(--pastel-blue)', 'var(--pastel-pink)', 'var(--pastel-yellow)'];
      deptList.innerHTML = d.departments.map((dept, i) => `
        <div style="display:flex;align-items:center;justify-content:space-between;padding:12px;border-radius:14px;cursor:pointer;transition:all 0.2s;border:1px solid transparent;" onmouseover="this.style.background='var(--teal-50)'" onmouseout="this.style.background='transparent'">
          <div style="display:flex;align-items:center;gap:12px;">
            <div style="width:40px;height:40px;background:${deptTints[i % deptTints.length]};border-radius:12px;display:flex;align-items:center;justify-content:center;">
              <span class="material-symbols-outlined">${deptIcons[i % deptIcons.length]}</span>
            </div>
            <div>
              <div style="font-size:14px;font-weight:500;">${dept.name || '未命名'}</div>
              <div style="font-size:11px;color:#8AA8A2;">${dept.description || ''}</div>
            </div>
          </div>
          <span style="background:var(--teal-50);color:var(--teal-700);padding:2px 10px;border-radius:999px;font-size:11px;font-weight:700;">${dept.member_count ?? 0}</span>
        </div>
      `).join('');
    }
  }

  // 员工状态表格
  const empTable = document.getElementById('employee-table-body');
  if (empTable) {
    if (!d.agents || d.agents.length === 0) {
      empTable.innerHTML = `<tr><td colspan="5" style="padding:32px;text-align:center;color:#747878;">暂无员工数据</td></tr>`;
    } else {
      // 与后端 Agent.status 原值一一对应（后端已直传，不再二次映射）
      const statusStyles = {
        online: { bg: '#f0fdf4', text: '#166534', dot: '#22c55e', label: '可用' },
        trial: { bg: '#fffbeb', text: '#92400e', dot: '#f59e0b', label: '试运行' },
        indexing: { bg: '#eff6ff', text: '#1d4ed8', dot: '#3b82f6', label: '索引中' },
        pending_check: { bg: '#fef2f2', text: '#991b1b', dot: '#ef4444', label: '受限' },
        maintenance: { bg: '#f1edec', text: '#747878', dot: '#747878', label: '维护中' },
      };
      empTable.innerHTML = d.agents.map(a => {
        const st = statusStyles[a.status] || statusStyles.online;
        // 采纳率无评价数据时后端给 None → 显示「—」,进度条置 0
        const adoptionPct = a.adoption_rate == null ? null : Math.round(a.adoption_rate * 100);
        return `
          <tr style="border-bottom:1px solid var(--border-soft);transition:background 0.2s;" onmouseover="this.style.background='#F0F7F5'" onmouseout="this.style.background='transparent'">
            <td style="padding:16px 24px;">
              <div style="display:flex;align-items:center;gap:12px;">
                ${cuteAvatar(a.name, a.emoji, 32)}
                <span style="font-size:14px;font-weight:500;">${a.name || '匿名'}</span>
              </div>
            </td>
            <td style="padding:16px 24px;font-size:14px;color:#5F7470;">${a.role || '员工'} / ${a.domain || '通用'}</td>
            <td style="padding:16px 24px;">
              <span style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:9999px;font-size:11px;font-weight:500;background:${st.bg};color:${st.text};">
                <span style="width:6px;height:6px;border-radius:50%;background:${st.dot};${a.status === 'trial' ? 'animation:pulse 1s infinite;' : ''}"></span>
                ${st.label}
              </span>
            </td>
            <td style="padding:16px 24px;">
              <div style="display:flex;align-items:center;gap:12px;">
                <div style="width:96px;background:#E3EEEB;height:6px;border-radius:9999px;">
                  <div style="background:var(--teal-600);height:100%;border-radius:9999px;width:${adoptionPct ?? 0}%;"></div>
                </div>
                <span style="font-size:14px;">${adoptionPct == null ? '—' : adoptionPct + '%'}</span>
              </div>
            </td>
            <td style="padding:16px 24px;">
              <button onclick="showAgentCard('${a.id}')" style="color:var(--teal-700);font-size:12px;font-weight:500;background:none;border:none;cursor:pointer;text-decoration:underline;">详情</button>
            </td>
          </tr>
        `;
      }).join('');
    }
  }
}


// ====== 渲染：员工办公室 ======
function renderEmployees() {
  const agents = _cache.agents;
  if (!agents) return;

  const grid = document.getElementById('employee-grid') || document.querySelector('#app-employees .emp-card-grid');
  if (!grid) return;

  const statusStyles = {
    online: { bg: '#f0fdf4', text: '#166534', dot: '#22c55e', label: '可用', border: '#22c55e' },
    trial: { bg: '#fffbeb', text: '#92400e', dot: '#f59e0b', label: '试运行', border: '#f59e0b' },
    offline: { bg: '#fef2f2', text: '#991b1b', dot: '#ef4444', label: '受限', border: '#ef4444' },
    maintenance: { bg: '#f1edec', text: '#747878', dot: '#747878', label: '维护中', border: '#747878' },
  };

  grid.innerHTML = agents.map(a => {
    const st = statusStyles[a.status] || statusStyles.online;
    const adoptionPct = Math.round((a.adoption_rate || 0) * 100);
    const resources = (a.resources || []).slice(0, 3);

    return `
      <div data-agent-id="${a.id}" style="background:#fff;border-radius:12px;border:1px solid #c4c7c7;overflow:hidden;transition:all 0.2s;position:relative;"
        onmouseover="this.style.boxShadow='0 4px 12px rgba(0,0,0,0.08)';this.style.transform='translateY(-2px)'"
        onmouseout="this.style.boxShadow='none';this.style.transform='translateY(0)'">
        <!-- 顶部色带 -->
        <div style="height:3px;background:${st.border};"></div>

        <div style="padding:20px;">
          <!-- 头部：头像 + 姓名 + 状态 -->
          <div style="display:flex;align-items:flex-start;gap:12px;margin-bottom:16px;">
            ${cuteAvatar(a.name, a.emoji, 44, '14px')}
            <div style="flex:1;min-width:0;">
              <div style="display:flex;align-items:center;gap:8px;">
                <span style="font-size:15px;font-weight:600;color:#1c1b1b;">${a.name}</span>
                <span style="font-size:10px;padding:2px 8px;border-radius:9999px;font-weight:500;background:${st.bg};color:${st.text};display:inline-flex;align-items:center;gap:4px;">
                  <span style="width:6px;height:6px;border-radius:50%;background:${st.dot};"></span>
                  ${st.label}
                </span>
              </div>
              <div style="font-size:13px;color:#444748;margin-top:2px;">${a.role}</div>
              <div style="font-size:11px;color:#747878;margin-top:2px;">${a.department_id} · ${a.domain_id}</div>
            </div>
          </div>

          <!-- 指标条 -->
          <div style="display:flex;gap:0;border-top:1px solid #f1edec;border-bottom:1px solid #f1edec;margin-bottom:12px;">
            <div style="text-align:center;flex:1;padding:8px 0;">
              <div style="font-size:16px;font-weight:600;color:#1c1b1b;">${adoptionPct}%</div>
              <div style="font-size:10px;color:#747878;">采纳率</div>
            </div>
            <div style="width:1px;background:#f1edec;"></div>
            <div style="text-align:center;flex:1;padding:8px 0;">
              <div style="font-size:16px;font-weight:600;color:#1c1b1b;">${a.total_sessions || 0}</div>
              <div style="font-size:10px;color:#747878;">会话</div>
            </div>
            <div style="width:1px;background:#f1edec;"></div>
            <div style="text-align:center;flex:1;padding:8px 0;">
              <div style="font-size:16px;font-weight:600;color:#1c1b1b;">${a.version || 'v1'}</div>
              <div style="font-size:10px;color:#747878;">版本</div>
            </div>
          </div>

          <!-- 描述 -->
          <div style="font-size:12px;color:#444748;line-height:18px;margin-bottom:12px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;">${a.description}</div>

          <!-- 资源标签 -->
          ${resources.length > 0 ? `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px;">
            ${resources.map(r => {
              const name = r.replace(/^[💻📄🗄️📎]\s*/, '');
              return `<span style="font-size:11px;padding:2px 8px;background:#f7f3f2;border-radius:4px;color:#444748;">${name}</span>`;
            }).join('')}
          </div>` : ''}

          <!-- 操作按钮 -->
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            <button onclick="showAgentCard('${a.id}')" style="padding:8px;border:1px solid var(--border-soft);border-radius:999px;background:#fff;font-size:12px;font-weight:500;cursor:pointer;color:#1c1b1b;transition:all 0.15s;"
              onmouseover="this.style.background='var(--teal-50)'"
              onmouseout="this.style.background='#fff'"><span class="material-symbols-outlined">badge</span> 名片</button>
            <button onclick="startChat('${a.id}')" style="padding:8px;border:none;border-radius:999px;background:var(--teal-600);color:#fff;font-size:12px;font-weight:500;cursor:pointer;transition:opacity 0.15s;"
              onmouseover="this.style.opacity=0.85"
              onmouseout="this.style.opacity=1"><span class="material-symbols-outlined">chat_bubble</span> 提问</button>
          </div>
        </div>
      </div>
    `;
  }).join('');
}


// ====== 渲染：协作会议室（聊天式布局：左会话栏 + 右对话流） ======
// 进行中任务轮询定时器（有 in_progress 任务时每 5s 刷新一次列表）
let _tasksPollTimer = null;
// 当前选中的协作会话 id（轮询刷新后保持选中）
let _selectedCollabTaskId = null;
// 切会话/新提交后置 true，渲染时强制消息区贴底
let _collabScrollToBottom = false;

/** 会议室文本转义（用户标题/描述/LLM 产出防注入） */
function _collabEsc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function renderTasks() {
  const tasks = _cache.tasks;
  if (!tasks) return;

  const container = document.querySelector('#app-collaboration .app-page-inner');
  if (!container) return;

  // 渲染前记录消息区是否本就近底（轮询刷新时只在近底才跟随滚动，不打扰翻历史）
  const oldFlow = document.getElementById('collab-msg-flow');
  const oldScrollTop = oldFlow ? oldFlow.scrollTop : 0;
  const stickBottom = _collabScrollToBottom || !oldFlow
    || (oldFlow.scrollHeight - oldFlow.scrollTop - oldFlow.clientHeight < 80);
  _collabScrollToBottom = false;
  // 渲染前暂存输入栏状态：轮询重建 innerHTML 会把正在输入的标题/描述清掉，表现为"卡住"
  const oldTitleEl = document.getElementById('collab-title');
  const oldDescEl = document.getElementById('collab-desc');
  const oldTitleVal = oldTitleEl ? oldTitleEl.value : '';
  const oldDescVal = oldDescEl ? oldDescEl.value : '';
  const oldDescShown = oldDescEl ? oldDescEl.style.display !== 'none' : false;
  const oldFocusId = document.activeElement ? document.activeElement.id : '';

  const header = `
    <div class="page-header">
      <h1>协作会议室</h1>
      <p>跨部门 / 多员工并行取证，像群聊一样浏览每个任务的讨论过程，冲突显式标注不强行合并</p>
    </div>`;

  // 空任务：左栏空态 + 右侧仅输入栏
  if (!tasks.length) {
    container.innerHTML = header + `
      <div class="collab-layout">
        <div class="collab-sidebar">
          <div class="collab-sidebar-title">会话</div>
          <div class="collab-sidebar-empty"><span class="material-symbols-outlined" style="font-size:15px;vertical-align:-3px;">forum</span> 暂无会话<br><span>在右下角发起第一个协作任务</span></div>
        </div>
        <div class="collab-main">
          <div class="collab-msg-flow" id="collab-msg-flow">
            <div class="collab-empty-hint">暂无协作任务<br><span>输入任务标题，LLM 拆解后多员工并行执行</span></div>
          </div>
          ${_collabInputBar()}
        </div>
      </div>`;
    return;
  }

  // 默认选中最新任务；已选任务被删则回退到第一个
  if (!_selectedCollabTaskId || !tasks.some(t => t.id === _selectedCollabTaskId)) {
    _selectedCollabTaskId = tasks[0].id;
  }
  const current = tasks.find(t => t.id === _selectedCollabTaskId);

  container.innerHTML = header + `
    <div class="collab-layout">
      <div class="collab-sidebar">
        <div class="collab-sidebar-title">会话（${tasks.length}）</div>
        ${_renderCollabSessions(tasks)}
      </div>
      <div class="collab-main">
        ${_renderCollabConversation(current)}
        ${_collabInputBar()}
      </div>
    </div>`;

  // 消息区贴底（切会话/新提交/轮询时原本就在底部）；非贴底则恢复原滚动位置，避免轮询把用户拽回顶部
  const flow = document.getElementById('collab-msg-flow');
  if (flow) {
    if (stickBottom) flow.scrollTop = flow.scrollHeight;
    else if (oldFlow) flow.scrollTop = Math.min(oldScrollTop, flow.scrollHeight);
  }

  // 恢复输入栏状态（值/展开态/焦点）
  const newTitleEl = document.getElementById('collab-title');
  const newDescEl = document.getElementById('collab-desc');
  if (newTitleEl && oldTitleVal) newTitleEl.value = oldTitleVal;
  if (newDescEl) {
    if (oldDescVal) newDescEl.value = oldDescVal;
    if (oldDescShown) {
      newDescEl.style.display = 'block';
      const toggle = container.querySelector('.collab-desc-toggle');
      if (toggle) toggle.textContent = '收起描述 ▾';
    }
  }
  if (oldFocusId === 'collab-title' && newTitleEl) newTitleEl.focus();
  else if (oldFocusId === 'collab-desc' && newDescEl && oldDescShown) newDescEl.focus();

  // 有进行中的任务时启动轮询（子任务状态/汇总完成后自动停止）
  const hasRunning = tasks.some(t => t.status === 'in_progress');
  if (hasRunning && !_tasksPollTimer) {
    _tasksPollTimer = setInterval(refreshTasks, 5000);
  } else if (!hasRunning && _tasksPollTimer) {
    clearInterval(_tasksPollTimer);
    _tasksPollTimer = null;
  }
}

/** 左侧会话列表：标题 + 状态徽章 + 参与员工头像堆叠 + 子任务数 */
function _renderCollabSessions(tasks) {
  return tasks.map(t => {
    const ts = TASK_STATUS_MAP[t.status] || TASK_STATUS_MAP.in_progress;
    const subs = t.subtasks || [];
    const avatars = subs.slice(0, 4).map(st =>
      `<span class="collab-stack-avatar">${cuteAvatar(st.agent_name, st.agent_emoji, 20)}</span>`
    ).join('');
    return `
      <div class="collab-session ${t.id === _selectedCollabTaskId ? 'active' : ''}"
        onclick="selectCollabTask('${t.id}')">
        <div class="collab-session-top">
          <span class="collab-session-title">${_collabEsc(t.title)}</span>
          <span class="task-status ${ts.class}">${ts.label}</span>
        </div>
        <div class="collab-session-meta">
          <span class="collab-avatar-stack">${avatars}</span>
          <span>${subs.length} 个子任务</span>
        </div>
      </div>`;
  }).join('');
}

/** 右侧对话流：用户右气泡（任务）→ 各员工左卡（子任务）→ 汇总/冲突系统卡 */
function _renderCollabConversation(task) {
  if (!task) {
    return `<div class="collab-msg-flow" id="collab-msg-flow">
      <div class="collab-empty-hint">选择左侧会话查看讨论</div></div>`;
  }
  const ts = TASK_STATUS_MAP[task.status] || TASK_STATUS_MAP.in_progress;

  // 用户发起的任务 = 右侧浅灰气泡（标题 + 可选描述）
  const userBubble = `
    <div class="collab-msg-user">
      <div class="collab-user-bubble">
        <div class="collab-user-title">${_collabEsc(task.title)}</div>
        ${task.description ? `<div class="collab-user-desc">${_collabEsc(task.description)}</div>` : ''}
        <div class="collab-user-meta"><span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">person</span> ${_collabEsc(task.meta_dept)} · <span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">sell</span> ${_collabEsc(task.meta_tag)} · <span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">schedule</span> ${_collabEsc(task.meta_overtime)}</div>
      </div>
    </div>`;

  // 每个子任务 = 一条员工消息（头像 + 无气泡内容,版式对齐总前台 AI 回答）
  // subtask_detail 生命周期：创建时=拆解指令，第 1 轮交付后覆写为草案；互评写独立字段 discussion
  // submitted/discussing/discussed 都渲染草案正文；analyzing 显示 typing，clarify 显示待澄清提示
  const agentMsgs = (task.subtasks || []).map(st => {
    const ss = SUBTASK_STATUS_MAP[st.status] || SUBTASK_STATUS_MAP.analyzing;
    let body;
    if (['submitted', 'discussing', 'discussed'].includes(st.status) && st.detail) {
      const md = (window.ChatModule && ChatModule.renderMarkdown)
        ? ChatModule.renderMarkdown(st.detail)
        : `<pre style="white-space:pre-wrap;font-family:inherit;margin:0;">${_collabEsc(st.detail)}</pre>`;
      body = `<div class="ai-answer-content collab-agent-detail">${md}</div>`;
      // 互评进行中：草案下方加 typing 提示
      if (st.status === 'discussing') {
        body += `<div class="collab-typing"><span></span><span></span><span></span><em>正在查看他人草案并互评…</em></div>`;
      }
      // 互评完成：草案下方追加"互评与补充"区块
      if (st.discussion) {
        const discMd = (window.ChatModule && ChatModule.renderMarkdown)
          ? ChatModule.renderMarkdown(st.discussion)
          : `<pre style="white-space:pre-wrap;font-family:inherit;margin:0;">${_collabEsc(st.discussion)}</pre>`;
        body += `<div class="collab-discussion-block">
          <div class="collab-discussion-label"><span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">forum</span> 互评与补充</div>
          <div class="ai-answer-content">${discMd}</div>
        </div>`;
      }
    } else if (st.status === 'clarify') {
      body = `<div class="collab-clarify-note">⚠ 该子任务未按时交付，已标记待澄清</div>`;
    } else {
      body = `<div class="collab-typing"><span></span><span></span><span></span><em>正在输入…</em></div>`;
    }
    // 底部徽章行（状态 + 置信度 pill,对齐总前台底部操作区）;analyzing 时由 typing 表达进度不显示
    const footer = st.status !== 'analyzing' ? `
      <div class="collab-agent-footer">
        <span class="sub-status ${ss.class}">${ss.label}</span>
        ${st.confidence ? `<span class="collab-confidence">置信度 ${_collabEsc(st.confidence)}</span>` : ''}
      </div>` : '';
    return `
      <div class="collab-msg-agent">
        <div class="collab-agent-avatar">${cuteAvatar(st.agent_name, st.agent_emoji, 36)}</div>
        <div class="collab-agent-card">
          <div class="collab-agent-top">
            <span class="name">${_collabEsc(st.agent_name)}</span>
            <span class="dept-tag">${_collabEsc(st.domain_name)}</span>
          </div>
          <div class="collab-agent-title"><span class="material-symbols-outlined" style="font-size:14px;">assignment</span>${_collabEsc(st.title)}</div>
          ${body}
          ${footer}
        </div>
      </div>`;
  }).join('');

  // 汇总/冲突 = 居中系统卡（成功 ✓ 绿调，冲突 ⚠ 琥珀调）；内容为 LLM 产出的 Markdown
  const conflictBody = (window.ChatModule && ChatModule.renderMarkdown)
    ? ChatModule.renderMarkdown(task.conflict_note || '')
    : _collabEsc(task.conflict_note || '');
  // 完整方案入口：doc_available（后端 result_doc_path 派生）为真时显示按钮
  const docBtn = task.doc_available
    ? `<button class="collab-doc-btn" onclick="viewCollabDoc('${task.id}')"><span class="material-symbols-outlined">description</span> 查看完整方案</button>` : '';
  const conflictHtml = task.conflict_note ? `
    <div class="collab-msg-system ${task.conflict_type === 'success' ? 'success' : 'warn'}">
      <div class="collab-system-label">${task.conflict_type === 'success' ? '✓ 会议纪要' : '⚠ 冲突提示'}</div>
      <div class="ai-answer-content">${conflictBody}</div>
      ${docBtn}
    </div>` : '';

  return `
    <div class="collab-main-header">
      <span class="collab-main-title">${_collabEsc(task.title)}</span>
      <span class="task-status ${ts.class}">${ts.label}</span>
    </div>
    <div class="collab-msg-flow" id="collab-msg-flow">
      ${userBubble}${agentMsgs}${conflictHtml}
    </div>`;
}

/**
 * 查看完整方案:三段式弹窗(遮罩/头/滚动正文),渲染 collab_docs 下合成的 md
 * 仿 admin.js previewResource 模式;失败显示错误文本
 */
async function viewCollabDoc(taskId) {
  const old = document.getElementById('collab-doc-modal');
  if (old) old.remove();

  const modal = document.createElement('div');
  modal.id = 'collab-doc-modal';
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:1000;display:flex;align-items:center;justify-content:center;';
  modal.innerHTML = `
    <div style="background:white;border-radius:12px;width:900px;max-width:94vw;max-height:88vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
      <div style="display:flex;align-items:center;padding:18px 28px;border-bottom:1px solid var(--border-default,#e5e5e5);">
        <h3 style="font-size:17px;font-weight:600;margin:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"><span class="material-symbols-outlined" style="font-size:17px;vertical-align:-3px;">description</span> 完整方案</h3>
        <button onclick="document.getElementById('collab-doc-modal').remove()" style="width:30px;height:30px;border:none;background:transparent;font-size:20px;color:var(--text-tertiary);cursor:pointer;">×</button>
      </div>
      <div id="collab-doc-body" class="ai-answer-content" style="flex:1;overflow-y:auto;padding:24px 32px;font-size:14px;line-height:1.8;">正在加载完整方案…</div>
    </div>`;
  document.body.appendChild(modal);
  modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

  const body = document.getElementById('collab-doc-body');
  try {
    const res = await fetch(`/api/tasks/${taskId}/doc`);
    const data = await res.json().catch(() => ({}));
    if (res.ok && data.content) {
      // 优先复用聊天模块的 Markdown 渲染;不存在时退化为转义纯文本
      body.innerHTML = (window.ChatModule && ChatModule.renderMarkdown)
        ? ChatModule.renderMarkdown(data.content)
        : `<pre style="white-space:pre-wrap;font-family:inherit;">${_collabEsc(data.content)}</pre>`;
    } else {
      body.textContent = data.detail || '完整方案尚未生成';
    }
  } catch (e) {
    body.innerHTML = `<div style="color:#DC2626;">加载失败:${_collabEsc(e.message)}</div>`;
  }
}

/** 底部输入栏：标题（回车提交）+ 展开描述 + 黑底发起按钮 */
function _collabInputBar() {
  return `
    <div class="collab-input-bar">
      <div class="collab-input-row">
        <input id="collab-title" type="text" placeholder="输入协作任务标题，回车发起…"
          onkeydown="if(event.key==='Enter')submitCollabTask()" />
        <button class="collab-desc-toggle" onclick="toggleCollabDesc()" title="补充描述">展开描述 ▸</button>
        <button id="collab-submit" onclick="submitCollabTask()">发起协作</button>
      </div>
      <textarea id="collab-desc" rows="2" placeholder="补充描述（可选）：背景、目标、交付要求…" style="display:none;"></textarea>
    </div>`;
}

/** 展开/收起描述输入框 */
function toggleCollabDesc() {
  const el = document.getElementById('collab-desc');
  const btn = document.querySelector('.collab-desc-toggle');
  if (!el) return;
  const show = el.style.display === 'none';
  el.style.display = show ? 'block' : 'none';
  if (btn) btn.textContent = show ? '收起描述 ▾' : '展开描述 ▸';
  if (show) el.focus();
}

/** 切换会话（记住选中 + 强制贴底） */
function selectCollabTask(id) {
  _selectedCollabTaskId = id;
  _collabScrollToBottom = true;
  renderTasks();
}

/**
 * 静默刷新任务列表（轮询用，不触发整页 loadData）
 */
async function refreshTasks() {
  try {
    const res = await fetch('/api/tasks');
    if (res.ok) {
      _cache.tasks = await res.json();
      renderTasks();
    }
  } catch (e) {
    console.warn('[tasks] 轮询刷新失败', e);
  }
}

/**
 * 发起协作任务：POST /api/tasks（LLM 拆解 + 后台并行执行）
 */
async function submitCollabTask() {
  const titleEl = document.getElementById('collab-title');
  const descEl = document.getElementById('collab-desc');
  const btn = document.getElementById('collab-submit');
  const title = (titleEl.value || '').trim();
  if (!title) {
    titleEl.focus();
    return;
  }
  btn.disabled = true;
  btn.textContent = 'LLM 拆解中…';
  try {
    const res = await fetch('/api/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title,
        description: (descEl.value || '').trim(),
        initiator: '用户手动发起',
        deadline_minutes: 30,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      (window.Toast ? Toast.error(err.detail || '发起协作失败，请稍后重试') : alert(err.detail || '发起协作失败，请稍后重试'));
      btn.disabled = false;
      btn.textContent = '发起协作';
      return;
    }
    // 成功后选中新任务并贴底（renderTasks 重建输入栏，按钮状态自动恢复）
    const created = await res.json().catch(() => null);
    if (created && created.id) {
      _selectedCollabTaskId = created.id;
      _collabScrollToBottom = true;
    }
    if (window.Toast) Toast.success('协作任务已发起，员工们讨论中…');
    await refreshTasks();
  } catch (e) {
    (window.Toast ? Toast.error('网络异常：' + e.message) : alert('网络异常：' + e.message));
    btn.disabled = false;
    btn.textContent = '发起协作';
  }
}


// ====== 渲染：知识与案例 ======
function renderKnowledge() {
  const entries = _cache.knowledge;
  if (!entries) return;

  const grid = document.querySelector('#app-knowledge .knowledge-grid');
  if (!grid) return;

  grid.innerHTML = entries.map(k => {
    const st = KNOWLEDGE_STATUS_MAP[k.status] || KNOWLEDGE_STATUS_MAP.published;
    const warningHtml = k.warning
      ? `<div class="knowledge-warning">⚠ ${k.warning}</div>`
      : '';
    return `
      <div class="knowledge-card">
        <div class="knowledge-card-row">
          <div class="knowledge-icon">${msIcon(k.icon, 'menu_book', 20)}</div>
          <div class="knowledge-text">
            <div class="title">${k.title}</div>
            <div class="domain">${k.domain_id}</div>
          </div>
          <span class="knowledge-status ${st.class}">${st.label}</span>
        </div>
        <div class="knowledge-meta">
          <span class="knowledge-meta-item"><span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">person</span> Owner ${k.owner}</span>
          <span class="knowledge-meta-item"><span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">calendar_month</span> ${k.date}</span>
          <span class="knowledge-meta-item"><span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">monitoring</span> 置信度 ${k.confidence}</span>
        </div>
        ${warningHtml}
      </div>
    `;
  }).join('');
}


// ====== 渲染：关系图谱统计 ======
function renderGraphStats() {
  fetchJSON('/api/graph/stats').then(stats => {
    const cards = document.querySelectorAll('#app-graph .graph-stat-card');
    if (cards.length >= 3) {
      cards[0].querySelector('.stat-value').textContent = stats.node_count;
      cards[1].querySelector('.stat-value').textContent = stats.edge_count;
      cards[2].querySelector('.stat-value').innerHTML = stats.pending_inferred +
        ' <span class="badge" style="background:#FEF3C7;color:#D97706">候选</span>';
    }
  }).catch(() => {});
}


// ====== 渲染：管理与治理表格 ======
function renderAdminTable() {
  const adminAgents = _cache.adminAgents;
  if (!adminAgents) return;

  const tbody = document.querySelector('#app-admin .admin-table tbody');
  if (!tbody) return;

  tbody.innerHTML = adminAgents.map(a => {
    const lc = LIFECYCLE_MAP[a.lifecycle] || LIFECYCLE_MAP.online;
    return `
      <tr>
        <td><div class="emp-cell"><div class="name">${a.name}</div><div class="sub">${a.role}</div></div></td>
        <td>${a.department_id} / ${a.domain_id}</td>
        <td>${a.owner}</td>
        <td>${a.version}</td>
        <td><span class="lifecycle-badge ${lc.class}">${lc.label}</span></td>
        <td><button class="edit-btn">编辑</button></td>
      </tr>
    `;
  }).join('');
}


// ====== 交互动作 ======
function showAgentCard(agentId) {
  const agent = _cache.agents?.find(a => a.id === agentId);
  if (!agent) return;

  // 移除已有模态框
  const old = document.getElementById('agent-card-modal');
  if (old) old.remove();

  const st = STATUS_MAP[agent.status] || STATUS_MAP.available;
  const adoptionPct = Math.round((agent.adoption_rate || 0) * 100);
  const resources = agent.resources || [];

  const modal = document.createElement('div');
  modal.id = 'agent-card-modal';
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:1500;display:flex;align-items:center;justify-content:center;';
  modal.innerHTML = `
    <div style="background:white;border-radius:16px;width:420px;max-height:85vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
      <!-- 顶部色带 -->
      <div style="height:4px;border-radius:16px 16px 0 0;background:${st.class === 'available' ? '#059669' : st.class === 'indexing' ? '#D97706' : st.class === 'restricted' ? '#DC2626' : '#6B7280'};"></div>

      <div style="padding:24px;">
        <!-- 头部 -->
        <div style="display:flex;align-items:flex-start;gap:16px;margin-bottom:20px;">
          ${cuteAvatar(agent.name, agent.emoji, 56, '18px')}
          <div style="flex:1;">
            <div style="display:flex;align-items:center;gap:8px;">
              <h3 style="font-size:18px;font-weight:600;">${agent.name}</h3>
              <span style="font-size:10px;padding:2px 8px;border-radius:12px;font-weight:500;background:${st.class === 'available' ? '#ECFDF5' : st.class === 'indexing' ? '#FEF3C7' : st.class === 'restricted' ? '#FEE2E2' : '#F3F4F6'};color:${st.class === 'available' ? '#059669' : st.class === 'indexing' ? '#D97706' : st.class === 'restricted' ? '#DC2626' : '#6B7280'};">${st.label}</span>
            </div>
            <div style="font-size:14px;color:var(--text-secondary);margin-top:2px;">${agent.role}</div>
            <div style="font-size:12px;color:var(--text-tertiary);margin-top:2px;">${agent.department_id} · ${agent.domain_id}</div>
          </div>
          <button onclick="document.getElementById('agent-card-modal').remove()" style="width:28px;height:28px;border:none;background:transparent;font-size:18px;color:var(--text-tertiary);cursor:pointer;">×</button>
        </div>

        <!-- 指标网格 -->
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--border-light);border-radius:8px;overflow:hidden;margin-bottom:20px;">
          <div style="background:white;padding:12px;text-align:center;">
            <div style="font-size:18px;font-weight:600;">${adoptionPct}%</div>
            <div style="font-size:10px;color:var(--text-tertiary);margin-top:2px;">采纳率</div>
          </div>
          <div style="background:white;padding:12px;text-align:center;">
            <div style="font-size:18px;font-weight:600;">${agent.total_sessions || 0}</div>
            <div style="font-size:10px;color:var(--text-tertiary);margin-top:2px;">总会话</div>
          </div>
          <div style="background:white;padding:12px;text-align:center;">
            <div style="font-size:18px;font-weight:600;">${agent.version || 'v1'}</div>
            <div style="font-size:10px;color:var(--text-tertiary);margin-top:2px;">版本</div>
          </div>
          <div style="background:white;padding:12px;text-align:center;">
            <div style="font-size:14px;font-weight:600;">${agent.owner || '-'}</div>
            <div style="font-size:10px;color:var(--text-tertiary);margin-top:2px;">Owner</div>
          </div>
        </div>

        <!-- 职责描述 -->
        <div style="margin-bottom:16px;">
          <div style="font-size:12px;font-weight:500;color:var(--text-tertiary);margin-bottom:6px;">职责范围</div>
          <div style="font-size:13px;color:var(--text-primary);line-height:20px;">${agent.description}</div>
        </div>

        <!-- 授权资源 -->
        ${resources.length > 0 ? `
        <div style="margin-bottom:20px;">
          <div style="font-size:12px;font-weight:500;color:var(--text-tertiary);margin-bottom:6px;">授权资源</div>
          <div style="display:flex;flex-wrap:wrap;gap:6px;">
            ${resources.map(r => `<span style="font-size:12px;padding:4px 10px;background:var(--bg-input);border-radius:6px;color:var(--text-secondary);">${r}</span>`).join('')}
          </div>
        </div>` : ''}

        <!-- 操作按钮 -->
        <div style="display:flex;gap:8px;">
          <button onclick="document.getElementById('agent-card-modal').remove();startChat('${agent.id}')" style="flex:1;padding:10px;border:none;border-radius:999px;background:var(--teal-700);color:white;font-size:14px;font-weight:500;cursor:pointer;">
            <span class="material-symbols-outlined">chat_bubble</span> 向此员工提问
          </button>
          <button onclick="document.getElementById('agent-card-modal').remove()" style="padding:10px 20px;border:1px solid var(--border-default);border-radius:999px;background:white;font-size:14px;cursor:pointer;">关闭</button>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
}

function startChat(agentId) {
  // 切换到总前台页面
  const nav = document.querySelector('[data-page="frontdesk"]');
  if (nav) nav.click();
  // 发起单聊：新建绑定该员工的干净会话（会话级定向，后端 ChatRequest.agent_id 已支持）
  if (window.ChatModule) ChatModule.startDirectChat(agentId);
}


// ====== 增强原始 handleLogin ======
const _originalHandleLogin = typeof handleLogin !== 'undefined' ? handleLogin : null;

/**
 * 登录按钮状态切换(配合 v2 登录页:spinner 为子 DOM,不能用 textContent 整体覆盖)
 */
function setLoginBtnLoading(loginBtn, loadingText) {
  if (!loginBtn) return;
  loginBtn.disabled = true;
  loginBtn.classList.add('is-loading');
  const label = loginBtn.querySelector('.lp-btn-label');
  if (label) label.textContent = loadingText;
  else loginBtn.textContent = loadingText;
}
function resetLoginBtn(loginBtn) {
  if (!loginBtn) return;
  loginBtn.disabled = false;
  loginBtn.classList.remove('is-loading');
  loginBtn.classList.remove('is-success');
  const label = loginBtn.querySelector('.lp-btn-label');
  if (label) label.textContent = '登录';
  else loginBtn.textContent = '登录';
}

/**
 * 登录处理（重构版）
 * 修复了原版的时序 bug：Promise.race 没有 await 导致数据加载与动画分离
 * 新增：3 步加载进度可视化（部门 → 员工 → 知识库）
 */
async function handleLogin() {
  const emailInput = document.getElementById('login-email');
  const passwordInput = document.getElementById('login-password');
  const loginBtn = document.getElementById('login-btn');
  const email = emailInput ? emailInput.value.trim() : 'guest@agent-office.ai';
  const password = passwordInput ? passwordInput.value.trim() : 'password';

  if (!email || !password) {
    showLoginError('请输入邮箱和密码');
    return;
  }

  // 按钮加载态
  setLoginBtnLoading(loginBtn, '正在登录…');

  // 1. 调用登录 API（失败时进入演示模式）
  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: '登录失败' }));
      showLoginError(err.detail || '登录失败');
      resetLoginBtn(loginBtn);
      return;
    }

    const data = await res.json();
    sessionStorage.setItem('office_agent_token', data.token || 'demo-token');
    sessionStorage.setItem('office_agent_user', data.user_name || '访客用户');
    sessionStorage.setItem('office_agent_role', data.role || '只读权限');
  } catch (e) {
    console.warn('[login] API 不可用，使用演示模式', e);
    sessionStorage.setItem('office_agent_token', 'demo-token');
  }

  // 登录成功:按钮成功态 + 粒子笑脸爆散重聚
  if (loginBtn) {
    loginBtn.classList.remove('is-loading');
    loginBtn.classList.add('is-success');
    const label = loginBtn.querySelector('.lp-btn-label');
    if (label) label.textContent = '✓ 欢迎回来';
  }
  if (window.ParticleFace && window.ParticleFace.explode) {
    window.ParticleFace.explode();
    // 延迟切页:让爆散+重聚在登录页播完(页面切走后 canvas 离视口,IntersectionObserver 会停掉帧循环)
    await new Promise(r => setTimeout(r, 600));
  }

  // 2. 切换到过渡页(粒子吉祥物 + 进度条)
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('page-transition').classList.add('active');

  // 过渡页粒子吉祥物:首次惰性创建,之后每次重播入场动画
  if (window.createParticleFace) {
    if (!window.__tpFace) {
      window.__tpFace = window.createParticleFace(
        document.getElementById('particle-face-transition'),
        { particleCount: 14000, config: window.PF_LIGHT_BG_CONFIG });
    }
    if (window.__tpFace) window.__tpFace.replay();
  }

  // 3. 并行：加载数据 + 最短展示时间（确保动画完整呈现）
  const minDisplayTime = new Promise(r => setTimeout(r, 1500));

  // 分步骤加载数据（用 loadData 复用容错逻辑,进度条同步推进）
  setTransitionProgress(18, '正在获取部门与员工…');
  const dataLoadPromise = (async () => {
    try {
      await loadData();
    } catch(e) {
      console.warn('[login] 数据加载部分失败（不阻断）:', e);
    }
    setTransitionProgress(85, '正在准备知识库…');
  })();

  // 4. 等待数据加载 + 最短展示时间都完成（加 catch 防止阻断）
  await Promise.all([dataLoadPromise, minDisplayTime]).catch(e => {
    console.warn('[login] 数据加载异常（继续进入主应用）:', e);
  });
  setTransitionProgress(100, '准备完成');
  await new Promise(r => setTimeout(r, 320)); // 让 100% 进度可读一瞬再切页

  // 5. 进入主应用
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('page-app').classList.add('active');

  updateUserInfo();

  // 恢复上次选中的页面（登录后保持 Tab）
  const savedPage = sessionStorage.getItem('office_agent_page');
  if (savedPage && savedPage !== 'dashboard') {
    setTimeout(() => {
      const navItem = document.querySelector(`[data-page="${savedPage}"]`);
      if (navItem) {
        window.switchAppPage(savedPage, navItem);
      }
    }, 200);
  }

  resetLoginBtn(loginBtn);
}

/**
 * 更新过渡页进度条与状态文案(粒子吉祥物过渡页)
 */
function setTransitionProgress(pct, statusText) {
  const fill = document.getElementById('tp-progress-fill');
  if (fill) fill.style.width = Math.max(0, Math.min(100, pct)) + '%';
  const status = document.getElementById('tp-status');
  if (status) status.textContent = (statusText || '正在加载资源…') + ' ' + Math.round(pct) + '%';
}

function showLoginError(msg) {
  let errEl = document.getElementById('login-error');
  if (!errEl) {
    errEl = document.createElement('div');
    errEl.id = 'login-error';
    errEl.style.cssText = 'color:#DC2626;font-size:13px;margin-top:8px;text-align:center;padding:8px;background:#FEF2F2;border-radius:8px;';
    // 新登录页用 form 标签
    const form = document.querySelector('#page-login form') || document.querySelector('.login-form');
    if (form) form.appendChild(errEl);
    else {
      // 兜底：插入到登录按钮后面
      const btn = document.getElementById('login-btn');
      if (btn && btn.parentElement) btn.parentElement.appendChild(errEl);
    }
  }
  errEl.textContent = msg;
  setTimeout(() => { if (errEl) errEl.remove(); }, 4000);

  // 错误态:输入框红描边 + 抖动,任一输入框重新输入时自动清除
  ['login-email', 'login-password'].forEach(function (id) {
    const input = document.getElementById(id);
    const field = input && input.closest('.lp-field');
    if (!field) return;
    field.classList.remove('is-error');
    void field.offsetWidth; // 强制重排,重复报错时抖动动画可重新触发
    field.classList.add('is-error');
    input.addEventListener('input', function clearErr() {
      field.classList.remove('is-error');
      input.removeEventListener('input', clearErr);
    });
  });
}

function updateUserInfo() {
  const userName = sessionStorage.getItem('office_agent_user') || '访客用户';
  const userRole = sessionStorage.getItem('office_agent_role') || '只读权限';
  const nameEl = document.querySelector('.sidebar-user .name');
  const roleEl = document.querySelector('.sidebar-user .role');
  if (nameEl) nameEl.textContent = userName;
  if (roleEl) roleEl.textContent = userRole;
}

// ====== 鉴权检查：页面加载时验证 token ======
function checkAuth() {
  const token = sessionStorage.getItem('office_agent_token');
  if (token) {
    // 已登录，跳过登录页直接进入应用
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById('page-app').classList.add('active');
    updateUserInfo();
    // 后台加载数据
    loadData().catch(e => console.warn('[auth] 数据加载失败', e));

    // 恢复上次选中的页面（刷新保持 Tab）
    const savedPage = sessionStorage.getItem('office_agent_page');
    if (savedPage && savedPage !== 'dashboard') {
      setTimeout(() => {
        const navItem = document.querySelector(`[data-page="${savedPage}"]`);
        if (navItem) {
          window.switchAppPage(savedPage, navItem);
        }
      }, 200);
    }
    return true;
  }
  return false;
}

// 登出
function logout() {
  sessionStorage.removeItem('office_agent_token');
  sessionStorage.removeItem('office_agent_user');
  sessionStorage.removeItem('office_agent_role');
  sessionStorage.removeItem('office_agent_page');        // 清理页面选中
  sessionStorage.removeItem('office_agent_admin_tab');   // 清理 admin tab 选中
  location.reload();
}

// 覆盖全局 handleLogin
window.handleLogin = handleLogin;


// ====== 页面切换钩子：初始化各页面的交互模块 ======
const _originalSwitch = typeof window.switchAppPage !== 'undefined' ? window.switchAppPage : null;

window.switchAppPage = function(pageId, el) {
  // 保存当前 pageId 到 sessionStorage（刷新后恢复）
  sessionStorage.setItem('office_agent_page', pageId);

  // 调用原始切换逻辑
  if (_originalSwitch) {
    _originalSwitch(pageId, el);
  } else {
    document.querySelectorAll('.app-page').forEach(p => p.classList.remove('active'));
    const target = document.getElementById('app-' + pageId);
    if (target) target.classList.add('active');
    document.querySelector('.main-content').scrollTop = 0;
  }

  // 更新侧边栏 active 状态（视觉全部交给 CSS .nav-item/.active，JS 只切类与图标填充）
  document.querySelectorAll('.nav-item').forEach(n => {
    n.classList.remove('active');
    const icon = n.querySelector('.material-symbols-outlined');
    if (icon) icon.style.fontVariationSettings = "'FILL' 0";
  });
  if (el) {
    el.classList.add('active');
    const icon = el.querySelector('.material-symbols-outlined');
    if (icon) icon.style.fontVariationSettings = "'FILL' 1";
  }

  // 按页面初始化交互模块
  setTimeout(() => {
    if (pageId === 'frontdesk' && window.ChatModule) {
      ChatModule.init();
    }
    if (pageId === 'graph' && window.GraphCanvas) {
      GraphCanvas.init();
    }
    if (pageId === 'admin' && window.AdminModule) {
      AdminModule.init();
    }
    // 协作会议室:每次切入都拉取最新任务列表(任务状态会被后台执行器推进)
    if (pageId === 'collaboration' && typeof refreshTasks === 'function') {
      refreshTasks();
    }
  }, 100);
};


// ====== 知识搜索框绑定 ======
function bindKnowledgeSearch() {
  const input = document.querySelector('#app-knowledge .knowledge-search input');
  if (!input || input.dataset.bound) return;
  input.dataset.bound = '1';

  let timer = null;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim();
      try {
        const url = q ? `/api/knowledge?search=${encodeURIComponent(q)}` : '/api/knowledge';
        const res = await fetch(url);
        const entries = await res.json();
        renderKnowledgeList(entries);
      } catch (e) {
        console.warn('[search] 知识搜索失败', e);
      }
    }, 300);
  });
}

function renderKnowledgeList(entries) {
  const grid = document.querySelector('#app-knowledge .knowledge-grid');
  if (!grid) return;

  if (!entries || entries.length === 0) {
    grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--text-tertiary);">未找到匹配的知识条目</div>';
    return;
  }

  const statusMap = {
    published: { label: '已发布', class: 'published' },
    expired: { label: '已过期', class: 'expired' },
    pending: { label: '待审核', class: 'pending' },
    pending_review: { label: '待审核', class: 'pending' },
  };

  grid.innerHTML = entries.map(k => {
    const st = statusMap[k.status] || statusMap.published;
    const warningHtml = k.warning
      ? `<div class="knowledge-warning">⚠ ${k.warning}</div>`
      : '';
    const domainDisplay = k.domain_id || k.summary || '';
    return `
      <div class="knowledge-card">
        <div class="knowledge-card-row">
          <div class="knowledge-icon">${msIcon(k.icon, 'menu_book', 20)}</div>
          <div class="knowledge-text">
            <div class="title">${k.title}</div>
            <div class="domain">${domainDisplay}</div>
          </div>
          <span class="knowledge-status ${st.class}">${st.label}</span>
        </div>
        <div class="knowledge-meta">
          <span class="knowledge-meta-item"><span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">person</span> Owner ${k.owner || ''}</span>
          <span class="knowledge-meta-item"><span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">calendar_month</span> ${k.date || ''}</span>
          <span class="knowledge-meta-item"><span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">monitoring</span> 置信度 ${k.confidence || ''}</span>
        </div>
        ${warningHtml}
      </div>
    `;
  }).join('');
}


// ====== 员工筛选按钮绑定 ======
function bindEmployeeFilter() {
  const buttons = document.querySelectorAll('#app-employees .filter-btn');
  buttons.forEach(btn => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = '1';

    btn.addEventListener('click', async () => {
      const deptName = btn.textContent.trim();

      // 更新按钮样式
      buttons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      // 筛选卡片
      const cards = document.querySelectorAll('#app-employees .emp-card-grid .emp-card');
      cards.forEach(card => {
        if (deptName === '全部') {
          card.style.display = '';
        } else {
          const tags = card.querySelectorAll('.emp-tag');
          const match = Array.from(tags).some(t => t.textContent.includes(deptName));
          card.style.display = match ? '' : 'none';
        }
      });
    });
  });
}


// ====== 主初始化入口 ======
function initApp() {
  console.log('[app.js] Office_Agent API 集成层已加载');

  // 鉴权检查：已登录则直接进入应用
  if (typeof checkAuth === 'function' && checkAuth()) {
    console.log('[auth] 检测到有效 token，跳过登录页');
  }

  // 恢复侧边栏收起状态(聊天时收起扩大内容区,跨页保持)
  if (sessionStorage.getItem('sidebarCollapsed') === '1') {
    const shell = document.getElementById('page-app');
    if (shell) shell.classList.add('sidebar-collapsed');
  }

  // 在页面切换时绑定各模块
  const observer = new MutationObserver(() => {
    bindKnowledgeSearch();
    bindEmployeeFilter();
    bindRepoManager();
  });
  const appShell = document.getElementById('page-app');
  if (appShell) {
    observer.observe(appShell, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
  }
}

/**
 * 收起/展开侧边栏（总前台聊天等场景扩大内容区），状态跨页保持
 */
function toggleSidebar() {
  const shell = document.getElementById('page-app');
  if (!shell) return;
  const collapsed = shell.classList.toggle('sidebar-collapsed');
  sessionStorage.setItem('sidebarCollapsed', collapsed ? '1' : '');
}

// ====== 代码仓库管理 ======
function bindRepoManager() {
  const cloneBtn = document.getElementById('repo-clone-btn');
  const repoList = document.getElementById('repo-list');
  if (!cloneBtn || !repoList || cloneBtn.dataset.bound) return;
  cloneBtn.dataset.bound = '1';

  // 加载仓库列表
  loadRepoList();

  // 接入仓库按钮
  cloneBtn.onclick = () => showCloneModal();
}

async function loadRepoList() {
  const repoList = document.getElementById('repo-list');
  if (!repoList) return;

  try {
    const res = await fetch('/api/repos');
    const repos = await res.json();

    if (!repos || repos.length === 0) {
      repoList.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-tertiary);background:white;border:1px solid var(--border-light);border-radius:12px;">点击"接入仓库"按钮，输入 Git 地址</div>';
      return;
    }

    repoList.innerHTML = repos.map(r => {
      const statusColor = r.local_exists ? '#059669' : '#DC2626';
      const statusText = r.local_exists ? '✓ 就绪' : '✕ 未拉取';
      return `
        <div style="background:white;border:1px solid var(--border-light);border-radius:12px;padding:16px;display:flex;align-items:center;gap:16px;box-shadow:0 1px 3px rgba(0,0,0,0.04);">
          <div style="width:40px;height:40px;background:var(--bg-input);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;color:var(--text-secondary);"><span class="material-symbols-outlined" style="font-size:20px;vertical-align:-2px;">inventory_2</span></div>
          <div style="flex:1;min-width:0;">
            <div style="display:flex;align-items:center;gap:8px;">
              <span style="font-size:15px;font-weight:600;color:var(--text-primary);">${r.name || r.repo_id}</span>
              <span style="font-size:11px;padding:2px 8px;border-radius:12px;background:${statusColor}15;color:${statusColor};font-weight:500;">${statusText}</span>
            </div>
            <div style="font-size:12px;color:var(--text-tertiary);margin-top:4px;font-family:monospace;">${r.clone_url || '本地仓库'}</div>
            ${r.file_count ? `<div style="font-size:12px;color:var(--text-tertiary);margin-top:2px;">${r.file_count} 个文件 · ${r.branch || 'main'}</div>` : ''}
          </div>
          <div style="display:flex;gap:8px;flex-shrink:0;">
            ${r.local_exists ? `<button onclick="browseRepo('${r.repo_id}')" style="padding:6px 14px;border:1px solid var(--border-default);border-radius:999px;background:white;font-size:13px;cursor:pointer;">浏览</button>` : ''}
            <button onclick="deleteRepo('${r.repo_id}')" style="padding:6px 14px;border:1px solid var(--border-default);border-radius:999px;background:white;font-size:13px;cursor:pointer;color:#DC2626;">删除</button>
          </div>
        </div>
      `;
    }).join('');
  } catch (e) {
    console.warn('[repo] 加载列表失败', e);
  }
}

function showCloneModal() {
  const modal = document.createElement('div');
  modal.id = 'clone-modal';
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:1000;display:flex;align-items:center;justify-content:center;';
  modal.innerHTML = `
    <div style="background:white;border-radius:12px;padding:32px;width:480px;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
      <h3 style="font-size:18px;font-weight:600;margin-bottom:24px;"><span class="material-symbols-outlined" style="font-size:20px;vertical-align:-4px;">folder_open</span> 接入 Git 仓库</h3>
      <div style="display:flex;flex-direction:column;gap:16px;">
        <div>
          <label style="font-size:13px;font-weight:500;color:var(--text-secondary);margin-bottom:6px;display:block;">Git 地址 *</label>
          <input type="text" id="clone-url" placeholder="https://github.com/user/repo.git" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;font-family:monospace;">
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
          <div>
            <label style="font-size:13px;font-weight:500;color:var(--text-secondary);margin-bottom:6px;display:block;">仓库名称 *</label>
            <input type="text" id="clone-repo-id" placeholder="如 my-project" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;">
          </div>
          <div>
            <label style="font-size:13px;font-weight:500;color:var(--text-secondary);margin-bottom:6px;display:block;">分支</label>
            <input type="text" id="clone-branch" value="main" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;">
          </div>
        </div>
      </div>
      <div style="display:flex;gap:8px;margin-top:24px;">
        <button onclick="document.getElementById('clone-modal').remove()" style="flex:1;padding:10px;border:1px solid var(--border-default);border-radius:999px;background:white;font-size:14px;cursor:pointer;">取消</button>
        <button id="clone-confirm" style="flex:1;padding:10px;border:none;border-radius:999px;background:var(--teal-700);color:white;font-size:14px;cursor:pointer;">Clone</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

  document.getElementById('clone-confirm').onclick = async () => {
    const url = document.getElementById('clone-url').value.trim();
    const repoId = document.getElementById('clone-repo-id').value.trim();
    const branch = document.getElementById('clone-branch').value.trim() || 'main';

    if (!url || !repoId) {
      Toast.warning('请填写 Git 地址和仓库名称');
      return;
    }

    const btn = document.getElementById('clone-confirm');
    btn.disabled = true;
    btn.textContent = '正在 Clone…';

    try {
      const res = await fetch('/api/repos/clone', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ git_url: url, repo_id: repoId, branch, name: repoId }),
      });

      if (res.ok) {
        const data = await res.json();
        modal.remove();
        loadRepoList();
        Toast.success(data.message || 'Clone 成功');
      } else {
        const err = await res.json().catch(() => ({ detail: 'Clone 失败' }));
        throw new Error(err.detail || 'Clone 失败');
      }
    } catch (e) {
      btn.disabled = false;
      btn.textContent = 'Clone';
      Toast.error(`Clone 失败: ${e.message}`);
    }
  };
}

async function browseRepo(repoId) {
  // 弹出文件列表 + 搜索
  const modal = document.createElement('div');
  modal.id = 'browse-modal';
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:1000;display:flex;align-items:center;justify-content:center;';
  modal.innerHTML = `
    <div style="background:white;border-radius:12px;padding:32px;width:640px;max-height:80vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;">
        <h3 style="font-size:18px;font-weight:600;"><span class="material-symbols-outlined" style="font-size:20px;vertical-align:-4px;">inventory_2</span> ${repoId}</h3>
        <button onclick="document.getElementById('browse-modal').remove()" style="width:32px;height:32px;border:none;background:transparent;font-size:20px;color:var(--text-tertiary);cursor:pointer;">×</button>
      </div>
      <div style="display:flex;gap:8px;margin-bottom:16px;">
        <input type="text" id="repo-search-input" placeholder="搜索代码…" style="flex:1;height:36px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 12px;font-size:14px;">
        <button id="repo-search-btn" style="padding:0 18px;background:var(--teal-700);color:white;border:none;border-radius:999px;cursor:pointer;font-size:14px;">搜索</button>
      </div>
      <div id="repo-file-list" style="display:flex;flex-direction:column;gap:4px;">
        <div style="padding:20px;text-align:center;color:var(--text-tertiary);">加载中…</div>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

  // 加载文件列表
  try {
    const res = await fetch(`/api/repos/${repoId}/files?max_results=50`);
    const data = await res.json();
    renderRepoFiles(data.files || [], repoId);
  } catch (e) {
    document.getElementById('repo-file-list').innerHTML = `<div style="padding:20px;text-align:center;color:#DC2626;">加载失败: ${e.message}</div>`;
  }

  // 搜索
  document.getElementById('repo-search-btn').onclick = async () => {
    const query = document.getElementById('repo-search-input').value.trim();
    if (!query) return;

    document.getElementById('repo-file-list').innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-tertiary);">搜索中…</div>';

    try {
      const res = await fetch(`/api/repos/${repoId}/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      });
      const data = await res.json();

      if (data.results && data.results.length > 0) {
        document.getElementById('repo-file-list').innerHTML = data.results.map(r => `
          <div style="padding:10px;background:var(--bg-input);border-radius:8px;cursor:pointer;" onclick="readRepoFile('${repoId}','${r.file}',${r.line})">
            <div style="font-size:13px;font-weight:500;font-family:monospace;"><span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">description</span> ${r.file}:${r.line}</div>
            <div style="font-size:12px;color:var(--text-tertiary);margin-top:4px;font-family:monospace;background:white;padding:4px 8px;border-radius:4px;border:1px solid var(--border-light);">${r.content}</div>
          </div>
        `).join('');
      } else {
        document.getElementById('repo-file-list').innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-tertiary);">未找到匹配的代码</div>';
      }
    } catch (e) {
      document.getElementById('repo-file-list').innerHTML = `<div style="padding:20px;text-align:center;color:#DC2626;">搜索失败: ${e.message}</div>`;
    }
  };
}

function renderRepoFiles(files, repoId) {
  const list = document.getElementById('repo-file-list');
  if (!files || files.length === 0) {
    list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-tertiary);">无文件</div>';
    return;
  }
  list.innerHTML = files.map(f => {
    const sizeKB = (f.size / 1024).toFixed(1);
    return `<div style="padding:8px 12px;background:var(--bg-input);border-radius:6px;cursor:pointer;font-size:13px;display:flex;justify-content:space-between;align-items:center;"
      onclick="readRepoFile('${repoId}','${f.path}')">
      <span style="font-family:monospace;"><span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">description</span> ${f.path}</span>
      <span style="color:var(--text-tertiary);font-size:11px;">${sizeKB}KB</span>
    </div>`;
  }).join('');
}

async function readRepoFile(repoId, filePath, line = 1) {
  const endLine = line + 50;
  try {
    const res = await fetch(`/api/repos/${repoId}/read?file_path=${encodeURIComponent(filePath)}&start_line=${line}&end_line=${endLine}`);
    const data = await res.json();

    // 替换浏览弹窗内容为代码查看
    const list = document.getElementById('repo-file-list');
    if (list) {
      list.innerHTML = `
        <div style="margin-bottom:8px;">
          <button onclick="browseRepo('${repoId}')" style="padding:4px 14px;border:1px solid var(--border-default);border-radius:999px;background:white;font-size:13px;cursor:pointer;">← 返回</button>
          <span style="font-size:13px;font-weight:500;margin-left:8px;font-family:monospace;"><span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">description</span> ${data.file} (L${data.start_line}-${data.end_line}/${data.total_lines})</span>
        </div>
        <pre style="background:#1e1e1e;color:#d4d4d4;padding:16px;border-radius:8px;overflow-x:auto;font-size:13px;line-height:20px;font-family:ui-monospace,Menlo,Monaco,Consolas,monospace;">${data.content.replace(/</g,'&lt;')}</pre>
      `;
    }
  } catch (e) {
    Toast.error(`读取失败: ${e.message}`);
  }
}

async function deleteRepo(repoId) {
  const confirmed = await Toast.confirm(`确认删除仓库「${repoId}」？本地代码将被清除。`, '删除');
  if (!confirmed) return;
  try {
    await fetch(`/api/repos/${repoId}`, { method: 'DELETE' });
    Toast.success('仓库已删除');
    loadRepoList();
  } catch (e) {
    Toast.error(`删除失败: ${e.message}`);
  }
}

// ====== 全局吉祥物:总览页粒子笑脸(惰性创建,离屏自动暂停);侧边栏为史迪奇图片,不走粒子 ======
function initGlobalMascots() {
  if (!window.createParticleFace) return;
  const spots = [
    // 总览页为浅底:用浅底配色预设
    { id: 'mascot-dashboard', count: 9000, config: window.PF_LIGHT_BG_CONFIG },
  ];
  spots.forEach(s => {
    const el = document.getElementById(s.id);
    if (el && !el.dataset.mascotInit) {
      el.dataset.mascotInit = '1';
      window.createParticleFace(el, { particleCount: s.count, config: s.config || undefined });
    }
  });
}

initApp();
initGlobalMascots();
