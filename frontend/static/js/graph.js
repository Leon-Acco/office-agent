/**
 * 关系图谱 Canvas 可视化模块(浅色·组织核心圈层风)
 * 浅色画布 + 深色小圆点(按连接数定大小)+ 点旁标签 + 细浅灰边 + 淡 teal 圈层引导线
 * 布局:以组织管理为核心的圈层放射——中心公司(虚拟根) → 部门环 → 领域环 → 员工环 → 资源外环
 *   按父子关系递归分配角度扇区(子树越大扇区越宽),目标环位弹簧保证整齐归位
 * 动感:节点从中心绽放归位,拖拽节点局部再加热,alpha 冷却后停止力学计算省 CPU
 * 交互:滚轮缩放 / 拖拽平移 / 节点拖拽(松手弹回环位) / 悬停邻居聚焦 / 类型筛选 / 双击复位
 */

const GraphCanvas = {
  canvas: null,
  ctx: null,
  nodes: [],
  edges: [],
  hoverNode: null,
  dragNode: null,
  panning: false,
  panStart: null,
  animationId: null,
  filterType: null, // 当前筛选的节点类型
  resizeObserver: null,
  refitTimer: null, // 入场绽放后一次性重新取景的定时器

  // 力导向模拟状态
  alpha: 0,          // 模拟热度(1=最热,冷却到 ALPHA_MIN 后停算)
  ALPHA_MIN: 0.02,   // 冷却阈值
  ALPHA_DECAY: 0.02, // 每帧衰减率

  // 视图变换(缩放/平移)
  view: { scale: 1, ox: 0, oy: 0 },

  // 浅色主题配色(按节点类型,保证浅底上的对比度)
  COLORS: {
    company:    '#0F766E',
    department: '#6d5ae0',
    domain:     '#3b82f6',
    agent:      '#2fa05a',
    repo:       '#8b5cf6',
    skill:      '#d97706',
    tool:       '#0891b2',
    knowledge:  '#ea580c',
    resource:   '#0891b2',
  },
  BG: '#fcfcfb',
  EDGE: 'rgba(70, 80, 100, 0.45)',   // 关系边:加深提透明度,浅底上更清晰
  EDGE_HI: '#2f3340',
  LABEL: '#2f3340',                  // 标签:深灰近墨,提升可读性
  LABEL_HALO: 'rgba(252, 252, 251, 0.88)', // 标签白描边(压过背后的边与点阵)
  GRID_DOT: 'rgba(15, 118, 110, 0.20)',  // 点阵网格颜色(teal 系,适度可见)
  GRID_GAP: 26,                          // 点阵间距(CSS px)

  /**
   * 初始化 Canvas 图谱
   */
  async init() {
    const container = document.querySelector('#app-graph .graph-canvas');
    if (!container) return;

    // 重建画布(幂等:重复进入页面先停旧动画)
    this.destroy();
    container.innerHTML = '<canvas id="graphCanvas" style="display:block;width:100%;height:100%;cursor:grab;border-radius:12px;"></canvas>';
    this.canvas = container.querySelector('#graphCanvas');
    this.ctx = this.canvas.getContext('2d');
    this.view = { scale: 1, ox: 0, oy: 0 };
    this.hoverNode = null;
    this.dragNode = null;

    this.resizeCanvas();
    // 容器尺寸变化时重设画布并重新取景
    this.resizeObserver = new ResizeObserver(() => {
      this.resizeCanvas();
      this.fitToView();
    });
    this.resizeObserver.observe(container);

    // 加载数据
    try {
      const res = await fetch('/api/graph');
      const data = await res.json();
      this.setData(data.nodes || [], data.edges || []);
    } catch (e) {
      console.error('[graph] 加载失败', e);
      container.innerHTML = '<div style="padding:40px;text-align:center;color:#8a8f9e;">图谱数据加载失败</div>';
      return;
    }

    this.bindEvents();
    this.animate();
  },

  /**
   * 按容器尺寸重设画布(支持高分屏)
   */
  resizeCanvas() {
    if (!this.canvas) return;
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = rect.width * dpr;
    this.canvas.height = rect.height * dpr;
    this.dpr = dpr;
    this.width = rect.width;
    this.height = rect.height;
  },

  /**
   * 设置图数据:以组织管理为核心的圈层整齐布局
   * 中心=公司(虚拟根) → 部门环 → 领域环 → 员工环 → 资源外环(仓库/能力/工具/知识)
   * 按父子关系递归分配角度扇区(子树越大扇区越宽),节点从中心绽放后归位到目标环位
   * 无部门数据时退化:无虚拟根,各类型按圈层整圆均布,依然整齐
   */
  setData(nodes, edges) {
    // 类型 → 圈层(0 中心根,1 部门,2 领域,3 员工,4 资源外环)
    const RING_OF = { company: 0, department: 1, domain: 2, agent: 3 };
    const ringOf = (t) => (RING_OF[t] !== undefined ? RING_OF[t] : 4);

    // 注入虚拟公司根节点(组织管理核心),与各部门连"管理"边
    let all = nodes.slice();
    const allEdges = edges.slice();
    if (all.some(n => n.type === 'department') && !all.some(n => n.type === 'company')) {
      all.unshift({ id: '__company__', label: '公司', type: 'company', verified: true });
      for (const n of nodes) {
        if (n.type === 'department') allEdges.push({ source: '__company__', target: n.id, label: '管理' });
      }
    }
    const byId = {};
    all.forEach(n => { byId[n.id] = n; });

    // 连接数统计(决定节点大小)
    const degree = {};
    for (const e of allEdges) {
      degree[e.source] = (degree[e.source] || 0) + 1;
      degree[e.target] = (degree[e.target] || 0) + 1;
    }

    // 父子归属:父=低一圈的邻居(优先恰好低一圈;兜底取圈层最低的邻居,如知识直挂领域)
    const parentOf = {};
    for (const e of allEdges) {
      const s = byId[e.source], t = byId[e.target];
      if (!s || !t) continue;
      const rs = ringOf(s.type), rt = ringOf(t.type);
      if (rt === rs + 1 && parentOf[t.id] === undefined) parentOf[t.id] = s.id;
      else if (rs === rt + 1 && parentOf[s.id] === undefined) parentOf[s.id] = t.id;
    }
    for (const e of allEdges) {
      const s = byId[e.source], t = byId[e.target];
      if (!s || !t) continue;
      for (const pair of [[s, t], [t, s]]) {
        const a = pair[0], b = pair[1];
        if (a.type === 'company') continue;
        if (parentOf[a.id] === undefined && ringOf(b.type) < ringOf(a.type)) parentOf[a.id] = b.id;
      }
    }
    // 仍无父的孤儿挂到根(无根则为 null,后面按圈层均布)
    const rootId = (all[0] && all[0].type === 'company') ? all[0].id : null;
    for (const n of all) {
      if (n.id === rootId) continue;
      if (parentOf[n.id] === undefined) parentOf[n.id] = rootId;
    }

    // 子树权重(子树越大分到的扇区越宽,环上分布越匀)
    const children = {};
    for (const id in parentOf) {
      const p = parentOf[id];
      if (p) (children[p] = children[p] || []).push(id);
    }
    const weight = {};
    const calcW = (id) => {
      if (weight[id] !== undefined) return weight[id];
      let w = 1;
      for (const c of (children[id] || [])) w += calcW(c);
      weight[id] = w;
      return w;
    };
    all.forEach(n => calcW(n.id));

    // 递归扇区分配:根占整圆,子节点按权重切分父扇区,节点取扇区中角
    const angleOf = {};
    const assign = (id, a0, a1) => {
      angleOf[id] = (a0 + a1) / 2;
      const kids = children[id] || [];
      const total = kids.reduce((sum, c) => sum + weight[c], 0) || 1;
      let a = a0;
      for (const c of kids) {
        const span = (a1 - a0) * weight[c] / total;
        assign(c, a, a + span);
        a += span;
      }
    };
    if (rootId) assign(rootId, 0, Math.PI * 2);
    // 兜底:未被扇区覆盖的节点(无根场景)按圈层整圆均布
    for (let k = 1; k <= 4; k++) {
      const ringNodes = all.filter(n => ringOf(n.type) === k && angleOf[n.id] === undefined);
      ringNodes.forEach((n, idx) => {
        angleOf[n.id] = (idx / Math.max(ringNodes.length, 1)) * Math.PI * 2;
      });
    }

    // 各环半径:基础值 + 按节点数扩容(保证环上弧距不挤)
    const RING_BASE = [0, 150, 265, 385, 500];
    const RING_ARC = [0, 110, 88, 72, 52];
    const countByRing = [0, 0, 0, 0, 0];
    all.forEach(n => countByRing[ringOf(n.type)]++);
    this.ringRadii = RING_BASE.map((b, k) =>
      k === 0 ? 0 : Math.max(b, countByRing[k] * RING_ARC[k] / (Math.PI * 2)));

    this.nodes = all.map((n, i) => {
      const deg = degree[n.id] || 0;
      const ring = ringOf(n.type);
      const base = ring === 0 ? 12 : n.type === 'department' ? 9 : n.type === 'domain' ? 7.5 : n.type === 'agent' ? 7 : 5.5;
      const ang = angleOf[n.id];
      const rr = this.ringRadii[ring];
      // 从中心小范围随机出发,目标环位弹簧将其拉到环位(整齐绽放)
      const a0 = (i / Math.max(all.length, 1)) * Math.PI * 2;
      const r0 = 8 + Math.random() * 24;
      return {
        ...n,
        degree: deg,
        ring,
        tx: Math.cos(ang) * rr,
        ty: Math.sin(ang) * rr,
        x: Math.cos(a0) * r0,
        y: Math.sin(a0) * r0,
        vx: 0,
        vy: 0,
        radius: base + Math.min(deg, 14) * 0.6,
      };
    });

    this.edges = allEdges.map(e => ({
      ...e,
      sourceNode: this.nodes.find(n => n.id === e.source),
      targetNode: this.nodes.find(n => n.id === e.target),
    })).filter(e => e.sourceNode && e.targetNode);

    // 点火:全热启动,节点从中心绽放归位
    this.alpha = 1;
    this._coolFitted = false; // 待冷却后按最终布局重新取景
    this.fitToView();
    // 绽放归位后一次性重新取景,让最终布局居中充满画布
    clearTimeout(this.refitTimer);
    this.refitTimer = setTimeout(() => this.fitToView(), 2200);
  },

  /**
   * 力导向模拟单步(圈层布局版):
   *   目标环位弹簧(主约束,整齐来源) + 弱链接弹簧(添有机感)
   *   + 弱节点斥力(推开贴脸邻居) + 半径碰撞(防重叠压字)
   * 冷却到 ALPHA_MIN 后不再计算,只保留渲染
   */
  tick() {
    if (this.alpha < this.ALPHA_MIN) {
      // 首次冷却沉淀完成:按最终布局重新取景(只做一次,拖拽再热不触发,避免视图跳变)
      if (!this._coolFitted) {
        this._coolFitted = true;
        this.fitToView();
      }
      return;
    }
    this.alpha *= (1 - this.ALPHA_DECAY);

    const alpha = this.alpha;
    const TARGET_K = 0.10;   // 目标环位弹簧强度(圈层整齐的主约束力)
    const LINK_DIST = 120;   // 链接目标弧长
    const LINK_K = 0.02;     // 弹簧强度(弱,不破坏环序)
    const CHARGE = 1600;     // 斥力强度(弱,只推开贴脸邻居)
    const PAD = 16;          // 碰撞间隙(留给标签)

    // 链接弹簧
    for (const e of this.edges) {
      const s = e.sourceNode;
      const t = e.targetNode;
      let dx = t.x - s.x;
      let dy = t.y - s.y;
      let d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (d - LINK_DIST) / d * LINK_K * alpha;
      dx *= f; dy *= f;
      s.vx += dx; s.vy += dy;
      t.vx -= dx; t.vy -= dy;
    }

    // 斥力 + 碰撞(同一趟 O(n²))
    const list = this.nodes;
    for (let i = 0; i < list.length; i++) {
      const a = list[i];
      for (let j = i + 1; j < list.length; j++) {
        const b = list[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 1; }
        const d = Math.sqrt(d2);
        // 斥力随距离平方衰减,远距离忽略(>300px 互不影响)
        if (d < 300) {
          const f = CHARGE * alpha / d2 / d;
          a.vx -= dx * f; a.vy -= dy * f;
          b.vx += dx * f; b.vy += dy * f;
        }
        // 碰撞:两圆相交则沿法线推开
        const min = a.radius + b.radius + PAD;
        if (d < min) {
          const push = (min - d) / d * 0.5 * alpha;
          a.vx -= dx * push; a.vy -= dy * push;
          b.vx += dx * push; b.vy += dy * push;
        }
      }
    }

    // 应用速度:目标环位引力 + 阻尼 + 位置积分(拖拽节点由鼠标接管,松手后弹回环位)
    for (const n of list) {
      if (n === this.dragNode) { n.vx = 0; n.vy = 0; continue; }
      n.vx = (n.vx + (n.tx - n.x) * TARGET_K * alpha) * 0.55;
      n.vy = (n.vy + (n.ty - n.y) * TARGET_K * alpha) * 0.55;
      n.x += n.vx;
      n.y += n.vy;
    }
  },

  /**
   * 再加热:拖拽/交互时唤醒模拟(Obsidian 的"拨一下又活过来"手感)
   */
  reheat(level = 0.3) {
    this.alpha = Math.max(this.alpha, level);
  },

  /**
   * 世界坐标 → 屏幕坐标变换
   */
  applyView() {
    const { scale, ox, oy } = this.view;
    this.ctx.setTransform(this.dpr * scale, 0, 0, this.dpr * scale, this.dpr * ox, this.dpr * oy);
  },

  /**
   * 点阵网格背景(屏幕空间绘制,不随缩放变化;偏移取模实现随平移联动)
   */
  drawDotGrid() {
    const ctx = this.ctx;
    const gap = this.GRID_GAP;
    const w = this.canvas.width / this.dpr;
    const h = this.canvas.height / this.dpr;
    const offX = ((this.view.ox % gap) + gap) % gap;
    const offY = ((this.view.oy % gap) + gap) % gap;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.fillStyle = this.GRID_DOT;
    ctx.beginPath();
    for (let x = offX; x < w; x += gap) {
      for (let y = offY; y < h; y += gap) {
        ctx.moveTo(x + 1.3, y);
        ctx.arc(x, y, 1.3, 0, Math.PI * 2);
      }
    }
    ctx.fill();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
  },

  /**
   * 绘制(浅色底,弱化装饰,突出节点与关系本身)
   */
  draw() {
    const ctx = this.ctx;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = this.BG;
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

    // 点阵网格背景(Obsidian 风):屏幕空间恒定密度,用视图偏移取模让点阵随平移联动
    this.drawDotGrid();

    this.applyView();

    // 圈层引导线(世界空间):淡 teal 细环,强化"入圈"秩序感
    if (this.ringRadii) {
      ctx.strokeStyle = 'rgba(15, 118, 110, 0.08)';
      ctx.lineWidth = 1 / this.view.scale;
      for (let k = 1; k < this.ringRadii.length; k++) {
        ctx.beginPath();
        ctx.arc(0, 0, this.ringRadii[k], 0, Math.PI * 2);
        ctx.stroke();
      }
    }

    const hover = this.hoverNode;
    const hasFilter = !!this.filterType;

    // 邻居集合(悬停聚焦用)
    let neighbors = null;
    if (hover) {
      neighbors = new Set([hover.id]);
      for (const e of this.edges) {
        if (e.source === hover.id) neighbors.add(e.target);
        if (e.target === hover.id) neighbors.add(e.source);
      }
    }

    // 绘制边(细浅灰线,悬停边微亮加粗)
    ctx.lineCap = 'round';
    for (const edge of this.edges) {
      const s = edge.sourceNode;
      const t = edge.targetNode;
      const isHi = hover && (s.id === hover.id || t.id === hover.id);
      let alpha = 1;
      if (hover && !isHi) alpha = 0.08;
      if (hasFilter && s.type !== this.filterType && t.type !== this.filterType) alpha = Math.min(alpha, 0.06);

      ctx.globalAlpha = alpha;
      ctx.strokeStyle = isHi ? this.EDGE_HI : this.EDGE;
      ctx.lineWidth = (isHi ? 2.2 : 1.3) / this.view.scale;
      ctx.beginPath();
      ctx.moveTo(s.x, s.y);
      ctx.lineTo(t.x, t.y);
      ctx.stroke();

      // 边标签仅悬停时显示
      if (isHi && edge.label) {
        const mx = (s.x + t.x) / 2;
        const my = (s.y + t.y) / 2;
        ctx.font = `${11 / this.view.scale}px Inter, sans-serif`;
        ctx.fillStyle = '#3f4653';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'bottom';
        ctx.fillText(edge.label, mx, my - 3 / this.view.scale);
      }
    }

    // 绘制节点
    for (const node of this.nodes) {
      const color = this.COLORS[node.type] || this.COLORS.domain;
      const isHover = hover && hover.id === node.id;
      let alpha = 1;
      if (neighbors && !neighbors.has(node.id)) alpha = 0.15;
      if (hasFilter && node.type !== this.filterType) alpha = Math.min(alpha, 0.1);

      ctx.globalAlpha = alpha;

      // 节点柔光晕(同色低透明外圈)
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.radius + 4.5 / this.view.scale, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.globalAlpha = alpha * 0.12;
      ctx.fill();
      ctx.globalAlpha = alpha;

      // 悬停发光(阴影辉光)
      if (isHover) {
        ctx.shadowColor = color;
        ctx.shadowBlur = 14 / this.view.scale;
      }

      // 节点圆点(白描边与背后的边/点阵分离,更清晰)
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.strokeStyle = this.LABEL_HALO;
      ctx.lineWidth = 2 / this.view.scale;
      ctx.stroke();

      // 悬停光圈
      if (isHover) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius + 3 / this.view.scale, 0, Math.PI * 2);
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5 / this.view.scale;
        ctx.stroke();
      }

      // 未验证节点:虚线外圈标记
      if (!node.verified) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius + 2.5 / this.view.scale, 0, Math.PI * 2);
        ctx.setLineDash([3 / this.view.scale, 3 / this.view.scale]);
        ctx.strokeStyle = '#d97706';
        ctx.lineWidth = 1 / this.view.scale;
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // 点旁标签(Obsidian 风:统一放圆点右侧,左对齐;白描边压过背景元素)
      const fs = (isHover ? 13.5 : 12.5) / this.view.scale;
      ctx.font = `${isHover ? '600 ' : ''}${fs}px Inter, sans-serif`;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      const labelText = this.truncate(node.label, 16);
      const labelX = node.x + node.radius + 5 / this.view.scale;
      ctx.lineWidth = 3.5 / this.view.scale;
      ctx.strokeStyle = this.LABEL_HALO;
      ctx.strokeText(labelText, labelX, node.y);
      ctx.fillStyle = isHover ? '#0f1115' : this.LABEL;
      ctx.fillText(labelText, labelX, node.y);
    }

    ctx.globalAlpha = 1;
  },

  truncate(text, max) {
    if (!text) return '';
    return text.length > max ? text.slice(0, max) + '…' : text;
  },

  /**
   * 动画循环:先走一步力学(冷却后内部短路),再重绘响应悬停/缩放/拖拽
   */
  animate() {
    this.tick();
    this.draw();
    this.animationId = requestAnimationFrame(() => this.animate());
  },

  /**
   * 取景:按节点包围盒调整缩放与平移,使全图居中可见
   */
  fitToView() {
    if (!this.nodes.length || !this.width) return;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of this.nodes) {
      minX = Math.min(minX, n.x - 30);
      maxX = Math.max(maxX, n.x + 150); // 右侧标签余量
      minY = Math.min(minY, n.y - 40);
      maxY = Math.max(maxY, n.y + 40);
    }
    const bw = Math.max(maxX - minX, 1);
    const bh = Math.max(maxY - minY, 1);
    const scale = Math.min(this.width / bw, this.height / bh, 1.6) * 0.94;
    this.view.scale = Math.min(4, Math.max(0.15, scale));
    this.view.ox = this.width / 2 - (minX + bw / 2) * this.view.scale;
    this.view.oy = this.height / 2 - (minY + bh / 2) * this.view.scale;
  },

  /**
   * 鼠标事件绑定
   */
  bindEvents() {
    const canvas = this.canvas;

    // 屏幕坐标 → 世界坐标
    const toWorld = (e) => {
      const rect = canvas.getBoundingClientRect();
      const sx = (e.clientX - rect.left) * (this.width / rect.width);
      const sy = (e.clientY - rect.top) * (this.height / rect.height);
      return {
        sx, sy,
        x: (sx - this.view.ox) / this.view.scale,
        y: (sy - this.view.oy) / this.view.scale,
      };
    };

    const findNode = (pos) => {
      // 倒序:后画的(上层)先命中
      for (let i = this.nodes.length - 1; i >= 0; i--) {
        const node = this.nodes[i];
        const dx = node.x - pos.x;
        const dy = node.y - pos.y;
        if (Math.sqrt(dx * dx + dy * dy) < node.radius + 3 / this.view.scale) return node;
      }
      return null;
    };

    canvas.addEventListener('mousemove', (e) => {
      const pos = toWorld(e);

      if (this.dragNode) {
        this.dragNode.x = pos.x;
        this.dragNode.y = pos.y;
        this.reheat(0.25); // 拖拽唤醒周边力学,邻居跟着让位
        return;
      }
      if (this.panning && this.panStart) {
        this.view.ox = pos.sx - this.panStart.x;
        this.view.oy = pos.sy - this.panStart.y;
        return;
      }

      const node = findNode(pos);
      this.hoverNode = node;
      canvas.style.cursor = node ? 'pointer' : 'grab';
    });

    canvas.addEventListener('mousedown', (e) => {
      const pos = toWorld(e);
      const node = findNode(pos);
      if (node) {
        this.dragNode = node;
        this.reheat(0.3);
        canvas.style.cursor = 'grabbing';
      } else {
        // 空白处拖拽 = 平移
        this.panning = true;
        this.panStart = { x: pos.sx - this.view.ox, y: pos.sy - this.view.oy };
        canvas.style.cursor = 'grabbing';
      }
    });

    canvas.addEventListener('mouseup', () => {
      if (this.dragNode) this.reheat(0.15); // 松手后轻微回弹沉淀
      this.dragNode = null;
      this.panning = false;
      canvas.style.cursor = 'grab';
    });

    canvas.addEventListener('mouseleave', () => {
      this.hoverNode = null;
      this.dragNode = null;
      this.panning = false;
    });

    // 滚轮缩放(以光标为中心)
    canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const pos = toWorld(e);
      const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
      const next = Math.min(4, Math.max(0.15, this.view.scale * factor));
      const real = next / this.view.scale;
      // 保持光标下的世界点不动
      this.view.ox = pos.sx - (pos.sx - this.view.ox) * real;
      this.view.oy = pos.sy - (pos.sy - this.view.oy) * real;
      this.view.scale = next;
    }, { passive: false });

    // 双击复位为自适应取景
    canvas.addEventListener('dblclick', () => {
      this.fitToView();
    });

    // 筛选按钮
    document.querySelectorAll('#app-graph .graph-filter-label.normal').forEach(btn => {
      const text = btn.textContent.trim();
      const typeMap = {
        '部门': 'department', '领域': 'domain', '员工': 'agent', '仓库': 'repo',
        '能力': 'skill', '工具': 'tool', '知识': 'knowledge', '资源': 'resource',
      };
      btn.onclick = () => {
        if (typeMap[text]) {
          this.filterType = this.filterType === typeMap[text] ? null : typeMap[text];
          document.querySelectorAll('#app-graph .graph-filter-label.normal').forEach(b => b.classList.remove('active'));
          if (this.filterType) btn.classList.add('active');
        }
      };
    });
  },

  /**
   * 停止动画与监听
   */
  destroy() {
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
      this.animationId = null;
    }
    if (this.resizeObserver) {
      this.resizeObserver.disconnect();
      this.resizeObserver = null;
    }
    clearTimeout(this.refitTimer);
  },
};

window.GraphCanvas = GraphCanvas;
