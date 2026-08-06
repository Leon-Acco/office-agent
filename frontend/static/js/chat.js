/**
 * 总前台聊天模块 v5 — 新设计风格 + Canvas 侧边文档面板 + 多会话持久化
 * ============================================
 * 3 栏布局：
 *   - 会话侧栏（240px）：新建会话 + 会话列表（后端持久化，刷新可恢复）
 *   - 主内容区：Header + 3 层分诊链路 + 答案卡片 + 底部圆角输入栏
 *   - Canvas 面板（480px）：AI 回答中的代码块/长文档可在此打开、编辑、复制、下载
 *
 * 多会话：Session/Message 由后端持久化，init 时拉取列表，历史消息懒加载
 * Canvas：纯前端解析（``` 代码块注入入口按钮，_blockStore 存原文），SSE 协议不动
 */

const ChatModule = {
  sessions: {},          // { sessionId: { id, title, messages: []|null(未加载), route, preview, createdAt } }
  currentSessionId: null,
  isStreaming: false,
  initialized: false,
  _initPromise: null,  // init 去重 promise（并发调用共享同一次初始化）
  pendingAgentId: null,  // 定向提问的员工 id（员工办公室"向此员工提问"时设置）
  canvas: { open: false, editing: false, title: '', lang: '', content: '' },
  _blockStore: [],       // 代码块/长文原文暂存（Canvas 入口按钮按索引取用）
  _stickBottom: true,    // 用户是否钉在消息底部（上翻阅读时暂停自动吸底）
  _abortCtrl: null,      // 流式请求的中止控制器（停止按钮用）
  _renderScheduled: false, // 流式渲染节流:是否已排队一帧渲染
  _lastStreamRender: 0,    // 上次流式渲染时间戳(节流间隔基准)

  /**
   * 初始化：构建布局 + 绑定事件 + 加载后端会话列表（失败降级纯本地）
   * 用 _initPromise 去重并发调用（startDirectChat 首次进页时需 await 它，避免会话被覆盖）
   */
  init() {
    if (this._initPromise) return this._initPromise;
    this._initPromise = (async () => {
      this.initialized = true;
      this.buildLayout();
      this.bindEvents();
      this.injectThemeStyle();
      await this.loadSessions();
      const list = Object.values(this.sessions).sort((a, b) => b.createdAt - a.createdAt);
      if (list.length > 0) {
        // 恢复最近一个会话（含历史消息懒加载）
        await this.switchSession(list[0].id);
      } else {
        this.startNewSession();
      }
      this.initChatMascot();
    })();
    return this._initPromise;
  },

  /**
   * 构建 3 栏布局（会话侧栏 + 主内容区 + Canvas 面板）
   * 直接操作 #app-frontdesk 本身（静态骨架无 .app-page-inner，旧选择器会提前 return）
   */
  buildLayout() {
    const page = document.getElementById('app-frontdesk');
    if (!page) return;

    // 铺满主内容区卡片；display 由 .app-page.active 控制，此处只定高度与裁剪
    // （外框布局后 .main-content 为固定高度圆角卡片，用 100% 而非 100vh）
    page.style.height = '100%';
    page.style.overflow = 'hidden';

    page.innerHTML = `
      <!-- 三栏容器：会话侧栏 + 主内容 + Canvas 面板 -->
      <div style="display:flex;height:100%;overflow:hidden;position:relative;">

        <!-- ========== 会话侧栏（240px） ========== -->
        <aside style="width:240px;flex-shrink:0;background:#FAFAFA;border-right:1px solid var(--border-light);display:flex;flex-direction:column;">
          <!-- 新建会话按钮 -->
          <div style="padding:12px;background:white;border-bottom:1px solid var(--border-light);">
            <button id="chat-new-session"
              style="width:100%;height:36px;display:flex;align-items:center;gap:8px;padding:0 12px;background:white;border:1px solid var(--border-default);border-radius:8px;cursor:pointer;font-size:14px;color:var(--text-primary);font-weight:500;transition:all 0.15s;"
              onmouseover="this.style.borderColor='var(--brand-primary)';this.style.color='var(--brand-primary)'"
              onmouseout="this.style.borderColor='var(--border-default)';this.style.color='var(--text-primary)'">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="5" x2="12" y2="19"></line>
                <line x1="5" y1="12" x2="19" y2="12"></line>
              </svg>
              <span>新建会话</span>
            </button>
          </div>
          <!-- 会话列表（滚动） -->
          <div id="chat-session-list" style="flex:1;overflow-y:auto;padding:8px;"></div>
        </aside>

        <!-- ========== 主内容区 ========== -->
        <main style="flex:1;display:flex;flex-direction:column;background:white;min-width:0;position:relative;">
          <!-- 背景光晕（装饰，不响应事件） -->
          <div style="position:absolute;top:-120px;right:-80px;width:340px;height:340px;border-radius:50%;background:rgba(225,113,0,0.08);filter:blur(70px);pointer-events:none;"></div>
          <div style="position:absolute;bottom:-100px;left:-60px;width:300px;height:300px;border-radius:50%;background:rgba(225,113,0,0.05);filter:blur(70px);pointer-events:none;"></div>

          <!-- Header -->
          <header style="padding:16px 32px;border-bottom:1px solid var(--border-light);flex-shrink:0;display:flex;align-items:center;justify-content:space-between;position:relative;z-index:1;">
            <div>
              <h1 id="chat-header-title" style="margin:0;font-size:24px;font-weight:600;color:var(--text-primary);line-height:36px;">总前台</h1>
              <p id="chat-header-sub" style="margin:0;font-size:13px;color:var(--text-secondary);line-height:20px;margin-top:4px;">向公司提问，由总前台 + 部门对接人两级分诊，定位到最合适的员工作答</p>
            </div>
            <div style="display:flex;align-items:center;gap:10px;">
            <!-- 退出单聊按钮（仅单聊会话显示） -->
            <button id="chat-exit-direct" title="退出单聊，恢复总前台分诊" style="display:none;align-items:center;gap:6px;padding:8px 14px;background:#fff7ed;border:1px solid #fdba74;border-radius:999px;color:#c2410c;font-size:13px;cursor:pointer;">
              <span>✕ 退出单聊</span>
            </button>
            <button id="chat-canvas-toggle" title="打开 / 关闭 Canvas 文档面板"
              style="display:flex;align-items:center;gap:6px;padding:8px 14px;background:white;border:1px solid var(--border-default);border-radius:10px;cursor:pointer;font-size:13px;color:var(--text-secondary);font-family:inherit;transition:all 0.15s;flex-shrink:0;"
              onmouseover="this.style.borderColor='#171717';this.style.color='#171717'"
              onmouseout="this.style.borderColor='var(--border-default)';this.style.color='var(--text-secondary)'">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                <line x1="15" y1="3" x2="15" y2="21"></line>
              </svg>
              <span>Canvas</span>
            </button>
            </div>
          </header>

          <!-- 内容区（可滚动） -->
          <div id="chat-scroll-area" style="flex:1;overflow-y:auto;position:relative;z-index:1;">
            <!-- 空状态：居中欢迎页（粒子吉祥物 + 拟人问候,无建议问题） -->
            <div id="chat-empty" style="min-height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:32px;text-align:center;">
              <div class="chat-mascot-wrap">
                <canvas id="mascot-chat" aria-hidden="true"></canvas>
              </div>
              <h3 style="font-size:20px;font-weight:600;color:var(--text-primary);margin:0;">人，今天你有什么问题？</h3>
            </div>

            <!-- 消息列表（默认隐藏，发消息后显示） -->
            <div id="chat-messages" style="display:none;padding:24px 32px;max-width:768px;margin:0 auto;"></div>
          </div>

          <!-- 底部输入栏（大圆角卡片:上行输入框,下行 左附件 + 右发送,meta 行） -->
          <footer style="padding:12px 32px 14px;border-top:1px solid var(--border-light);background:rgba(255,255,255,0.85);backdrop-filter:blur(8px);flex-shrink:0;position:relative;z-index:1;">
            <div style="max-width:768px;margin:0 auto;">
              <div style="background:#F3F3F5;border-radius:24px;padding:10px 12px 8px;">
                <input id="chat-input" type="text" placeholder="向公司描述你的问题…"
                  style="width:100%;height:34px;background:transparent;border:none;font-size:14px;font-family:inherit;outline:none;color:var(--text-primary);padding:0 6px;box-sizing:border-box;">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-top:4px;">
                  <button title="附件（即将支持）" disabled
                    style="width:32px;height:32px;background:transparent;border:none;border-radius:50%;color:var(--text-tertiary);cursor:not-allowed;display:flex;align-items:center;justify-content:center;flex-shrink:0;">
                    <span class="material-symbols-outlined" style="font-size:20px;">add</span>
                  </button>
                  <button id="chat-send" title="发送"
                    style="width:36px;height:36px;background:var(--teal-600);border:none;border-radius:50%;color:white;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background 0.2s;flex-shrink:0;">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                      <line x1="12" y1="19" x2="12" y2="5"></line>
                      <polyline points="5 12 12 5 19 12"></polyline>
                    </svg>
                  </button>
                </div>
              </div>
              <div style="text-align:center;font-size:11px;color:var(--text-tertiary);margin-top:8px;">Enter 发送 · Shift+Enter 换行 · 由总前台智能分诊</div>
            </div>
          </footer>
        </main>

        <!-- ========== Canvas 侧边文档面板（默认隐藏） ========== -->
        <aside id="chat-canvas" class="chat-canvas-panel"
          style="width:480px;max-width:90vw;flex-shrink:0;background:white;border-left:1px solid var(--border-light);display:none;flex-direction:column;">
          <!-- 面板头部：标题 + 操作按钮 -->
          <div style="display:flex;align-items:center;gap:8px;padding:12px 16px;border-bottom:1px solid var(--border-light);flex-shrink:0;">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--text-tertiary);flex-shrink:0;">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
            </svg>
            <span id="chat-canvas-title" style="flex:1;font-size:14px;font-weight:600;color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">文档</span>
            <button id="chat-canvas-edit" title="编辑" onclick="ChatModule.toggleCanvasEdit()"
              style="width:30px;height:30px;background:white;border:1px solid var(--border-default);border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--text-secondary);">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"></path>
              </svg>
            </button>
            <button id="chat-canvas-copy" title="复制" onclick="ChatModule.copyCanvas()"
              style="width:30px;height:30px;background:white;border:1px solid var(--border-default);border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--text-secondary);font-size:11px;">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
              </svg>
            </button>
            <button id="chat-canvas-download" title="下载" onclick="ChatModule.downloadCanvas()"
              style="width:30px;height:30px;background:white;border:1px solid var(--border-default);border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--text-secondary);">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="7 10 12 15 17 10"></polyline>
                <line x1="12" y1="15" x2="12" y2="3"></line>
              </svg>
            </button>
            <button id="chat-canvas-close" title="关闭" onclick="ChatModule.closeCanvas()"
              style="width:30px;height:30px;background:white;border:1px solid var(--border-default);border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--text-secondary);font-size:15px;">×</button>
          </div>
          <!-- meta 行：语言 · 字符数 -->
          <div id="chat-canvas-meta" style="padding:8px 16px;font-size:11px;color:var(--text-tertiary);border-bottom:1px solid var(--border-light);flex-shrink:0;"></div>
          <!-- 内容区（查看 <pre> / 编辑 <textarea>） -->
          <div id="chat-canvas-body" style="flex:1;overflow:auto;padding:16px;"></div>
        </aside>
      </div>
    `;
  },

  /**
   * 注入新设计相关样式（一次性，独立于 tailwind.config，防止被覆盖后失效）
   */
  injectThemeStyle() {
    if (document.getElementById('chat-theme-style')) return;
    const style = document.createElement('style');
    style.id = 'chat-theme-style';
    style.textContent = `
      /* 空状态粒子吉祥物（带 teal 光晕） */
      .chat-mascot-wrap { position: relative; width: 132px; height: 132px; margin-bottom: 18px; }
      .chat-mascot-wrap::before {
        content: ''; position: absolute; inset: -16px; border-radius: 50%;
        background: radial-gradient(circle, rgba(13,148,136,0.16), transparent 70%);
        pointer-events: none;
      }
      #mascot-chat { width: 132px; height: 132px; display: block; position: relative; }

      /* Markdown 代码块/表格卡片(header 条 + 图标按钮,参考主流 AI 聊天输出) */
      .md-code-card, .md-table-card { margin: 12px 0; border: 1px solid #E3EEEB; border-radius: 14px; overflow: hidden; box-shadow: 0 1px 3px rgba(15,94,89,0.05); }
      .md-card-head { display: flex; align-items: center; gap: 6px; padding: 6px 10px 6px 14px; background: #F7FAF9; border-bottom: 1px solid #E3EEEB; }
      .md-card-head-label { flex: 1; font-size: 12px; font-weight: 600; color: #6B7F7B; font-family: ui-monospace, Menlo, Monaco, Consolas, monospace; }
      .md-icon-btn { display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; background: transparent; border: none; border-radius: 7px; color: #8A9B97; cursor: pointer; padding: 0; transition: background 0.15s, color 0.15s; }
      .md-icon-btn:hover { background: #E4F0ED; color: #0F766E; }
      .md-icon-btn .material-symbols-outlined { font-size: 16px; }

      /* Canvas 面板滚动条 */
      #chat-canvas-body::-webkit-scrollbar { width: 6px; }
      #chat-canvas-body::-webkit-scrollbar-thumb { background: #D1D5DB; border-radius: 3px; }

      /* 窄屏时 Canvas 改覆盖式（absolute + 阴影） */
      @media (max-width: 1200px) {
        .chat-canvas-panel {
          position: absolute !important; right: 0; top: 0; bottom: 0; height: 100%;
          z-index: 30; box-shadow: -12px 0 40px rgba(0,0,0,0.15);
        }
      }
    `;
    document.head.appendChild(style);
  },

  /**
   * 绑定全局事件（输入、发送、新建、Canvas 开关）
   */
  bindEvents() {
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('chat-send');
    const newBtn = document.getElementById('chat-new-session');
    const canvasToggle = document.getElementById('chat-canvas-toggle');

    if (input) {
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          this.sendMessage(input.value);
        }
      });
    }

    if (sendBtn) {
      sendBtn.addEventListener('click', () => {
        // 流式期间按钮语义切换为「停止生成」
        if (this.isStreaming) { this.stopStreaming(); return; }
        if (input) this.sendMessage(input.value);
      });
    }

    if (newBtn) {
      newBtn.addEventListener('click', () => this.startNewSession());
    }

    if (canvasToggle) {
      canvasToggle.addEventListener('click', () => this.toggleCanvas());
    }

    // 退出单聊：回到总前台分诊（新建无绑定会话）
    const exitDirect = document.getElementById('chat-exit-direct');
    if (exitDirect) {
      exitDirect.addEventListener('click', () => this.startNewSession());
    }

    // 监听用户滚动：上翻超过 60px 视为离开底部，暂停流式吸底；回到底部附近自动恢复
    const scrollArea = document.getElementById('chat-scroll-area');
    if (scrollArea) {
      scrollArea.addEventListener('scroll', () => {
        const gap = scrollArea.scrollHeight - scrollArea.scrollTop - scrollArea.clientHeight;
        this._stickBottom = gap < 60;
      });
    }
  },

  // ============================================================
  // 多会话持久化
  // ============================================================

  /**
   * 从后端加载会话列表（失败时降级为纯本地模式，不阻塞页面）
   */
  async loadSessions() {
    try {
      const res = await fetch('/api/frontdesk/sessions');
      if (!res.ok) throw new Error('sessions API 失败');
      const list = await res.json();
      this.sessions = {};
      for (const s of list) {
        this.sessions[s.id] = {
          id: s.id,
          title: s.title || '对话',
          messages: null,        // null = 未加载（切换时懒加载历史消息）
          route: null,
          preview: s.preview || '',
          createdAt: new Date(s.created_at || Date.now()),
        };
      }
      this.renderSidebar();
    } catch (e) {
      console.warn('[chat] 会话列表加载失败，降级为本地模式', e);
    }
  },

  /**
   * 新建会话（纯本地；首条消息发出时后端以前端 id 入库）
   * @param {string|null} agentId 定向员工 id（单聊会话），null 表示总前台分诊
   */
  startNewSession(agentId = null) {
    const id = 'sess_' + Date.now();
    this.sessions[id] = {
      id,
      title: '新对话',
      messages: [],
      route: null,        // 分诊链路数据
      preview: '',
      createdAt: new Date(),
      agentId,            // 会话级单聊绑定（null = 总前台分诊）
    };
    this.currentSessionId = id;
    this.pendingAgentId = null;   // 新会话清除消息级定向（单聊走会话级 agentId）
    this._stickBottom = true;     // 新会话恢复吸底
    this.closeCanvas();
    this.renderSidebar();
    this.renderMessages();
    this.showEmpty();
    this.updateDirectHeader();

    // 聚焦输入框
    setTimeout(() => {
      const input = document.getElementById('chat-input');
      if (input) input.focus();
    }, 50);
  },

  /**
   * 发起单聊：新建一个绑定指定员工的干净会话并跳转聊天页
   */
  async startDirectChat(agentId) {
    // 首次进入前台页时先等初始化完成，否则 init 恢复的会话会覆盖单聊会话
    await this.init();
    this.startNewSession(agentId);
    const agent = (typeof _cache !== 'undefined' && _cache.agents || []).find(a => a.id === agentId);
    if (agent) {
      const sess = this.sessions[this.currentSessionId];
      sess.title = `与 ${agent.name} 单聊`;
      this.renderSidebar();
      this.updateDirectHeader();
    }
  },

  /**
   * 按当前会话的单聊绑定更新头部标题/副标题、退出按钮显隐与输入框占位
   */
  updateDirectHeader() {
    const sess = this.sessions[this.currentSessionId];
    const agent = sess && sess.agentId
      ? (typeof _cache !== 'undefined' && _cache.agents || []).find(a => a.id === sess.agentId)
      : null;
    const titleEl = document.getElementById('chat-header-title');
    const subEl = document.getElementById('chat-header-sub');
    const exitBtn = document.getElementById('chat-exit-direct');
    const input = document.getElementById('chat-input');
    if (agent) {
      if (titleEl) titleEl.innerHTML = `<span style="display:inline-flex;align-items:center;gap:8px;">${typeof cuteAvatar === 'function' ? cuteAvatar(agent.name, agent.emoji, 30) : (agent.emoji || '')}<span>${agent.name}</span></span>`;
      if (subEl) subEl.textContent = `单聊模式 · ${agent.title || agent.role || ''} · 绕过总前台分诊`;
      if (exitBtn) exitBtn.style.display = 'inline-flex';
      if (input) input.placeholder = `直接向 ${agent.name} 提问…`;
    } else {
      if (titleEl) titleEl.textContent = '总前台';
      if (subEl) subEl.textContent = '描述你的问题，我会为你分诊给最合适的员工';
      if (exitBtn) exitBtn.style.display = 'none';
      if (input) input.placeholder = '描述你的问题，总前台为你分诊…';
    }
  },

  /**
   * 切换会话（messages 为 null 时从后端懒加载历史消息）
   */
  async switchSession(sessionId) {
    const sess = this.sessions[sessionId];
    if (!sess) return;
    this.currentSessionId = sessionId;
    this._stickBottom = true;     // 切换会话恢复吸底
    this.closeCanvas();
    this.renderSidebar();

    if (sess.messages === null) {
      // 懒加载：先置空渲染，再拉取历史消息
      sess.messages = [];
      this.renderMessages();
      try {
        const res = await fetch(`/api/frontdesk/sessions/${sessionId}/messages`);
        if (!res.ok) throw new Error('messages API 失败');
        const list = await res.json();
        sess.messages = list.map(m => ({
          role: m.role,
          content: m.content,
          messageId: m.id,            // 点赞/点踩回传用
          feedback: m.feedback || '', // 历史评价状态回显
          agentName: m.agent_name,
          agentEmoji: m.agent_emoji,
          department: m.department,
          domain: m.domain,
          streaming: false,
          tools: [],           // 工具调用未持久化，历史消息不渲染工具折叠区
          route: m.role === 'assistant' ? {
            agentName: m.agent_name,
            agentEmoji: m.agent_emoji,
            department: m.department,
            domain: m.domain,
            confidence: m.confidence || '中',
          } : null,
        }));
      } catch (e) {
        console.warn('[chat] 历史消息加载失败', e);
      }
    }

    this.renderMessages();
    this.updateDirectHeader();
  },

  /**
   * 删除会话（先调后端，幂等；再删本地）
   */
  async deleteSession(sessionId) {
    try {
      await fetch(`/api/frontdesk/sessions/${sessionId}`, { method: 'DELETE' });
    } catch (e) {
      console.warn('[chat] 后端删除会话失败（本地仍删除）', e);
    }
    delete this.sessions[sessionId];
    if (this.currentSessionId === sessionId) {
      this.closeCanvas();
      const keys = Object.keys(this.sessions);
      if (keys.length > 0) {
        this.currentSessionId = keys[0];
        this.renderSidebar();
        await this.switchSession(keys[0]);
        return;
      } else {
        this.startNewSession();
        return;
      }
    }
    this.renderSidebar();
  },

  /**
   * 渲染会话侧栏列表
   */
  renderSidebar() {
    const list = document.getElementById('chat-session-list');
    if (!list) return;

    const sessionList = Object.values(this.sessions).sort((a, b) => b.createdAt - a.createdAt);

    if (sessionList.length === 0) {
      list.innerHTML = '<div style="padding:32px 16px;text-align:center;color:var(--text-tertiary);font-size:13px;">暂无对话</div>';
      return;
    }

    list.innerHTML = sessionList.map(s => {
      const isActive = s.id === this.currentSessionId;
      // messages 可能为 null（未加载），优先取最后一条消息，否则用后端 preview
      const lastMsg = (s.messages && s.messages.length > 0) ? s.messages[s.messages.length - 1] : null;
      const preview = lastMsg ? (lastMsg.content || '...').slice(0, 28) : (s.preview ? s.preview.slice(0, 28) : '新对话');

      return `
        <div onclick="ChatModule.switchSession('${s.id}')"
          style="padding:8px 10px;border-radius:8px;cursor:pointer;margin-bottom:2px;background:${isActive ? 'var(--brand-primary-light)' : 'transparent'};border-left:${isActive ? '3px solid var(--brand-primary)' : '3px solid transparent'};transition:background 0.15s;"
          onmouseover="if(!${isActive})this.style.background='#F3F4F6'"
          onmouseout="if(!${isActive})this.style.background='transparent'">
          <div style="display:flex;align-items:center;gap:8px;">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--text-tertiary);flex-shrink:0;">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
            </svg>
            <span style="flex:1;font-size:13px;font-weight:${isActive ? '500' : '400'};color:${isActive ? 'var(--brand-primary)' : 'var(--text-primary)'};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${this.escape(s.title)}</span>
            ${isActive ? `
              <span onclick="event.stopPropagation();ChatModule.deleteSession('${s.id}')"
                style="font-size:14px;color:var(--text-tertiary);cursor:pointer;flex-shrink:0;padding:0 4px;"
                onmouseover="this.style.color='#dc2626'"
                onmouseout="this.style.color='var(--text-tertiary)'">×</span>
            ` : ''}
          </div>
          <div style="font-size:11px;color:var(--text-tertiary);margin-top:2px;padding-left:22px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${this.escape(preview)}</div>
        </div>
      `;
    }).join('');
  },

  /**
   * 时间格式化
   */
  formatTime(date) {
    if (!date) return '';
    const now = new Date();
    const diff = (now - date) / 1000;
    if (diff < 60) return '刚刚';
    if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
    if (diff < 86400) return date.getHours().toString().padStart(2, '0') + ':' + date.getMinutes().toString().padStart(2, '0');
    return (date.getMonth() + 1) + '/' + date.getDate();
  },

  /**
   * 初始化聊天空态粒子吉祥物（惰性创建；init 因 _initPromise 只跑一次，canvas 不会被重建，无上下文泄漏）
   * WebGL 不可用时 createParticleFace 返回 null，静默跳过（空态仅剩问候语）
   */
  initChatMascot() {
    const canvas = document.getElementById('mascot-chat');
    if (!canvas || canvas.dataset.mascotInit || typeof window.createParticleFace !== 'function') return;
    canvas.dataset.mascotInit = '1';
    // 浅底场景:用浅底配色预设(teal 本体),否则白色粒子在浅底上不显形
    this._chatMascot = window.createParticleFace(canvas, { particleCount: 6000, config: window.PF_LIGHT_BG_CONFIG });
  },

  /**
   * 显示/隐藏空状态
   */
  showEmpty() {
    const empty = document.getElementById('chat-empty');
    const messages = document.getElementById('chat-messages');
    if (empty) empty.style.display = 'flex';
    if (messages) messages.style.display = 'none';
    // 空态重新显示时重播吉祥物入场动画(隐藏期创建会跳过入场)
    if (this._chatMascot) this._chatMascot.replay();
  },

  hideEmpty() {
    const empty = document.getElementById('chat-empty');
    const messages = document.getElementById('chat-messages');
    if (empty) empty.style.display = 'none';
    if (messages) messages.style.display = 'block';
  },

  // ============================================================
  // Canvas 侧边文档面板
  // ============================================================

  /**
   * 打开 Canvas 面板并展示内容
   * @param {{title: string, lang: string, content: string}} doc 文档对象
   */
  openCanvas(doc) {
    this.canvas.open = true;
    this.canvas.editing = false;
    this.canvas.title = doc.title || '文档';
    this.canvas.lang = doc.lang || 'text';
    this.canvas.content = doc.content || '';
    this.renderCanvas();
  },

  /**
   * 从代码块/长文暂存区打开 Canvas（按钮 onclick 按索引取用，避免大文本塞进 DOM 属性）
   */
  openCanvasFromBlock(idx) {
    const b = this._blockStore[idx];
    if (!b) return;
    const isMarkdown = b.lang === 'markdown';
    this.openCanvas({
      title: isMarkdown ? '回答全文' : (b.lang && b.lang !== 'text' ? `${b.lang} 代码` : '代码块'),
      lang: b.lang || 'text',
      content: b.code,
    });
  },

  /**
   * 开关 Canvas 面板（header 按钮）
   */
  toggleCanvas() {
    if (this.canvas.open) {
      this.closeCanvas();
    } else {
      this.canvas.open = true;
      this.canvas.editing = false;
      this.renderCanvas();
    }
  },

  /**
   * 关闭 Canvas 面板
   */
  closeCanvas() {
    this.canvas.open = false;
    this.canvas.editing = false;
    const panel = document.getElementById('chat-canvas');
    if (panel) panel.style.display = 'none';
  },

  /**
   * 渲染 Canvas 面板（查看 / 编辑两种模式）
   */
  renderCanvas() {
    const panel = document.getElementById('chat-canvas');
    if (!panel) return;
    panel.style.display = this.canvas.open ? 'flex' : 'none';
    if (!this.canvas.open) return;

    const titleEl = document.getElementById('chat-canvas-title');
    const metaEl = document.getElementById('chat-canvas-meta');
    const bodyEl = document.getElementById('chat-canvas-body');
    if (titleEl) titleEl.textContent = this.canvas.title;
    if (metaEl) metaEl.textContent = `${this.canvas.lang || 'text'} · ${this.canvas.content.length} 字符`;

    if (!bodyEl) return;

    if (!this.canvas.content && !this.canvas.editing) {
      // 无内容占位
      bodyEl.innerHTML = `
        <div style="height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--text-tertiary);text-align:center;padding:24px;">
          <div style="font-size:32px;margin-bottom:12px;"><span class="material-symbols-outlined" style="font-size:32px;vertical-align:-2px;">description</span></div>
          <div style="font-size:13px;line-height:1.8;">暂无文档<br>AI 回答中的代码块或长文，可点击「在 Canvas 中打开」在此查看和编辑</div>
        </div>`;
      return;
    }

    if (this.canvas.editing) {
      // 编辑模式：textarea + 保存/取消
      bodyEl.innerHTML = `
        <div style="display:flex;flex-direction:column;height:100%;">
          <textarea id="chat-canvas-textarea"
            style="flex:1;min-height:280px;background:#FAFAFA;border:1px solid var(--border-default);border-radius:12px;padding:14px;font-family:ui-monospace,Menlo,Monaco,Consolas,monospace;font-size:13px;line-height:20px;resize:none;outline:none;color:var(--text-primary);">${this.escape(this.canvas.content)}</textarea>
          <div style="display:flex;gap:8px;margin-top:12px;flex-shrink:0;">
            <button onclick="ChatModule.saveCanvasEdit()"
              style="padding:8px 18px;background:var(--teal-700);border:none;border-radius:999px;color:white;font-size:13px;cursor:pointer;font-family:inherit;">保存</button>
            <button onclick="ChatModule.cancelCanvasEdit()"
              style="padding:8px 18px;background:white;border:1px solid var(--border-soft);border-radius:999px;color:var(--text-secondary);font-size:13px;cursor:pointer;font-family:inherit;">取消</button>
          </div>
        </div>`;
    } else {
      // 查看模式：等宽 pre
      bodyEl.innerHTML = `<pre style="margin:0;background:#FAFAFA;border:1px solid var(--border-light);border-radius:12px;padding:14px;font-family:ui-monospace,Menlo,Monaco,Consolas,monospace;font-size:13px;line-height:20px;color:var(--text-primary);white-space:pre-wrap;word-break:break-word;">${this.escape(this.canvas.content)}</pre>`;
    }
  },

  /**
   * 切换 Canvas 编辑模式
   */
  toggleCanvasEdit() {
    if (!this.canvas.open) return;
    this.canvas.editing = !this.canvas.editing;
    this.renderCanvas();
  },

  /**
   * 保存 Canvas 编辑内容
   */
  saveCanvasEdit() {
    const ta = document.getElementById('chat-canvas-textarea');
    if (ta) this.canvas.content = ta.value;
    this.canvas.editing = false;
    this.renderCanvas();
  },

  /**
   * 取消 Canvas 编辑
   */
  cancelCanvasEdit() {
    this.canvas.editing = false;
    this.renderCanvas();
  },

  /**
   * 复制 Canvas 内容（复制后按钮短暂显示"已复制"）
   */
  async copyCanvas() {
    if (!this.canvas.content) return;
    try {
      await navigator.clipboard.writeText(this.canvas.content);
      const btn = document.getElementById('chat-canvas-copy');
      if (btn) {
        const old = btn.innerHTML;
        btn.innerHTML = '<span style="font-size:10px;color:#059669;">已复制</span>';
        setTimeout(() => { btn.innerHTML = old; }, 1200);
      }
    } catch (e) {
      console.warn('[chat] 复制失败', e);
    }
  },

  /**
   * 下载 Canvas 内容（扩展名按语言映射，默认 .txt）
   */
  downloadCanvas() {
    if (!this.canvas.content) return;
    const extMap = {
      python: 'py', py: 'py', javascript: 'js', js: 'js', typescript: 'ts', ts: 'ts',
      html: 'html', css: 'css', json: 'json', markdown: 'md', md: 'md', sql: 'sql',
      bash: 'sh', sh: 'sh', shell: 'sh', java: 'java', go: 'go', rust: 'rs',
      cpp: 'cpp', c: 'c', yaml: 'yml', yml: 'yml', xml: 'xml', text: 'txt',
    };
    const ext = extMap[(this.canvas.lang || '').toLowerCase()] || 'txt';
    const blob = new Blob([this.canvas.content], { type: 'text/plain;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `canvas_${Date.now()}.${ext}`;
    a.click();
    URL.revokeObjectURL(a.href);
  },

  // ============================================================
  // 消息发送与 SSE 流式
  // ============================================================

  /**
   * 发送消息
   */
  async sendMessage(text) {
    text = (text || '').trim();
    if (!text || this.isStreaming) return;

    if (!this.currentSessionId || !this.sessions[this.currentSessionId]) {
      this.startNewSession();
    }

    const session = this.sessions[this.currentSessionId];
    const input = document.getElementById('chat-input');
    if (input) input.value = '';

    // 历史会话懒加载未完成时 messages 可能为 null，兜底
    if (!session.messages) session.messages = [];

    // 用户消息入队
    session.messages.push({ role: 'user', content: text });

    // 第一条消息 → 更新会话标题（后端入库时也会同步）
    if (session.messages.length === 1) {
      session.title = text.slice(0, 20) + (text.length > 20 ? '…' : '');
    }

    // AI 占位消息
    const aiMsg = {
      role: 'assistant',
      content: '',
      agentName: '',
      agentEmoji: '',
      department: '',
      domain: '',
      route: null,          // 本条消息的分诊信息（route.decided 后填充）
      streaming: true,
    };
    session.messages.push(aiMsg);

    // 重置分诊链路
    session.route = null;

    // 用户主动发消息时强制钉回底部;流式期间关闭平滑滚动动画,避免 chunk 高频触发导致抖动
    this._stickBottom = true;
    const scrollArea = document.getElementById('chat-scroll-area');
    if (scrollArea) scrollArea.style.scrollBehavior = 'auto';

    this.hideEmpty();
    this.renderMessages();
    this.renderSidebar();
    this.isStreaming = true;
    this.updateSendButton(true);
    this._abortCtrl = new AbortController();   // 停止按钮的中止句柄

    try {
      await this.streamResponse(text, session, aiMsg);
    } catch (e) {
      if (e.name === 'AbortError') {
        // 用户手动停止:保留已生成内容,追加停止标记
        aiMsg.content = aiMsg.content ? aiMsg.content + '\n\n（已手动停止生成）' : '（已手动停止生成）';
      } else {
        aiMsg.content = `⚠ 回答失败：${e.message}`;
      }
      aiMsg.streaming = false;
      this.renderMessages();
    } finally {
      this.isStreaming = false;
      this._abortCtrl = null;
      this.updateSendButton(false);
      this.renderSidebar();
      // 流式结束恢复平滑滚动(切会话等场景保留动画)
      if (scrollArea) scrollArea.style.scrollBehavior = '';
    }
  },

  /**
   * SSE 流式接收 — 解析 route.decided / tool.start / tool.result / answer.chunk / answer.completed
   */
  async streamResponse(question, session, aiMsg) {
    const res = await fetch('/api/frontdesk/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: this._abortCtrl?.signal,   // 停止按钮 → abort → 断开 SSE,后端生成随连接取消
      body: JSON.stringify({
        question,
        session_id: session.id,
        agent_id: session.agentId || this.pendingAgentId || null,   // 会话级单聊绑定优先，兼容消息级定向
      }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split('\n\n');
      buffer = events.pop() || '';

      for (const evt of events) {
        const lines = evt.split('\n');
        let eventType = '';
        let eventData = '';

        for (const line of lines) {
          if (line.startsWith('event: ')) eventType = line.slice(7);
          else if (line.startsWith('data: ')) eventData = line.slice(6);
        }

        if (!eventType || !eventData) continue;

        try {
          const data = JSON.parse(eventData);

          if (eventType === 'route.decided') {
            // 构建分诊链路数据（session 级 + 消息级各存一份）
            session.route = {
              agentName: data.agent_name || '未分配',
              agentEmoji: data.agent_emoji || '🤖',
              department: data.department || '',
              domain: data.domain || '',
              confidence: data.confidence || '中',
            };
            aiMsg.route = session.route;
            aiMsg.agentName = session.route.agentName;
            aiMsg.agentEmoji = session.route.agentEmoji;
            aiMsg.department = session.route.department;
            aiMsg.domain = session.route.domain;
            aiMsg.tools = []; // 工具调用记录
            this.renderMessages();
          } else if (eventType === 'tool.start') {
            // 工具调用开始:增量追加叙事行,不触发全量渲染(消除卡顿)
            aiMsg.tools = aiMsg.tools || [];
            aiMsg.tools.push({ name: data.name, arguments: data.arguments, status: 'running', result: '' });
            aiMsg.toolActive = true;
            this.streamToolStart(aiMsg, aiMsg.tools.length - 1);
          } else if (eventType === 'tool.result') {
            // 工具调用结果:只重绘对应那一行
            if (aiMsg.tools && aiMsg.tools.length > 0) {
              const lastTool = aiMsg.tools[aiMsg.tools.length - 1];
              lastTool.status = data.is_error ? 'error' : 'done';
              lastTool.result = data.result || '';
              this.streamToolResult(aiMsg, aiMsg.tools.length - 1);
            }
            aiMsg.toolActive = false;
          } else if (eventType === 'answer.chunk') {
            aiMsg.content += data.content;
            this.scheduleStreamRender();   // 节流渲染,避免 chunk 高频触发全文重建
          } else if (eventType === 'answer.completed') {
            aiMsg.content = data.full_answer;
            aiMsg.streaming = false;
            aiMsg.toolsUsed = data.tools_used || [];
            aiMsg.iterations = data.iterations || 0;
            // 回答已持久化,记录消息 id 供点赞/点踩回传(总览采纳率数据源)
            aiMsg.messageId = data.message_id || null;
            aiMsg.feedback = '';
            // 跨领域建议(命中 >=2 个领域时后端返回领域名列表,用于「转为协作任务」入口)
            aiMsg.suggestCollab = data.suggest_collab || [];
            // 后端重新分配 session_id 时同步 re-key，避免侧栏出现重复会话
            if (data.session_id && data.session_id !== session.id) {
              const oldId = session.id;
              session.id = data.session_id;
              if (this.sessions[oldId] === session) {
                delete this.sessions[oldId];
                this.sessions[session.id] = session;
              }
              if (this.currentSessionId === oldId) this.currentSessionId = session.id;
              this.renderSidebar();
            }
            this.renderMessages();
          } else if (eventType === 'error') {
            // 保留已渲染的部分内容,追加错误提示(整段替换会丢失流式已产出文本)
            const warn = `\n\n> ⚠ ${data.message}(以上内容可能不完整)`;
            aiMsg.content = aiMsg.content ? aiMsg.content + warn : `⚠ ${data.message}`;
            aiMsg.streaming = false;
            this.renderMessages();
          }
        } catch (e) {
          console.warn('[chat] SSE parse', e);
        }
      }
    }

    aiMsg.streaming = false;
    this.renderMessages();
  },

  /**
   * 手动停止流式生成(中断 SSE 连接,后端生成随连接断开而取消)
   */
  stopStreaming() {
    if (this._abortCtrl) this._abortCtrl.abort();
  },

  /**
   * 流式渲染节流:chunk 高频到达时不逐片全量重渲染,
   * 合并到 ~90ms 一帧的节奏(对齐 rAF),消除全文 Markdown + innerHTML 重建造成的卡顿;
   * 完成/工具事件仍走 updateLastMessage() 即时渲染,不受节流影响
   */
  scheduleStreamRender() {
    if (this._renderScheduled) return;
    this._renderScheduled = true;
    const wait = Math.max(0, 90 - (performance.now() - this._lastStreamRender));
    setTimeout(() => {
      requestAnimationFrame(() => {
        this._renderScheduled = false;
        this._lastStreamRender = performance.now();
        this.updateLastMessage();
      });
    }, wait);
  },

  /**
   * 只更新最后一条消息的内容（流式优化，避免重渲染整个列表）
   */
  updateLastMessage() {
    const session = this.sessions[this.currentSessionId];
    if (!session) return;
    // 流式消息的内容容器带固定 id(renderAnswerCard 保证其始终存在),按 id 精确定位;
    // 不能用 .ai-answer-content:last-child——每条旧消息都满足 :last-child,会写串到上一条
    const msgEl = document.getElementById('ai-streaming-content');
    if (msgEl) {
      const lastMsg = session.messages[session.messages.length - 1];
      if (lastMsg) {
        // 流式期间同样跑完整 Markdown(未闭合的 ``` 临时补尾),
        // 避免回答过程中裸露原始标记,完成后再由 renderMessages() 统一精修
        msgEl.innerHTML = this.renderStreamMarkdown(lastMsg.content);
      }
    }
    // 仅当用户钉在底部时才自动跟随(上翻阅读时不拽回)
    this.scrollToBottomIfPinned();
  },

  /**
   * 流式期间的 Markdown 渲染:代码块围栏为奇数个时临时补一个闭合 ```,
   * 让半截代码块也能渲染成代码样式而不是裸露围栏字符
   */
  renderStreamMarkdown(text) {
    if (!text) return '';
    let t = text;
    const fenceCount = (t.match(/```/g) || []).length;
    if (fenceCount % 2 === 1) t += '\n```';
    return this.renderMarkdown(t);
  },

  /**
   * 用户钉在底部时才吸底跟随(配合 _stickBottom 标志)
   */
  scrollToBottomIfPinned() {
    if (!this._stickBottom) return;
    const scroll = document.getElementById('chat-scroll-area');
    if (scroll) scroll.scrollTop = scroll.scrollHeight;
  },

  /**
   * 渲染当前会话的消息列表（包括分诊链路）
   * 核心设计：
   *   - 用户问题右对齐气泡
   *   - AI 回答：3 层分诊链路（若有） + 员工答卡片
   *   - 分诊链路数据源：优先 msg.route（每条历史消息各自带卡片），流式中最后一条回退 session.route
   */
  renderMessages() {
    const session = this.sessions[this.currentSessionId];
    if (!session) return;

    const container = document.getElementById('chat-messages');
    if (!container) return;

    // 每次全量渲染重置代码块暂存区（renderMarkdown / renderAnswerCard 会按序重新填充，索引稳定）
    this._blockStore = [];

    if (!session.messages || session.messages.length === 0) {
      this.showEmpty();
      return;
    }

    this.hideEmpty();

    // 如果最后一条是 AI 消息且 route 已知，先渲染分诊链路
    const lastAi = [...session.messages].reverse().find(m => m.role === 'assistant');

    container.innerHTML = session.messages.map((msg, idx) => {
      if (msg.role === 'user') {
        // 用户消息：右对齐深色气泡
        return `
          <div style="display:flex;justify-content:flex-end;margin-bottom:24px;">
            <div style="max-width:75%;background:#F3F3F5;color:var(--text-primary);padding:12px 16px;border-radius:14px 14px 4px 14px;font-size:14px;line-height:22px;">${this.escape(msg.content)}</div>
          </div>
        `;
      }

      // AI 消息：优先消息自身的 route，流式中最后一条回退 session.route
      const isLastAi = (msg === lastAi);
      const route = msg.route || (isLastAi ? session.route : null);

      // 分诊链路（3 层）,单聊模式(直连员工,绕过总前台)不显示
      const routeHtml = (route && !session.agentId) ? this.renderRouteChain(route) : '';

      // 员工答卡片(idx 用于「转为协作任务」定位对应的用户提问)
      const cardHtml = this.renderAnswerCard(msg, route, idx);

      return `
        <div style="display:flex;justify-content:flex-start;margin-bottom:24px;">
          <div style="max-width:100%;width:100%;">
            ${routeHtml}
            ${cardHtml}
          </div>
        </div>
      `;
    }).join('');

    // 仅当用户钉在底部时才滚动到底（用户上翻阅读时不打断）
    this.scrollToBottomIfPinned();
  },

  /**
   * 渲染 3 层分诊链路
   *   总前台 → 部门对接人 → 领域员工
   */
  renderRouteChain(route) {
    const deptText = route.department
      ? `已接待并识别意图，分诊到「${this.escape(route.department)}」（置信度 ${this.escape(route.confidence || '中')}）`
      : '已接待并识别意图';
    const domainText = route.domain
      ? `在部门内定位到「${this.escape(route.domain)}」→ 员工「${this.escape(route.agentName)}」`
      : '';
    const agentText = route.agentName
      ? `${this.escape(route.agentName)} 已在授权资源范围内完成检索与取证`
      : '';

    const stepStyle = 'display:flex;align-items:center;gap:8px;padding:6px 0;font-size:13px;color:var(--text-secondary);';
    const badgeStyle = 'display:inline-flex;align-items:center;padding:3px 9px;border-radius:12px;font-size:11px;font-weight:500;background:var(--brand-primary-light);color:var(--brand-primary);';
    const arrowStyle = 'color:var(--text-tertiary);flex-shrink:0;';

    return `
      <div style="background:#FAFBFC;border:1px solid var(--border-light);border-radius:12px;padding:12px 16px;margin-bottom:12px;">
        <!-- 第 1 层：总前台 -->
        <div style="${stepStyle}">
          <span style="${badgeStyle}">总前台</span>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="${arrowStyle}">
            <polyline points="9 18 15 12 9 6"></polyline>
          </svg>
          <span>${deptText}</span>
        </div>
        ${domainText ? `
        <!-- 第 2 层：部门对接人 -->
        <div style="${stepStyle}">
          <span style="${badgeStyle}">部门对接人</span>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="${arrowStyle}">
            <polyline points="9 18 15 12 9 6"></polyline>
          </svg>
          <span>${domainText}</span>
        </div>` : ''}
        ${agentText ? `
        <!-- 第 3 层：领域员工 -->
        <div style="${stepStyle}">
          <span style="${badgeStyle}">领域员工</span>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="${arrowStyle}">
            <polyline points="9 18 15 12 9 6"></polyline>
          </svg>
          <span>${agentText}</span>
        </div>` : ''}
      </div>
    `;
  },

  /**
   * 工具调用叙事文案(方案 A:技术日志 → 思考过程)
   * 内置工具逐一映射为自然语言;MCP/未知工具兜底「调用 工具名」
   */
  toolNarrative(t) {
    const args = t.arguments || {};
    const esc = (s) => this.escape(String(s ?? ''));
    // 路径只显文件名,完整路径折叠进详情(默认折叠长路径)
    const basename = (p) => {
      const s = String(p || '').replace(/\\/g, '/');
      return esc(s.split('/').pop() || s);
    };
    switch (t.name) {
      case 'searchCode': return `搜索关键词 “${esc(args.query)}”`;
      case 'searchInDocs': return `在文档中搜索 “${esc(args.query)}”`;
      case 'getCodeExcerpt': return `查看 ${basename(args.file_path)}`;
      case 'listFiles': return `浏览 ${args.subdir ? esc(args.subdir) : '根'}目录`;
      case 'getProjectStructure': return '分析项目结构';
      case 'searchKnowledge': return `检索知识库 “${esc(args.query)}”`;
      case 'getEmployeeInfo': return args.query ? `查找员工 “${esc(args.query)}”` : '查看员工列表';
      case 'searchResource': return args.keyword ? `查找资源 “${esc(args.keyword)}”` : '查看资源列表';
      case 'cloneRepo': return `拉取仓库 ${esc(args.repo_id || args.clone_url)}`;
      case 'loadSkill': return `加载能力 ${esc(args.skill_key)}`;
      default: return `调用 ${esc(t.name)}`;
    }
  },

  /**
   * 从工具结果首行提取统计摘要(后端各工具首行均为「找到 N 处匹配/个文件/条知识…」格式)
   */
  toolResultSummary(t) {
    if (!t.result) return '';
    const firstLine = String(t.result).split('\n')[0] || '';
    const m = firstLine.match(/找到\s*\d+\s*[^\s:：,，]+/);
    if (m) return `→ ${m[0]}`;
    if (/未找到/.test(firstLine)) return '→ 未找到';
    return '';
  },

  /** 流式期间的「正在分析」标题行(容器内固定 id,去重判断用) */
  toolStreamHeader(msg) {
    const name = this.escape(msg.agentName || '员工');
    return `<div id="ai-tools-header" style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
      <span style="display:inline-block;width:10px;height:10px;border:2px solid var(--text-tertiary);border-top-color:transparent;border-radius:50%;animation:chat-spin 0.8s linear infinite;"></span>
      <span style="font-size:12px;color:var(--text-tertiary);">${name} 正在分析您的需求…</span>
    </div>`;
  },

  /**
   * 渲染一条工具叙事行(树形前缀 + 状态图标 + 叙事 + 结果摘要;点击展开完整参数与结果原文)
   */
  renderToolNarrativeLine(msg, t, idx) {
    const isLast = idx === msg.tools.length - 1;
    const statusIcon = t.status === 'running'
      ? '<span style="display:inline-block;width:10px;height:10px;border:2px solid var(--text-tertiary);border-top-color:transparent;border-radius:50%;animation:chat-spin 0.8s linear infinite;flex-shrink:0;"></span>'
      : t.status === 'error'
        ? '<span style="color:#DC2626;font-size:12px;flex-shrink:0;">✕</span>'
        : '<span style="color:#059669;font-size:12px;flex-shrink:0;">✓</span>';
    const summary = t.status === 'done' ? this.toolResultSummary(t)
      : t.status === 'error' ? '→ 执行失败' : '';
    const summaryColor = t.status === 'error' ? '#DC2626' : 'var(--text-tertiary)';
    const argStr = t.arguments ? Object.entries(t.arguments).map(([k, v]) => `${k}=${v}`).join(', ') : '';

    return `<div class="tool-line" style="margin-bottom:2px;">
      <div style="display:flex;align-items:center;gap:6px;padding:3px 6px;border-radius:6px;cursor:pointer;transition:background 0.15s;"
           onclick="ChatModule.toggleToolLineDetail(this)"
           onmouseover="this.style.background='var(--bg-page)'" onmouseout="this.style.background=''">
        <span class="tool-line-prefix" style="color:var(--text-tertiary);font-size:12px;font-family:monospace;flex-shrink:0;">${isLast ? '└─' : '├─'}</span>
        ${statusIcon}
        <span style="font-size:13px;color:var(--text-secondary);">${this.toolNarrative(t)}</span>
        ${summary ? `<span style="font-size:12px;color:${summaryColor};margin-left:2px;flex-shrink:0;">${summary}</span>` : ''}
      </div>
      <div class="tool-line-detail" style="display:none;margin:2px 0 4px 30px;padding:8px 10px;background:var(--bg-input);border-radius:6px;font-size:11px;color:var(--text-secondary);font-family:monospace;max-height:160px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;">
        ${argStr ? `<div style="margin-bottom:6px;color:var(--text-tertiary);">${this.escape(argStr)}</div>` : ''}
        ${t.result ? this.escape(t.result) : '<span style="color:var(--text-tertiary);">执行中…</span>'}
      </div>
    </div>`;
  },

  /** 展开/收起单条工具行的详情(参数 + 结果原文),用兄弟节点定位,无 id 冲突 */
  toggleToolLineDetail(lineHeaderEl) {
    const detail = lineHeaderEl.parentElement.querySelector('.tool-line-detail');
    if (detail) detail.style.display = detail.style.display === 'none' ? 'block' : 'none';
  },

  /** 展开/收起已完成消息的整个工具过程区(箭头随动旋转) */
  toggleToolProcess(headerEl) {
    const detail = headerEl.nextElementSibling;
    if (!detail) return;
    const open = detail.style.display !== 'none';
    detail.style.display = open ? 'none' : 'block';
    const chev = headerEl.querySelector('.tool-process-chevron');
    if (chev) chev.style.transform = open ? '' : 'rotate(180deg)';
  },

  /**
   * 流式期间增量渲染:工具开始 → 容器内追加一行(首次先插入「正在分析」头),
   * 不触发 updateLastMessage 的全量 Markdown 重建,消除工具高频事件造成的卡顿
   */
  streamToolStart(msg, idx) {
    const box = document.getElementById('ai-streaming-tools');
    if (!box) return;
    if (!document.getElementById('ai-tools-header')) {
      box.insertAdjacentHTML('afterbegin', this.toolStreamHeader(msg));
    }
    // 新的末行出现前,把原末行的树形前缀 └─ 改为 ├─
    const lines = box.querySelectorAll('.tool-line');
    if (lines.length) {
      const prev = lines[lines.length - 1].querySelector('.tool-line-prefix');
      if (prev) prev.textContent = '├─';
    }
    box.insertAdjacentHTML('beforeend', this.renderToolNarrativeLine(msg, msg.tools[idx], idx));
    this.scrollToBottomIfPinned();
  },

  /** 流式期间增量渲染:工具结果到达 → 只重绘对应那一行 */
  streamToolResult(msg, idx) {
    const box = document.getElementById('ai-streaming-tools');
    if (!box) return;
    const line = box.querySelectorAll('.tool-line')[idx];
    if (!line) return;
    line.outerHTML = this.renderToolNarrativeLine(msg, msg.tools[idx], idx);
    this.scrollToBottomIfPinned();
  },

  /**
   * 渲染员工答案卡片
   *   - 头部：头像 + 员工姓名 + 部门/领域
   *   - 工具调用折叠区（流式期间）
   *   - 结论 Block：图标 + "结论" 标题 + 答案内容
   *   - 底部：置信度 + Canvas 全文入口（长文） + 操作按钮（赞/踩）
   */
  renderAnswerCard(msg, route, msgIdx) {
    const agentName = msg.agentName || route?.agentName || '总前台';
    const agentEmoji = msg.agentEmoji || route?.agentEmoji || '🎯';
    const agentRole = route ? `${route.department || ''}${route.department ? ' / ' : ''}${route.domain || ''}`.replace(/^ \/\s|\/\s$/, '') : '';

    // 头像：全员橘子吉祥物图(总前台原图,领域员工由 cuteAvatar 按姓名哈希做轻微色相/饱和度差异化)
    const isFrontdesk = agentName === '总前台';
    const avatarHtml = isFrontdesk
      ? '<img src="/static/assets/avatar-orange.png" alt="总前台" style="width:100%;height:100%;object-fit:cover;">'
      : (typeof cuteAvatar === 'function' ? cuteAvatar(agentName, agentEmoji, 36) : agentEmoji);

    const spinnerHtml = msg.streaming && !msg.content
      ? '<div style="display:flex;gap:6px;padding:8px 0;"><span style="width:8px;height:8px;background:var(--text-tertiary);border-radius:50%;animation:chat-bounce 1.4s infinite ease-in-out both;"></span><span style="width:8px;height:8px;background:var(--text-tertiary);border-radius:50%;animation:chat-bounce 1.4s infinite ease-in-out both;animation-delay:-0.16s;"></span><span style="width:8px;height:8px;background:var(--text-tertiary);border-radius:50%;animation:chat-bounce 1.4s infinite ease-in-out both;animation-delay:-0.32s;"></span></div>'
      : '';

    // 流式消息必须始终渲染带固定 id 的内容容器(spinner 也放在容器内),
    // 否则 updateLastMessage 找不到属于它的 DOM,chunk 会写进上一条旧消息
    const contentHtml = msg.streaming
      ? `<div class="ai-answer-content" id="ai-streaming-content" style="font-size:14px;line-height:22px;color:var(--text-primary);">${msg.content ? this.renderStreamMarkdown(msg.content) : spinnerHtml}</div>`
      : (msg.content
        ? `<div class="ai-answer-content" style="font-size:14px;line-height:22px;color:var(--text-primary);">${this.renderMarkdown(msg.content)}</div>`
        : '');

    // 工具调用叙事区(方案 A:折叠聚合 + 过程叙事)
    // 流式期间:容器常驻固定 id,工具行由 streamToolStart/streamToolResult 增量写入,不重建 DOM;
    // 完成后:自动折叠为一行摘要(直接展示结论),点击才展开过程,每行可再展开参数与结果原文
    let toolsHtml = '';
    if (msg.streaming) {
      toolsHtml = `<div id="ai-streaming-tools" style="padding:0 0 10px;">${msg.tools && msg.tools.length
        ? this.toolStreamHeader(msg) + msg.tools.map((t, i) => this.renderToolNarrativeLine(msg, t, i)).join('')
        : ''}</div>`;
    } else if (msg.tools && msg.tools.length > 0) {
      const errCount = msg.tools.filter(t => t.status === 'error').length;
      toolsHtml = `<div style="padding:0 0 10px;">
        <div style="display:flex;align-items:center;gap:6px;cursor:pointer;user-select:none;width:fit-content;" onclick="ChatModule.toggleToolProcess(this)">
          <span style="color:${errCount ? '#DC2626' : '#059669'};font-size:12px;">${errCount ? '✕' : '✓'}</span>
          <span style="font-size:12px;color:var(--text-tertiary);">已完成分析(${msg.tools.length} 步)${errCount ? `,${errCount} 步失败` : ''}</span>
          <span class="material-symbols-outlined tool-process-chevron" style="font-size:16px;color:var(--text-tertiary);transition:transform 0.2s;">expand_more</span>
        </div>
        <div class="tool-process-detail" style="display:none;margin-top:6px;">
          ${msg.tools.map((t, i) => this.renderToolNarrativeLine(msg, t, i)).join('')}
        </div>
      </div>`;
    }

    // 长文（>800 字符）提供"在 Canvas 中打开全文"入口；原文入暂存区按索引取用
    let fullCanvasBtn = '';
    if (!msg.streaming && msg.content && msg.content.length > 800) {
      const ftIdx = this._blockStore.length;
      this._blockStore.push({ lang: 'markdown', code: msg.content });
      fullCanvasBtn = `<button onclick="ChatModule.openCanvasFromBlock(${ftIdx})"
        style="padding:3px 10px;background:white;border:1px solid var(--border-default);border-radius:12px;font-size:12px;color:var(--text-secondary);cursor:pointer;font-family:inherit;transition:all 0.15s;"
        onmouseover="this.style.borderColor='#171717';this.style.color='#171717'"
        onmouseout="this.style.borderColor='var(--border-default)';this.style.color='var(--text-secondary)'">⧉ 在 Canvas 中打开全文</button>`;
    }

    // 跨领域提示卡:总前台回答涉及多个领域时,提供「转为协作任务」一键入口(单聊不显示)
    let collabHtml = '';
    const curSession = this.sessions[this.currentSessionId];
    if (!msg.streaming && msgIdx != null && msg.suggestCollab && msg.suggestCollab.length >= 2
        && curSession && !curSession.agentId) {
      const domainsText = msg.suggestCollab.map(d => this.escape(d)).join('、');
      collabHtml = `
      <div style="margin-top:12px;display:flex;align-items:center;gap:12px;padding:12px 16px;background:#FFFBEB;border:1px solid #FDE68A;border-radius:12px;">
        <span class="material-symbols-outlined">handshake</span>
        <div style="flex:1;min-width:0;font-size:13px;color:#92400E;line-height:20px;">
          检测到该问题涉及多个领域(<b>${domainsText}</b>),可转为协作任务,由多领域员工并行处理并汇总冲突。
        </div>
        <button onclick="ChatModule.convertToCollab(${msgIdx})"
          style="flex-shrink:0;padding:6px 14px;background:var(--teal-700);color:white;border:none;border-radius:999px;font-size:13px;cursor:pointer;font-family:inherit;transition:opacity 0.15s;"
          onmouseover="this.style.opacity='0.85'" onmouseout="this.style.opacity='1'">转为协作任务</button>
      </div>`;
    }

    return `
      <!-- 无气泡卡片：内容直接落在页面背景上(融入背景),md-code/table-card 内容卡片保留 -->
      <div>
        <!-- 头部：员工信息（头像：总前台用橘子吉祥物图,员工沿用像素牛马） -->
        <div style="display:flex;align-items:center;gap:12px;padding:4px 0 10px;">
          <div style="width:36px;height:36px;border-radius:50%;overflow:hidden;flex-shrink:0;">${avatarHtml}</div>
          <div style="flex:1;min-width:0;">
            <div style="font-size:14px;font-weight:600;color:var(--text-primary);">${this.escape(agentName)}</div>
            ${agentRole ? `<div style="font-size:12px;color:var(--text-tertiary);margin-top:2px;">${agentRole}</div>` : ''}
          </div>
        </div>

        <!-- 工具调用区域 -->
        ${toolsHtml}

        <!-- 结论 Block -->
        <div style="padding:0;">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--text-tertiary);">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
            <span style="font-size:12px;font-weight:600;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:0.5px;">结论</span>
          </div>
          ${contentHtml}
        </div>

        ${!msg.streaming && msg.content ? `
        <!-- 底部操作区（无边框无底色,融入背景） -->
        <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 0 0;">
          <div style="display:flex;align-items:center;gap:8px;font-size:12px;color:var(--text-tertiary);flex-wrap:wrap;">
            ${route?.confidence ? `<span style="padding:3px 8px;background:white;border:1px solid var(--border-default);border-radius:12px;">置信度 ${this.escape(route.confidence)}</span>` : ''}
            ${msg.toolsUsed && msg.toolsUsed.length > 0 ? `<span style="padding:3px 8px;background:#ECFDF5;border:1px solid #A7F3D0;border-radius:12px;color:#059669;"><span class="material-symbols-outlined" style="font-size:12px;vertical-align:-2px;">build</span> ${msg.toolsUsed.length} 次工具调用 · ${msg.iterations || 0} 轮</span>` : ''}
            ${fullCanvasBtn}
          </div>
          <div style="display:flex;gap:8px;">
            <button title="复制回答" onclick="ChatModule.copyAnswer(${msgIdx}, this)"
              style="width:32px;height:32px;background:white;border:1px solid var(--border-default);border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--text-secondary);transition:all 0.15s;"
              onmouseover="this.style.borderColor='var(--teal-600, #0D9488)';this.style.color='var(--teal-600, #0D9488)'" onmouseout="this.style.borderColor='var(--border-default)';this.style.color='var(--text-secondary)'">
              <span class="material-symbols-outlined" style="font-size:16px;">content_copy</span>
            </button>
            <button title="重新生成" onclick="ChatModule.regenerate(${msgIdx})"
              style="width:32px;height:32px;background:white;border:1px solid var(--border-default);border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--text-secondary);transition:all 0.15s;"
              onmouseover="this.style.borderColor='var(--teal-600, #0D9488)';this.style.color='var(--teal-600, #0D9488)'" onmouseout="this.style.borderColor='var(--border-default)';this.style.color='var(--text-secondary)'">
              <span class="material-symbols-outlined" style="font-size:16px;">refresh</span>
            </button>
            <button title="分享(复制问题+回答)" onclick="ChatModule.shareAnswer(${msgIdx}, this)"
              style="width:32px;height:32px;background:white;border:1px solid var(--border-default);border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--text-secondary);transition:all 0.15s;"
              onmouseover="this.style.borderColor='var(--teal-600, #0D9488)';this.style.color='var(--teal-600, #0D9488)'" onmouseout="this.style.borderColor='var(--border-default)';this.style.color='var(--text-secondary)'">
              <span class="material-symbols-outlined" style="font-size:16px;">share</span>
            </button>
            <button title="有用" onclick="ChatModule.submitFeedback(${msgIdx}, 'up')"
              style="width:32px;height:32px;background:${msg.feedback === 'up' ? '#ECFDF5' : 'white'};border:1px solid ${msg.feedback === 'up' ? '#059669' : 'var(--border-default)'};border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;color:${msg.feedback === 'up' ? '#059669' : 'var(--text-secondary)'};transition:all 0.15s;"
              ${msg.feedback !== 'up' ? `onmouseover="this.style.borderColor='var(--status-success)';this.style.color='var(--status-success)'" onmouseout="this.style.borderColor='var(--border-default)';this.style.color='var(--text-secondary)'"` : ''}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="${msg.feedback === 'up' ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"></path>
              </svg>
            </button>
            <button title="需要改进" onclick="ChatModule.submitFeedback(${msgIdx}, 'down')"
              style="width:32px;height:32px;background:${msg.feedback === 'down' ? '#FEF2F2' : 'white'};border:1px solid ${msg.feedback === 'down' ? '#DC2626' : 'var(--border-default)'};border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;color:${msg.feedback === 'down' ? '#DC2626' : 'var(--text-secondary)'};transition:all 0.15s;"
              ${msg.feedback !== 'down' ? `onmouseover="this.style.borderColor='var(--status-warning)';this.style.color='var(--status-warning)'" onmouseout="this.style.borderColor='var(--border-default)';this.style.color='var(--text-secondary)'"` : ''}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="${msg.feedback === 'down' ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"></path>
              </svg>
            </button>
          </div>
        </div>` : ''}
      </div>
      ${collabHtml}
    `;
  },

  /**
   * 提交回答评价(点赞/点踩):再次点击同一按钮=取消评价
   * 乐观更新本地状态后回传后端,看板采纳率以此聚合
   */
  async submitFeedback(msgIdx, kind) {
    const session = this.sessions[this.currentSessionId];
    if (!session || !session.messages) return;
    const msg = session.messages[msgIdx];
    if (!msg || !msg.messageId) return;
    // 点同一个按钮 = 取消评价;点另一个 = 切换评价
    const next = msg.feedback === kind ? '' : kind;
    const prev = msg.feedback || '';
    msg.feedback = next;
    this.renderMessages();
    try {
      const res = await fetch(`/api/frontdesk/messages/${msg.messageId}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feedback: next }),
      });
      if (!res.ok) throw new Error('feedback API 失败');
    } catch (e) {
      console.warn('[chat] 评价提交失败,回滚', e);
      msg.feedback = prev;  // 失败回滚
      this.renderMessages();
    }
  },

  /**
   * 复制指定回答的 Markdown 原文
   */
  async copyAnswer(msgIdx, btn) {
    const msg = this.sessions[this.currentSessionId]?.messages?.[msgIdx];
    if (msg?.content) await this._copyText(msg.content, btn);
  },

  /**
   * 复制代码块/表格 CSV(_blockStore 原文)
   */
  async copyBlock(storeIdx, btn) {
    const blk = this._blockStore[storeIdx];
    if (blk) await this._copyText(blk.code, btn);
  },

  /**
   * 下载表格 CSV(带 BOM 防 Excel 乱码)
   */
  downloadBlock(storeIdx) {
    const blk = this._blockStore[storeIdx];
    if (!blk) return;
    const blob = new Blob(['\ufeff' + blk.code], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'table.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  },

  /**
   * 分享回答:复制「问题 + 回答」格式化文本
   */
  async shareAnswer(msgIdx, btn) {
    const session = this.sessions[this.currentSessionId];
    const msg = session?.messages?.[msgIdx];
    if (!msg?.content) return;
    // 向前找最近一条用户消息作为问题
    let question = '';
    for (let i = msgIdx - 1; i >= 0; i--) {
      if (session.messages[i].role === 'user') { question = session.messages[i].content; break; }
    }
    const agentName = msg.agentName || msg.agent || 'AI 员工';
    await this._copyText(`问:${question}\n\n答(${agentName}):\n${msg.content}`, btn);
  },

  /**
   * 重新生成:找到对应用户提问重走 sendMessage(流式中忽略)
   */
  regenerate(msgIdx) {
    if (this.isStreaming) return;
    const session = this.sessions[this.currentSessionId];
    if (!session || !session.messages) return;
    let question = '';
    for (let i = msgIdx - 1; i >= 0; i--) {
      if (session.messages[i].role === 'user') { question = session.messages[i].content; break; }
    }
    if (question) this.sendMessage(question);
  },

  /**
   * 剪贴板复制 + 按钮对勾反馈(execCommand 兜底)
   */
  async _copyText(text, btn) {
    try {
      await navigator.clipboard.writeText(text);
    } catch (e) {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    }
    if (btn) {
      const old = btn.innerHTML;
      btn.innerHTML = '<span class="material-symbols-outlined" style="font-size:15px;color:#059669;">check</span>';
      setTimeout(() => { btn.innerHTML = old; }, 1200);
    }
  },

  /**
   * 更新发送按钮状态:流式期间变为可点击的红色「停止」按钮,结束后恢复发送样式
   */
  updateSendButton(loading) {
    const btn = document.getElementById('chat-send');
    if (!btn) return;
    if (loading) {
      btn.title = '停止生成';
      btn.style.background = '#DC2626';
      btn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"></rect></svg>';
    } else {
      btn.title = '发送';
      btn.style.background = 'var(--teal-600)';
      btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"></line><polyline points="5 12 12 5 19 12"></polyline></svg>';
    }
  },

  /**
   * 转为协作任务:取该 AI 回答对应的用户提问,调用 POST /api/tasks 发起协作,成功后跳转协作会议室
   */
  async convertToCollab(msgIdx) {
    const session = this.sessions[this.currentSessionId];
    if (!session || !session.messages) return;
    // 向前找最近一条用户消息作为协作任务内容
    const messages = session.messages;
    let question = '';
    for (let i = msgIdx - 1; i >= 0; i--) {
      if (messages[i].role === 'user') { question = messages[i].content; break; }
    }
    if (!question) { alert('未找到对应的用户提问,无法转为协作任务'); return; }

    try {
      const res = await fetch('/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: question.length > 50 ? question.substring(0, 50) + '…' : question,
          description: question,
          initiator: '总前台转入',
          deadline_minutes: 30,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(err.detail || '转为协作任务失败,请稍后重试');
        return;
      }
      // 跳转协作会议室(同步侧边栏激活态)
      const navEl = document.querySelector('.nav-item[data-page="collaboration"]');
      switchAppPage('collaboration', navEl);
    } catch (e) {
      alert('网络异常:' + e.message);
    }
  },

  /**
   * HTML 转义
   */
  escape(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
  },

  /**
   * HTML 反转义（取回代码块原文，供 Canvas 使用）
   */
  unescape(html) {
    const t = document.createElement('textarea');
    t.innerHTML = html || '';
    return t.value;
  },

  /**
   * 轻量 Markdown 渲染（不引入整库）
   * 支持：代码块 ```...```、行内代码 `...`、加粗 **...**、引用 > ...、无序列表 - / *
   * 策略：先 escape 防注入，再用占位符保护代码块，最后做行内替换
   * 代码块：原文入 _blockStore，悬浮按钮可"在 Canvas 中打开"
   */
  renderMarkdown(text) {
    if (!text) return '';
    let html = this.escape(text);

    // 0. Markdown 表格（先处理，避免被其他规则干扰）
    // 匹配 | col1 | col2 |\n|---|---|\n| val1 | val2 |
    // 包成 header 卡片(复制/下载 CSV),CSV 原文入 _blockStore
    const tableRegex = /(\|.+\|\n)(\|[\-\s|:]+\|\n)((?:\|.+\|\n?)+)/g;
    html = html.replace(tableRegex, (m, headerRow, separatorRow, bodyRows) => {
      const headers = headerRow.split('|').map(h => h.trim()).filter(h => h);
      const rows = bodyRows.trim().split('\n').map(row =>
        row.split('|').map(c => c.trim()).filter(c => c)
      );

      // CSV 原文(反转义,含分隔符的单元格加引号)入 _blockStore,供复制/下载
      const csvCell = (c) => {
        const v = this.unescape(c);
        return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
      };
      const csv = [headers.map(csvCell).join(','),
        ...rows.map(r => r.map(csvCell).join(','))].join('\n');
      const storeIdx = this._blockStore.length;
      this._blockStore.push({ lang: 'csv', code: csv });

      let table = '<table style="width:100%;border-collapse:collapse;font-size:13px;">';
      table += '<thead><tr>';
      headers.forEach(h => {
        table += `<th style="padding:8px 12px;background:#F7FAF9;border-bottom:1px solid var(--border-soft, #E3EEEB);text-align:left;font-weight:600;color:var(--text-primary);">${h}</th>`;
      });
      table += '</tr></thead><tbody>';
      rows.forEach(row => {
        table += '<tr>';
        row.forEach(cell => {
          table += `<td style="padding:8px 12px;border-bottom:1px solid var(--border-soft, #E3EEEB);color:var(--text-primary);">${cell}</td>`;
        });
        table += '</tr>';
      });
      table += '</tbody></table>';
      return `<div class="md-table-card"><div class="md-card-head"><span class="md-card-head-label">表格</span><button class="md-icon-btn" title="复制表格 (CSV)" onclick="ChatModule.copyBlock(${storeIdx}, this)"><span class="material-symbols-outlined">content_copy</span></button><button class="md-icon-btn" title="下载 CSV" onclick="ChatModule.downloadBlock(${storeIdx})"><span class="material-symbols-outlined">download</span></button></div><div style="overflow-x:auto;">${table}</div></div>`;
    });

    // 1. 代码块 ```...``` → header 卡片(语言名 + Canvas/复制图标),原文入 _blockStore
    const codeBlocks = [];
    html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (m, lang, code) => {
      const idx = codeBlocks.length;
      const trimmed = code.replace(/\n$/, '');
      // 记录反转义后的原始代码，供 Canvas 打开/编辑/下载/复制
      const storeIdx = this._blockStore.length;
      this._blockStore.push({ lang: lang || 'text', code: this.unescape(trimmed) });
      codeBlocks.push(`<div class="md-code-card"><div class="md-card-head"><span class="md-card-head-label">${lang || 'plain'}</span><button class="md-icon-btn" title="在 Canvas 中打开" onclick="ChatModule.openCanvasFromBlock(${storeIdx})"><span class="material-symbols-outlined">open_in_new</span></button><button class="md-icon-btn" title="复制代码" onclick="ChatModule.copyBlock(${storeIdx}, this)"><span class="material-symbols-outlined">content_copy</span></button></div><pre style="background:#0d1117;color:#c9d1d9;padding:12px 14px;overflow-x:auto;font-family:ui-monospace,Menlo,Monaco,Consolas,monospace;font-size:13px;line-height:20px;margin:0;">${trimmed}</pre></div>`);
      return ` CODE${idx} `;
    });

    // 2. 行内代码 `...` → <code>
    html = html.replace(/`([^`\n]+)`/g, '<code style="background:#F3F4F6;color:#1E40AF;padding:2px 6px;border-radius:4px;font-family:ui-monospace,Menlo,Monaco,Consolas,monospace;font-size:13px;">$1</code>');

    // 3. 加粗 **...** → <strong>
    html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong style="color:#171717;font-weight:600;">$1</strong>');

    // 4. 标题 # ~ ######(注意:必须按 # 数量从多到少替换,否则 #### 会被 ### 截胡)
    html = html.replace(/^######\s+(.+)$/gm, '<h6 style="font-size:13px;font-weight:600;color:#171717;margin:12px 0 6px 0;">$1</h6>');
    html = html.replace(/^#####\s+(.+)$/gm, '<h5 style="font-size:13px;font-weight:600;color:#171717;margin:12px 0 6px 0;">$1</h5>');
    html = html.replace(/^####\s+(.+)$/gm, '<h4 style="font-size:14px;font-weight:600;color:#171717;margin:14px 0 6px 0;">$1</h4>');
    html = html.replace(/^###\s+(.+)$/gm, '<h3 style="font-size:15px;font-weight:600;color:#171717;margin:16px 0 8px 0;">$1</h3>');
    html = html.replace(/^##\s+(.+)$/gm, '<h2 style="font-size:16px;font-weight:600;color:#171717;margin:18px 0 10px 0;">$1</h2>');
    html = html.replace(/^#\s+(.+)$/gm, '<h1 style="font-size:18px;font-weight:600;color:#171717;margin:20px 0 12px 0;">$1</h1>');

    // 5. 引用 > ...（整行）→ <blockquote>
    html = html.replace(/^&gt;\s?(.*)$/gm, '<blockquote style="border-left:3px solid #1E40AF;padding:6px 12px;margin:8px 0;background:#EFF6FF;color:#4B5563;font-size:13px;border-radius:0 6px 6px 0;">$1</blockquote>');

    // 6. 无序列表项 - / * → 带 • 前缀的 div
    html = html.replace(/^[\-\*]\s+(.+)$/gm, '<div style="padding-left:16px;text-indent:-12px;margin:4px 0;"><span style="color:#1E40AF;margin-right:6px;">•</span>$1</div>');

    // 7. 有序列表 1. 2. → 保持数字
    html = html.replace(/^(\d+)\.\s+(.+)$/gm, '<div style="padding-left:20px;text-indent:-16px;margin:4px 0;"><span style="color:#1E40AF;margin-right:6px;">$1.</span>$2</div>');

    // 8. 分隔线 --- → <hr>
    html = html.replace(/^---$/gm, '<hr style="border:none;border-top:1px solid var(--border-light);margin:16px 0;">');

    // 9. 段落：连续两个 \n → 段落分隔
    html = html.replace(/\n\n+/g, '\n\n');
    // 单 \n → <br>
    html = html.replace(/\n/g, '<br>');

    // 10. 还原代码块（避免被 <br> 影响）
    codeBlocks.forEach((block, idx) => {
      html = html.replace(` CODE${idx} `, block);
    });

    // 11. 清理 blockquote 内的 <br>
    html = html.replace(/<blockquote([^>]*)>([\s\S]*?)<\/blockquote>/g, (m, attr, content) => {
      return `<blockquote${attr}>${content.replace(/<br>/g, ' ')}</blockquote>`;
    });

    return html;
  },
};

// 动画样式（一次性注入）
if (!document.getElementById('chat-animation-style')) {
  const style = document.createElement('style');
  style.id = 'chat-animation-style';
  style.textContent = `
    @keyframes chat-bounce {
      0%, 80%, 100% { transform: scale(0); }
      40% { transform: scale(1); }
    }
    @keyframes chat-spin {
      to { transform: rotate(360deg); }
    }
    #chat-scroll-area { scroll-behavior: smooth; }
    #chat-messages { animation: chat-fade-in 0.2s ease; }
    @keyframes chat-fade-in {
      from { opacity: 0; transform: translateY(4px); }
      to { opacity: 1; transform: translateY(0); }
    }
  `;
  document.head.appendChild(style);
}

window.ChatModule = ChatModule;
