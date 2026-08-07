/**
 * 管理与治理模块
 * 7 大 Tab：组织管理 / 资源中心 / 能力中心 / 工具中心 / 岗位库 / 员工管理 / 权限与审计
 * 每个 Tab 支持列表查看 + 新增 + 编辑 + 删除
 *
 * v20：员工编辑弹窗整体优化
 *  - 部门/领域由文本框改为下拉选择（复用 /api/admin/departments、/api/admin/domains）
 *  - multiselect 选项行改用 ms-* 类样式（修复全局 .form-group input 把 checkbox 撑大的问题）
 *  - 弹窗加宽 480px → 560px
 */

const AdminModule = {
  activeTab: 'org',  // 默认显示组织管理（对齐 Figma）
  cache: {},            // 各 Tab 数据缓存
  _draft: null,           // AI 生成草案预填（新建表单消费后即清空）
  _lastAIGenPreview: null, // AI 生成 Skill 预览缓存（供「采用」使用）

  // Tab 配置
  TABS: {
    'org':         { label: '组织管理',     icon: '🏢', endpoint: '/api/admin/org',          columns: ['name', 'emoji', 'domains'] },
    'resources':   { label: '资源中心',     icon: '📁', endpoint: '/api/admin/resources',    columns: ['name', 'type', 'owner'] },
    'skills':      { label: '能力中心',     icon: '🧩', endpoint: '/api/admin/skills',       columns: ['name', 'type', 'owner'] },
    'tools':       { label: '工具中心',     icon: '🔧', endpoint: '/api/admin/tools',        columns: ['name', 'type', 'endpoint'] },
    'role-packs':  { label: '岗位库',       icon: '📦', endpoint: '/api/admin/role-packs',   columns: ['name', 'version', 'owner'] },
    'agents':      { label: '员工管理',     icon: '👥', endpoint: '/api/admin/agents',       columns: ['name', 'role', 'lifecycle'] },
    'audit':       { label: '权限与审计',   icon: '🔐', endpoint: '/api/admin/audit',        columns: ['actor', 'action', 'target_name'] },
  },

  /**
   * 初始化管理页面
   */
  init() {
    this.bindTabSwitch();
    // 恢复上次选中的 admin tab（刷新保持）
    const savedTab = sessionStorage.getItem('office_agent_admin_tab');
    if (savedTab && this.TABS[savedTab]) {
      this.activeTab = savedTab;
    }
    this.loadTab(this.activeTab);
    // 同步 Tab 高亮状态
    this._syncTabHighlight();
  },

  /**
   * 绑定 Tab 切换
   * 用 data-tab 属性绑定，避免 textContent 含 emoji 时匹配失败
   */
  bindTabSwitch() {
    document.querySelectorAll('#app-admin .admin-tab').forEach((tab, idx) => {
      if (tab.dataset.bound) return;
      tab.dataset.bound = '1';

      // 优先用 data-tab，否则按索引映射
      const tabKeys = ['org', 'resources', 'skills', 'tools', 'role-packs', 'agents', 'audit'];
      const key = tab.dataset.tab || tabKeys[idx];

      tab.onclick = (e) => {
        e.preventDefault();
        if (!key) return;
        document.querySelectorAll('#app-admin .admin-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        this.activeTab = key;
        sessionStorage.setItem('office_agent_admin_tab', key);  // 保存当前 admin tab
        this.loadTab(key);
      };
    });

    // 新增 Agent 按钮（顶部 + 底部）→ 触发 9 步向导
    const addBtns = document.querySelectorAll('#app-admin .filter-btn, #app-admin .add-agent-btn');
    addBtns.forEach(btn => {
      if (btn.dataset.bound) return;
      btn.dataset.bound = '1';
      btn.onclick = () => this.startWizard();
    });

    // 9 步向导步骤点击
    const steps = document.querySelectorAll('#app-admin .step-item');
    steps.forEach((step, idx) => {
      if (step.dataset.bound) return;
      step.dataset.bound = '1';
      step.style.cursor = 'pointer';
      step.onclick = () => this.startWizard(idx + 1);
    });
  },

  /**
   * 同步 Tab 高亮状态（恢复选中项时使用）
   */
  _syncTabHighlight() {
    const tabKeys = ['org', 'resources', 'skills', 'tools', 'role-packs', 'agents', 'audit'];
    document.querySelectorAll('#app-admin .admin-tab').forEach((tab, idx) => {
      const key = tab.dataset.tab || tabKeys[idx];
      tab.classList.toggle('active', key === this.activeTab);
    });
  },

  // ════════════════════════════════════════════
  //  文件上传（资源中心，markitdown 自动解析）
  // ════════════════════════════════════════════

  /**
   * 文件上传弹窗
   */
  showUploadModal() {
    const old = document.getElementById('admin-upload-modal');
    if (old) old.remove();

    const modal = document.createElement('div');
    modal.id = 'admin-upload-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:2000;display:flex;align-items:center;justify-content:center;';
    modal.innerHTML = `
      <div style="background:white;border-radius:12px;padding:32px;width:480px;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
        <h3 style="font-size:18px;font-weight:600;margin-bottom:8px;"><span class="material-symbols-outlined" style="font-size:20px;vertical-align:-4px;">upload</span> 上传文件</h3>
        <p style="font-size:13px;color:var(--text-secondary);margin-bottom:24px;">
          支持 PDF / Word / Excel / PPT / HTML / 图片 / 代码文件，上传后自动解析为 Markdown
        </p>

        <div id="upload-drop-zone" style="border:2px dashed var(--border-default);border-radius:12px;padding:40px 20px;text-align:center;cursor:pointer;transition:all 0.15s;background:var(--bg-page);">
          <div style="font-size:32px;margin-bottom:8px;"><span class="material-symbols-outlined" style="font-size:32px;vertical-align:-2px;">cloud_upload</span></div>
          <div style="font-size:14px;font-weight:500;color:var(--text-primary);">点击或拖拽文件到此处</div>
          <div style="font-size:12px;color:var(--text-tertiary);margin-top:4px;">最大 50MB · 支持 PDF/Word/Excel/PPT 等</div>
          <input type="file" id="upload-file-input" style="display:none;" />
        </div>

        <div id="upload-file-info" style="display:none;margin-top:12px;padding:12px;background:var(--bg-input);border-radius:8px;">
          <div style="display:flex;align-items:center;gap:8px;">
            <span id="upload-file-icon" style="font-size:20px;"><span class="material-symbols-outlined" style="font-size:20px;vertical-align:-2px;">description</span></span>
            <div style="flex:1;min-width:0;">
              <div id="upload-file-name" style="font-size:13px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"></div>
              <div id="upload-file-size" style="font-size:11px;color:var(--text-tertiary);"></div>
            </div>
          </div>
        </div>

        <div style="display:flex;gap:8px;margin-top:24px;">
          <button onclick="document.getElementById('admin-upload-modal').remove()" style="flex:1;padding:10px;border:1px solid var(--border-default);border-radius:999px;background:white;font-size:14px;cursor:pointer;">取消</button>
          <button id="upload-confirm-btn" disabled style="flex:1;padding:10px;border:none;border-radius:999px;background:var(--teal-700);color:white;font-size:14px;cursor:pointer;opacity:0.5;">
            上传并解析
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

    const dropZone = document.getElementById('upload-drop-zone');
    const fileInput = document.getElementById('upload-file-input');
    const fileInfo = document.getElementById('upload-file-info');
    const confirmBtn = document.getElementById('upload-confirm-btn');

    let selectedFile = null;

    // 点击选择文件
    dropZone.onclick = () => fileInput.click();

    // 拖拽
    dropZone.ondragover = (e) => { e.preventDefault(); dropZone.style.borderColor = '#059669'; dropZone.style.background = '#ECFDF5'; };
    dropZone.ondragleave = () => { dropZone.style.borderColor = 'var(--border-default)'; dropZone.style.background = 'var(--bg-page)'; };
    dropZone.ondrop = (e) => {
      e.preventDefault();
      dropZone.style.borderColor = 'var(--border-default)';
      dropZone.style.background = 'var(--bg-page)';
      if (e.dataTransfer.files.length > 0) {
        handleFileSelect(e.dataTransfer.files[0]);
      }
    };

    // 文件选择
    fileInput.onchange = (e) => {
      if (e.target.files.length > 0) {
        handleFileSelect(e.target.files[0]);
      }
    };

    function handleFileSelect(file) {
      selectedFile = file;
      const sizeStr = file.size > 1024*1024 ? `${(file.size/1024/1024).toFixed(1)} MB` : `${(file.size/1024).toFixed(0)} KB`;
      document.getElementById('upload-file-name').textContent = file.name;
      document.getElementById('upload-file-size').textContent = sizeStr;

      // 文件图标
      const ext = file.name.split('.').pop().toLowerCase();
      const iconMap = {pdf:'picture_as_pdf', doc:'description', docx:'description', xls:'table', xlsx:'table', ppt:'slideshow', pptx:'slideshow', py:'code', java:'code', js:'code'};
      document.getElementById('upload-file-icon').innerHTML = '<span class="material-symbols-outlined" style="font-size:20px;">' + (iconMap[ext] || 'description') + '</span>';

      fileInfo.style.display = 'block';
      confirmBtn.disabled = false;
      confirmBtn.style.opacity = '1';
    }

    // 上传
    confirmBtn.onclick = async () => {
      if (!selectedFile) return;

      confirmBtn.disabled = true;
      confirmBtn.textContent = '正在上传并解析…';

      const formData = new FormData();
      formData.append('file', selectedFile);

      try {
        const res = await fetch('/api/admin/resources/upload', {
          method: 'POST',
          body: formData,
        });

        if (res.ok) {
          const data = await res.json();
          modal.remove();
          this.loadTab('resources');
          this._toast(`✓ ${data.message}`, 'success');
        } else {
          const err = await res.json().catch(() => ({ detail: '上传失败' }));
          throw new Error(err.detail || '上传失败');
        }
      } catch (e) {
        confirmBtn.disabled = false;
        confirmBtn.textContent = '重试上传';
        Toast.error(`上传失败: ${e.message}`);
      }
    };
  },

  // ════════════════════════════════════════════
  //  代码仓库管理（资源中心子模块）
  // ════════════════════════════════════════════

  /**
   * 加载仓库列表（管理页面内）
   */
  async loadRepoListInAdmin() {
    const container = document.getElementById('admin-repo-list');
    if (!container) return;

    try {
      const res = await fetch('/api/repos');
      const repos = await res.json();

      if (!repos || repos.length === 0) {
        container.innerHTML = `
          <div style="padding:24px;text-align:center;color:var(--text-tertiary);background:var(--bg-page);border-radius:8px;">
            <div style="font-size:28px;margin-bottom:8px;"><span class="material-symbols-outlined" style="font-size:28px;vertical-align:-2px;">inventory_2</span></div>
            <div style="font-size:13px;">暂无代码仓库，点击"接入仓库"按钮接入 Git 仓库</div>
          </div>`;
        return;
      }

      // 缓存当前列表,编辑弹窗按 repo_id 取数,避免行内塞 JSON
      this._repoCache = repos;

      container.innerHTML = repos.map(r => {
        const statusColor = r.local_exists ? '#059669' : '#DC2626';
        const statusBg = r.local_exists ? '#ECFDF5' : '#FEE2E2';
        const statusText = r.local_exists ? '✓ 就绪' : '✕ 未拉取';
        // 定时刷新徽标(间隔分钟)+上次同步时间
        const refreshBadge = (r.auto_refresh_minutes > 0)
          ? `<span style="font-size:11px;padding:2px 8px;border-radius:12px;background:#EFF6FF;color:#2563EB;font-weight:500;" title="每 ${r.auto_refresh_minutes} 分钟自动拉取"><span class="material-symbols-outlined" style="font-size:12px;vertical-align:-2px;">sync</span> ${r.auto_refresh_minutes}min</span>` : '';
        const branchText = r.current_branch || r.branch || 'main';
        const syncText = r.last_sync_at ? ` · 上次同步 ${r.last_sync_at}` : '';
        return `
          <div style="display:flex;align-items:center;gap:12px;padding:12px 16px;background:white;border:1px solid var(--border-light);border-radius:10px;box-shadow:0 1px 2px rgba(0,0,0,0.03);">
            <div style="width:36px;height:36px;background:var(--bg-input);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;color:var(--text-secondary);"><span class="material-symbols-outlined" style="font-size:18px;vertical-align:-2px;">inventory_2</span></div>
            <div style="flex:1;min-width:0;">
              <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                <span style="font-size:14px;font-weight:600;color:var(--text-primary);">${r.name || r.repo_id}</span>
                <span style="font-size:11px;padding:2px 8px;border-radius:12px;background:${statusBg};color:${statusColor};font-weight:500;">${statusText}</span>
                ${refreshBadge}
                ${r.file_count ? `<span style="font-size:11px;color:var(--text-tertiary);">${r.file_count} 文件</span>` : ''}
              </div>
              <div style="font-size:11px;color:var(--text-tertiary);margin-top:2px;font-family:monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${r.clone_url || '本地仓库'} · <span class="material-symbols-outlined" style="font-size:12px;vertical-align:-2px;">account_tree</span> ${branchText}${syncText}</div>
            </div>
            <div style="display:flex;gap:6px;flex-shrink:0;">
              ${r.local_exists ? `<button onclick="AdminModule.browseRepoInAdmin('${r.repo_id}')" class="edit-btn" style="font-size:12px;">浏览</button>` : ''}
              ${r.local_exists ? `<button onclick="AdminModule.showBranchModal('${r.repo_id}')" class="edit-btn" style="font-size:12px;">分支</button>` : ''}
              <button onclick="AdminModule.showEditRepoModal('${r.repo_id}')" class="edit-btn" style="font-size:12px;">编辑</button>
              <button onclick="AdminModule.pullRepoInAdmin('${r.repo_id}')" class="edit-btn" style="font-size:12px;">拉取</button>
              <button onclick="AdminModule.deleteRepoInAdmin('${r.repo_id}')" class="edit-btn" style="font-size:12px;color:#DC2626;">删除</button>
            </div>
          </div>`;
      }).join('');
    } catch (e) {
      container.innerHTML = `<div style="padding:16px;text-align:center;color:#DC2626;background:#FEE2E2;border-radius:8px;font-size:13px;">加载失败: ${e.message}</div>`;
    }
  },

  /**
   * 接入仓库弹窗
   */
  showCloneRepoModal() {
    const old = document.getElementById('admin-clone-modal');
    if (old) old.remove();

    const modal = document.createElement('div');
    modal.id = 'admin-clone-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:2000;display:flex;align-items:center;justify-content:center;';
    modal.innerHTML = `
      <div style="background:white;border-radius:12px;padding:32px;width:480px;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
        <h3 style="font-size:18px;font-weight:600;margin-bottom:8px;"><span class="material-symbols-outlined" style="font-size:20px;vertical-align:-4px;">folder_open</span> 接入 Git 仓库</h3>
        <p style="font-size:13px;color:var(--text-secondary);margin-bottom:24px;">服务器将 clone 仓库到本地，AI 员工可检索代码回答问题</p>

        <div style="display:flex;flex-direction:column;gap:14px;">
          <div>
            <label style="font-size:13px;font-weight:500;color:var(--text-secondary);margin-bottom:6px;display:block;">Git 地址 *</label>
            <input type="text" id="admin-clone-url" placeholder="https://gitee.com/user/repo.git" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;font-family:monospace;">
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
            <div>
              <label style="font-size:13px;font-weight:500;color:var(--text-secondary);margin-bottom:6px;display:block;">仓库名称 *</label>
              <input type="text" id="admin-clone-id" placeholder="如 my-project" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;">
            </div>
            <div>
              <label style="font-size:13px;font-weight:500;color:var(--text-secondary);margin-bottom:6px;display:block;">分支</label>
              <input type="text" id="admin-clone-branch" value="main" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;">
            </div>
          </div>
          <div style="padding:10px 12px;background:#FEF3C7;border-radius:8px;font-size:12px;color:#92400E;">
            ⚠ 注意：当前 GitHub/GitLab 可能需要代理。推荐使用 Gitee 或内部 GitLab。
          </div>
        </div>

        <div style="display:flex;gap:8px;margin-top:24px;">
          <button onclick="document.getElementById('admin-clone-modal').remove()" style="flex:1;padding:10px;border:1px solid var(--border-default);border-radius:999px;background:white;font-size:14px;cursor:pointer;">取消</button>
          <button id="admin-clone-confirm" style="flex:1;padding:10px;border:none;border-radius:999px;background:var(--teal-700);color:white;font-size:14px;cursor:pointer;">Clone</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

    document.getElementById('admin-clone-confirm').onclick = async () => {
      const url = document.getElementById('admin-clone-url').value.trim();
      const repoId = document.getElementById('admin-clone-id').value.trim();
      const branch = document.getElementById('admin-clone-branch').value.trim() || 'main';

      if (!url || !repoId) { Toast.warning('请填写 Git 地址和仓库名称'); return; }

      const btn = document.getElementById('admin-clone-confirm');
      btn.disabled = true;
      btn.textContent = '正在 Clone…（可能需要 1-2 分钟）';

      try {
        const res = await fetch('/api/repos/clone', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ git_url: url, repo_id: repoId, branch, name: repoId }),
        });

        if (res.ok) {
          const data = await res.json();
          modal.remove();
          this.loadRepoListInAdmin();
          this._toast(`✓ ${data.message || 'Clone 成功'}`, 'success');
        } else {
          const err = await res.json().catch(() => ({ detail: 'Clone 失败' }));
          throw new Error(err.detail || 'Clone 失败');
        }
      } catch (e) {
        btn.disabled = false;
        btn.textContent = '重试 Clone';
        Toast.error(`Clone 失败: ${e.message}`);
      }
    };
  },

  /**
   * 编辑仓库弹窗:名称/克隆地址/默认分支/定时刷新间隔
   */
  showEditRepoModal(repoId) {
    const repo = (this._repoCache || []).find(r => r.repo_id === repoId || r.name === repoId);
    if (!repo) { Toast.error('仓库信息未加载,请刷新列表'); return; }

    const old = document.getElementById('admin-edit-repo-modal');
    if (old) old.remove();

    const modal = document.createElement('div');
    modal.id = 'admin-edit-repo-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:2000;display:flex;align-items:center;justify-content:center;';
    modal.innerHTML = `
      <div style="background:white;border-radius:12px;padding:32px;width:480px;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
        <h3 style="font-size:18px;font-weight:600;margin-bottom:8px;"><span class="material-symbols-outlined" style="font-size:20px;vertical-align:-4px;">edit</span> 编辑仓库</h3>
        <p style="font-size:13px;color:var(--text-secondary);margin-bottom:24px;">修改仓库配置；改名会同步重命名本地目录，不影响员工绑定</p>

        <div style="display:flex;flex-direction:column;gap:14px;">
          <div>
            <label style="font-size:13px;font-weight:500;color:var(--text-secondary);margin-bottom:6px;display:block;">仓库名称</label>
            <input type="text" id="admin-edit-repo-name" value="${repo.name || repo.repo_id}" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;">
          </div>
          <div>
            <label style="font-size:13px;font-weight:500;color:var(--text-secondary);margin-bottom:6px;display:block;">Git 地址</label>
            <input type="text" id="admin-edit-repo-url" value="${repo.clone_url || ''}" placeholder="本地仓库可留空" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;font-family:monospace;">
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
            <div>
              <label style="font-size:13px;font-weight:500;color:var(--text-secondary);margin-bottom:6px;display:block;">默认分支</label>
              <input type="text" id="admin-edit-repo-branch" value="${repo.branch || 'main'}" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;">
            </div>
            <div>
              <label style="font-size:13px;font-weight:500;color:var(--text-secondary);margin-bottom:6px;display:block;">定时刷新(分钟)</label>
              <input type="number" id="admin-edit-repo-refresh" value="${repo.auto_refresh_minutes || 0}" min="0" max="10080" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;">
            </div>
          </div>
          <div style="padding:10px 12px;background:var(--bg-hover);border-radius:8px;font-size:12px;color:var(--text-secondary);">
            定时刷新按间隔自动 git pull；填 0 表示关闭。上次同步:${repo.last_sync_at || '从未'}
          </div>
        </div>

        <div style="display:flex;gap:8px;margin-top:24px;">
          <button onclick="document.getElementById('admin-edit-repo-modal').remove()" style="flex:1;padding:10px;border:1px solid var(--border-default);border-radius:999px;background:white;font-size:14px;cursor:pointer;">取消</button>
          <button id="admin-edit-repo-confirm" style="flex:1;padding:10px;border:none;border-radius:999px;background:var(--teal-700);color:white;font-size:14px;cursor:pointer;">保存</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

    document.getElementById('admin-edit-repo-confirm').onclick = async () => {
      const body = {
        name: document.getElementById('admin-edit-repo-name').value.trim(),
        clone_url: document.getElementById('admin-edit-repo-url').value.trim(),
        branch: document.getElementById('admin-edit-repo-branch').value.trim(),
        auto_refresh_minutes: parseInt(document.getElementById('admin-edit-repo-refresh').value, 10) || 0,
      };
      if (!body.name) { Toast.warning('仓库名称不能为空'); return; }

      const btn = document.getElementById('admin-edit-repo-confirm');
      btn.disabled = true;
      btn.textContent = '保存中…';
      try {
        const res = await fetch(`/api/repos/${encodeURIComponent(repoId)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (res.ok) {
          modal.remove();
          this.loadRepoListInAdmin();
          Toast.success('仓库配置已保存');
        } else {
          const err = await res.json().catch(() => ({ detail: '保存失败' }));
          throw new Error(err.detail || '保存失败');
        }
      } catch (e) {
        btn.disabled = false;
        btn.textContent = '保存';
        Toast.error(`保存失败: ${e.message}`);
      }
    };
  },

  /**
   * 切换分支弹窗:列出本地+远端分支,选中后 checkout
   */
  async showBranchModal(repoId) {
    const old = document.getElementById('admin-branch-modal');
    if (old) old.remove();

    const modal = document.createElement('div');
    modal.id = 'admin-branch-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:2000;display:flex;align-items:center;justify-content:center;';
    modal.innerHTML = `
      <div style="background:white;border-radius:12px;padding:28px;width:440px;max-height:80vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
          <h3 style="font-size:17px;font-weight:600;"><span class="material-symbols-outlined" style="font-size:19px;vertical-align:-3px;">account_tree</span> 切换分支 · ${repoId}</h3>
          <button onclick="document.getElementById('admin-branch-modal').remove()" style="width:28px;height:28px;border:none;background:transparent;font-size:18px;color:var(--text-tertiary);cursor:pointer;">×</button>
        </div>
        <div id="admin-branch-list" style="display:flex;flex-direction:column;gap:6px;margin:14px 0;">
          <div style="padding:20px;text-align:center;color:var(--text-tertiary);font-size:13px;">加载分支中…</div>
        </div>
        <button id="admin-branch-confirm" style="width:100%;padding:10px;border:none;border-radius:999px;background:var(--teal-700);color:white;font-size:14px;cursor:pointer;">切换</button>
      </div>
    `;
    document.body.appendChild(modal);
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

    let branches = [], current = '';
    try {
      const res = await fetch(`/api/repos/${encodeURIComponent(repoId)}/branches`);
      const data = await res.json();
      branches = data.branches || [];
      current = data.current || '';
    } catch (e) {
      document.getElementById('admin-branch-list').innerHTML = `<div style="padding:16px;text-align:center;color:#DC2626;font-size:13px;">分支加载失败</div>`;
      return;
    }

    if (!branches.length) {
      document.getElementById('admin-branch-list').innerHTML = `<div style="padding:16px;text-align:center;color:var(--text-tertiary);font-size:13px;">无分支信息(可能为旧浅克隆,重新接入可获取)</div>`;
      return;
    }

    document.getElementById('admin-branch-list').innerHTML = branches.map(b => `
      <label style="display:flex;align-items:center;gap:8px;padding:9px 12px;border:1px solid ${b.current ? 'var(--teal-600)' : 'var(--border-light)'};border-radius:8px;cursor:pointer;background:${b.current ? 'var(--teal-50)' : 'white'};">
        <input type="radio" name="admin-branch-radio" value="${b.name}" ${b.current ? 'checked' : ''} style="accent-color:var(--teal-700);">
        <span style="font-size:13px;font-family:monospace;flex:1;">${b.name}</span>
        ${b.current ? '<span style="font-size:11px;color:var(--teal-700);font-weight:500;">当前</span>' : ''}
        ${b.remote ? '<span style="font-size:11px;color:var(--text-tertiary);">远端</span>' : ''}
      </label>`).join('');

    document.getElementById('admin-branch-confirm').onclick = async () => {
      const sel = document.querySelector('input[name="admin-branch-radio"]:checked');
      if (!sel) { Toast.warning('请选择分支'); return; }
      const branch = sel.value;
      if (branch === current) { modal.remove(); return; }

      const btn = document.getElementById('admin-branch-confirm');
      btn.disabled = true;
      btn.textContent = '切换中…';
      try {
        const res = await fetch(`/api/repos/${encodeURIComponent(repoId)}/checkout`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ branch }),
        });
        if (res.ok) {
          modal.remove();
          this.loadRepoListInAdmin();
          Toast.success(`已切换到分支 ${branch}`);
        } else {
          const err = await res.json().catch(() => ({ detail: '切换失败' }));
          throw new Error(err.detail || '切换失败');
        }
      } catch (e) {
        btn.disabled = false;
        btn.textContent = '切换';
        Toast.error(`切换分支失败: ${e.message}`);
      }
    };
  },

  /**
   * 浏览仓库（管理页面内）
   */
  async browseRepoInAdmin(repoId) {
    const old = document.getElementById('admin-browse-modal');
    if (old) old.remove();

    const modal = document.createElement('div');
    modal.id = 'admin-browse-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:2000;display:flex;align-items:center;justify-content:center;';
    modal.innerHTML = `
      <div style="background:white;border-radius:12px;padding:24px;width:640px;max-height:80vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
          <h3 style="font-size:16px;font-weight:600;"><span class="material-symbols-outlined" style="font-size:18px;vertical-align:-3px;">inventory_2</span> ${repoId}</h3>
          <button onclick="document.getElementById('admin-browse-modal').remove()" style="width:28px;height:28px;border:none;background:transparent;font-size:18px;color:var(--text-tertiary);cursor:pointer;">×</button>
        </div>
        <div style="display:flex;gap:8px;margin-bottom:12px;">
          <input type="text" id="admin-repo-search" placeholder="搜索代码关键词…" style="flex:1;height:34px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 12px;font-size:13px;">
          <button id="admin-repo-search-btn" style="padding:0 14px;background:var(--teal-700);color:white;border:none;border-radius:999px;cursor:pointer;font-size:13px;">搜索</button>
        </div>
        <div id="admin-repo-files" style="display:flex;flex-direction:column;gap:4px;">
          <div style="padding:20px;text-align:center;color:var(--text-tertiary);font-size:13px;">加载中…</div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

    // 加载文件列表
    try {
      const res = await fetch(`/api/repos/${repoId}/files?max_results=50`);
      const data = await res.json();
      this._renderRepoFilesInAdmin(data.files || [], repoId);
    } catch (e) {
      document.getElementById('admin-repo-files').innerHTML = `<div style="padding:20px;text-align:center;color:#DC2626;">加载失败</div>`;
    }

    // 搜索
    document.getElementById('admin-repo-search-btn').onclick = async () => {
      const q = document.getElementById('admin-repo-search').value.trim();
      if (!q) return;
      document.getElementById('admin-repo-files').innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-tertiary);">搜索中…</div>';
      try {
        const res = await fetch(`/api/repos/${repoId}/search`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: q }),
        });
        const data = await res.json();
        if (data.results && data.results.length > 0) {
          // 按文件分组
          const byFile = {};
          data.results.forEach(r => {
            if (!byFile[r.file]) byFile[r.file] = [];
            byFile[r.file].push(r);
          });

          document.getElementById('admin-repo-files').innerHTML = Object.entries(byFile).map(([file, results]) => {
            // git 作者信息(创建人/最后改动人),由搜索接口按文件富化
            const a = results[0];
            const authorBits = [];
            if (a.creator) authorBits.push(`创建 ${a.creator}`);
            if (a.last_modifier) authorBits.push(`最后修改 ${a.last_modifier}`);
            const authorText = authorBits.length ? `<span style="font-size:10px;color:var(--text-tertiary);">👤 ${authorBits.join(' · ')}</span>` : '';
            return `
            <div style="margin-bottom:12px;border:1px solid var(--border-light);border-radius:8px;overflow:hidden;">
              <div style="padding:8px 12px;background:var(--bg-page);font-size:12px;font-weight:600;font-family:monospace;border-bottom:1px solid var(--border-light);display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                <span style="color:var(--text-tertiary);"><span class="material-symbols-outlined" style="font-size:14px;vertical-align:-2px;">description</span></span>
                <span style="color:var(--text-primary);">${file}</span>
                ${authorText}
                <span style="font-size:10px;color:var(--text-tertiary);margin-left:auto;">${results.length} 处匹配</span>
              </div>
              ${results.map(r => `
                <div style="padding:8px 12px;border-bottom:1px solid var(--border-light);cursor:pointer;display:flex;gap:8px;align-items:flex-start;"
                     onclick="AdminModule._readRepoFileInAdmin('${repoId}','${r.file}',${r.line})"
                     onmouseover="this.style.background='var(--bg-hover)'"
                     onmouseout="this.style.background='transparent'">
                  <span style="font-size:11px;color:var(--text-tertiary);font-family:monospace;min-width:40px;text-align:right;flex-shrink:0;">${r.line}</span>
                  <span style="font-size:12px;font-family:monospace;color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${this._escapeHtml(r.content)}</span>
                </div>`).join('')}
            </div>`;
          }).join('');
        } else {
          document.getElementById('admin-repo-files').innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-tertiary);">未找到匹配</div>';
        }
      } catch (e) {
        document.getElementById('admin-repo-files').innerHTML = '<div style="padding:20px;text-align:center;color:#DC2626;">搜索失败</div>';
      }
    };
  },

  _renderRepoFilesInAdmin(files, repoId) {
    const list = document.getElementById('admin-repo-files');
    if (!files || files.length === 0) {
      list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-tertiary);">无文件</div>';
      return;
    }
    list.innerHTML = files.map(f => `
      <div style="padding:6px 10px;background:var(--bg-input);border-radius:6px;cursor:pointer;font-size:12px;display:flex;justify-content:space-between;" onclick="AdminModule._readRepoFileInAdmin('${repoId}','${f.path}')">
        <span style="font-family:monospace;"><span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">description</span> ${f.path}</span>
        <span style="color:var(--text-tertiary);font-size:10px;">${(f.size/1024).toFixed(1)}KB</span>
      </div>`).join('');
  },

  async _readRepoFileInAdmin(repoId, filePath, line = 1) {
    try {
      const res = await fetch(`/api/repos/${repoId}/read?file_path=${encodeURIComponent(filePath)}&start_line=${line}&end_line=${line+49}`);
      const data = await res.json();

      // 检测语言类型（根据文件扩展名）
      const ext = filePath.split('.').pop().toLowerCase();
      const langMap = {java:'java', py:'python', js:'javascript', ts:'javascript', xml:'xml', yaml:'yaml', yml:'yaml', md:'markdown', html:'xml'};
      const lang = langMap[ext] || '';

      // 生成带行号的代码块
      const lines = data.content.split('\n');
      const numberedLines = lines.map((line, idx) => {
        const lineNum = data.start_line + idx;
        return `<tr><td class="code-line-num">${lineNum}</td><td class="code-line-content">${this._escapeHtml(line)}</td></tr>`;
      }).join('');

      document.getElementById('admin-repo-files').innerHTML = `
        <div style="margin-bottom:8px;display:flex;align-items:center;gap:8px;">
          <button onclick="AdminModule.browseRepoInAdmin('${repoId}')" style="padding:4px 10px;border:1px solid var(--border-default);border-radius:999px;background:white;font-size:12px;cursor:pointer;">← 返回</button>
          <span style="font-size:12px;font-weight:500;font-family:monospace;"><span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">description</span> ${data.file}</span>
          <span style="font-size:11px;color:var(--text-tertiary);">L${data.start_line}-${data.end_line}/${data.total_lines}行</span>
          <span id="admin-repo-file-author" style="font-size:11px;color:var(--text-tertiary);"></span>
        </div>
        <div style="background:#0d1117;border-radius:8px;overflow:hidden;border:1px solid #30363d;">
          <table class="code-table" style="width:100%;border-collapse:collapse;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:12px;line-height:18px;">
            <tbody>${numberedLines}</tbody>
          </table>
        </div>
        <style>
          .code-line-num { padding:0 12px;text-align:right;color:#6e7681;user-select:none;background:#161b22;border-right:1px solid #30363d;vertical-align:top;width:1%;white-space:nowrap; }
          .code-line-content { padding:0 12px;color:#c9d1d9;vertical-align:top;white-space:pre; }
          .code-table tr:hover { background:#161b22; }
          .code-table tr:hover .code-line-num { background:#1c2128; }
        </style>
        <script>if (window.hljs) { hljs.highlightAll(); }</script>
      `;

      // 触发语法高亮
      if (window.hljs) {
        document.querySelectorAll('.code-line-content').forEach(el => {
          if (lang) {
            try {
              const result = hljs.highlight(el.textContent, {language: lang});
              el.innerHTML = result.value;
            } catch (e) { /* ignore */ }
          }
        });
      }

      // 异步补充 git 作者信息(创建人/最后改动人)
      fetch(`/api/repos/${repoId}/file-author?file_path=${encodeURIComponent(filePath)}`)
        .then(r => r.ok ? r.json() : null)
        .then(a => {
          const el = document.getElementById('admin-repo-file-author');
          if (!a || !el) return;
          const bits = [];
          if (a.creator) bits.push(`创建 ${a.creator.name}`);
          if (a.last_modifier) bits.push(`最后修改 ${a.last_modifier.name}`);
          if (bits.length) el.textContent = `👤 ${bits.join(' · ')}`;
        })
        .catch(() => {});
    } catch (e) { this._toast('读取失败: ' + e.message, 'error'); }
  },

  _escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },

  async pullRepoInAdmin(repoId) {
    this._toast('正在拉取最新代码…', 'success');
    try {
      const res = await fetch(`/api/repos/${repoId}/pull`, { method: 'POST' });
      if (res.ok) {
        this._toast('✓ 拉取成功', 'success');
      } else {
        this._toast('✕ 拉取失败', 'error');
      }
    } catch (e) { this._toast('✕ 拉取失败: ' + e.message, 'error'); }
  },

  async deleteRepoInAdmin(repoId) {
    const confirmed = await Toast.confirm(`确认删除仓库「${repoId}」？本地代码将被清除。`, '删除');
    if (!confirmed) return;
    try {
      const res = await fetch(`/api/repos/${repoId}`, { method: 'DELETE' });
      if (res.ok) {
        this.loadRepoListInAdmin();
        this._toast('✓ 仓库已删除', 'success');
      } else {
        // 后端删除失败（如本地目录被占用）时给出具体原因，不再静默报成功
        let msg = '删除失败';
        try { msg = (await res.json()).detail || msg; } catch (_) {}
        this._toast('✕ ' + msg, 'error');
      }
    } catch (e) { this._toast('✕ 删除失败: ' + e.message, 'error'); }
  },
  async loadTab(tabKey) {
    const config = this.TABS[tabKey];
    if (!config) return;

    const contentArea = document.querySelector('#app-admin .admin-table-wrap') ||
                        document.querySelector('#app-admin .app-page-inner');

    if (!contentArea) return;

    // 显示加载中
    const tableWrap = document.querySelector('#app-admin .admin-table-wrap');
    if (tableWrap) {
      tableWrap.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-tertiary);">加载中…</div>';
    }

    try {
      const res = await fetch(config.endpoint);
      const data = await res.json();
      this.cache[tabKey] = data;
      this.renderTab(tabKey, data);
    } catch (e) {
      if (tableWrap) {
        tableWrap.innerHTML = `<div style="padding:40px;text-align:center;color:var(--text-tertiary);">加载失败: ${e.message}</div>`;
      }
    }
  },

  /**
   * 渲染 Tab 内容
   */
  renderTab(tabKey, data) {
    const tableWrap = document.querySelector('#app-admin .admin-table-wrap');
    if (!tableWrap) return;

    if (tabKey === 'audit') {
      this.renderAuditTab(tableWrap, data);
      return;
    }

    if (tabKey === 'org') {
      this.renderOrgTab(tableWrap, data);
      return;
    }

    // 工具中心:卡片网格布局(替代标准表格)
    if (tabKey === 'tools') {
      this.renderToolsTab(tableWrap, Array.isArray(data) ? data : []);
      return;
    }

    // 标准 CRUD 表格
    const config = this.TABS[tabKey];
    const items = Array.isArray(data) ? data : [];

    const headers = {
      'resources': ['名称', '类型', 'Owner', '状态', '操作'],
      'skills': ['名称', 'Key', '类型', '版本', '状态', '风险', 'Owner', '操作'],
      'tools': ['名称', 'Key', '类型', '模式', '端点', '风险', 'Owner', '操作'],
      'role-packs': ['名称', '版本', 'Owner', '操作'],
      'agents': ['员工', '部门/领域', 'Owner', '版本', '生命周期', '操作'],
    };

    const cols = headers[tabKey] || ['名称', '类型', 'Owner', '操作'];

    let html = '';
    // 资源中心:检索条已移入文档资源卡片头部(rc-search-row),此处不再内嵌
    html += '<table class="admin-table"><thead><tr>';
    cols.forEach(h => html += `<th>${h}</th>`);
    html += '</tr></thead><tbody>';

    if (items.length === 0) {
      // 空态文案与实际操作入口保持一致(资源中心的按钮在卡片头右上角)
      const emptyText = tabKey === 'resources'
        ? '暂无文档，点击右上角「新增资源」或「上传文件」'
        : '暂无数据，点击下方按钮创建';
      html += `<tr><td colspan="${cols.length}" style="text-align:center;padding:30px;color:var(--text-tertiary);">${emptyText}</td></tr>`;
    }

    items.forEach(item => {
      html += '<tr>';
      if (tabKey === 'resources') {
        html += `<td>${msIcon(item.icon)} ${item.name}</td><td>${item.type}</td><td>${item.owner || '-'}</td><td>${item.status || 'ready'}</td>`;
      } else if (tabKey === 'skills') {
        const stateColors = {DRAFT:'#92400E', IN_REVIEW:'#2563EB', RELEASED:'#059669', RETIRED:'#737373'};
        const stateBg = {DRAFT:'#FEF3C7', IN_REVIEW:'#EFF6FF', RELEASED:'#ECFDF5', RETIRED:'#F3F4F6'};
        const st = item.state || 'RELEASED';
        html += `<td><span class="material-symbols-outlined" style="font-size:15px;vertical-align:-2px;">extension</span> ${item.name}</td>`;
        html += `<td style="font-family:monospace;font-size:12px;">${item.skill_key || '-'}</td>`;
        html += `<td>${item.type || '-'}</td>`;
        html += `<td>${item.version || '1.0.0'}</td>`;
        html += `<td><span style="padding:2px 8px;border-radius:12px;background:${stateBg[st]||'#F3F4F6'};color:${stateColors[st]||'#737373'};font-size:11px;font-weight:500;">${st}</span></td>`;
        html += `<td>${item.risk_level || 'LOW'}</td>`;
        html += `<td>${item.owner || '-'}</td>`;
      } else if (tabKey === 'tools') {
        const riskColors = {LOW:'#059669', MEDIUM:'#D97706', HIGH:'#DC2626'};
        html += `<td><span class="material-symbols-outlined" style="font-size:15px;vertical-align:-2px;">build</span> ${item.name}</td>`;
        html += `<td style="font-family:monospace;font-size:12px;">${item.tool_key || '-'}</td>`;
        html += `<td>${item.type || '-'}</td>`;
        html += `<td><span style="font-size:11px;padding:2px 6px;border-radius:4px;background:${item.mode === 'WRITE' ? '#FEE2E2' : '#ECFDF5'};color:${item.mode === 'WRITE' ? '#DC2626' : '#059669'};">${item.mode || 'READ_ONLY'}</span></td>`;
        html += `<td style="font-size:11px;max-width:180px;overflow:hidden;text-overflow:ellipsis;">${item.endpoint || '-'}</td>`;
        html += `<td><span style="color:${riskColors[item.risk_level]||'#737373'};font-weight:500;">${item.risk_level || 'LOW'}</span></td>`;
        html += `<td>${item.owner || '-'}</td>`;
      } else if (tabKey === 'role-packs') {
        html += `<td><span class="material-symbols-outlined" style="font-size:15px;vertical-align:-2px;">inventory_2</span> ${item.name}</td><td>${item.version}</td><td>${item.owner || '-'}</td>`;
      } else if (tabKey === 'agents') {
        const lcMap = { online: '已上线', indexing: '索引中', trial: '试运行', pending_check: '待校验', maintenance: '维护中' };
        html += `<td><div class="emp-cell"><div class="name">${item.emoji || ''} ${item.name}</div><div class="sub">${item.role || ''}</div></div></td>`;
        html += `<td>${item.department_id || '-'} / ${item.domain_id || '-'}</td>`;
        html += `<td>${item.owner || '-'}</td><td>${item.version}</td>`;
        html += `<td><span class="lifecycle-badge ${item.lifecycle}">${lcMap[item.lifecycle] || item.lifecycle}</span></td>`;
      }
      // 资源中心:已解析出 Markdown 的文档提供「预览」入口
      const previewBtn = (tabKey === 'resources' && (item.url || '').endsWith('/md'))
        ? `<button class="edit-btn" onclick="AdminModule.previewResource('${item.id}', '${(item.name || '').replace(/'/g, "\\'")}')">预览</button> ` : '';
      // 能力中心:提供只读「查看」入口,不用进编辑表单就能看 Skill 内容
      const skillViewBtn = (tabKey === 'skills')
        ? `<button class="edit-btn" onclick="AdminModule.viewSkill('${item.id}')">查看</button> ` : '';
      html += `<td>${previewBtn}${skillViewBtn}<button class="edit-btn" onclick="AdminModule.showEditModal('${tabKey}', '${item.id}')">编辑</button> <button class="edit-btn" style="color:#DC2626;" onclick="AdminModule.deleteItem('${tabKey}', '${item.id}', '${item.name || ''}')">删除</button></td>`;
      html += '</tr>';
    });

    html += '</tbody></table>';

    // 底部新增按钮（仅非审计 Tab）——工具行式自动宽药丸钮
    // 资源中心除外:其「新增资源/上传文件」已收进文档资源卡片头右上角
    if (tabKey !== 'audit' && tabKey !== 'org' && tabKey !== 'resources') {
      html += `<div class="add-agent-row">`;
      // 员工管理 Tab：用8步向导而非普通表单
      if (tabKey === 'agents') {
        html += `<button class="add-agent-btn" onclick="AdminModule.startWizard()"><span class="material-symbols-outlined">add</span> 新增Agent员工</button>`;
      } else {
        html += `<button class="add-agent-btn" onclick="AdminModule.showCreateModal()"><span class="material-symbols-outlined">add</span> 新增${config.label}</button>`;
      }
      // 资源中心额外增加上传文件按钮
      if (tabKey === 'resources') {
        html += `<button class="add-agent-btn" onclick="AdminModule.showUploadModal()"><span class="material-symbols-outlined">upload_file</span> 上传文件</button>`;
      }
      // 能力中心：AI 生成（生成→校验→自修复循环）+ 导入本地 SKILL.md/Manifest
      if (tabKey === 'skills') {
        html += `<button class="add-agent-btn" onclick="AdminModule.showSkillAIGenModal()"><span class="material-symbols-outlined">auto_awesome</span> AI 生成</button>`;
        html += `<button class="add-agent-btn" onclick="AdminModule.showSkillImportModal()"><span class="material-symbols-outlined">download</span> 导入</button>`;
      }
      // 工具中心：连接 MCP Server（粘贴 mcpServers JSON → 测试连接 → 落库）
      if (tabKey === 'tools') {
        html += `<button class="add-agent-btn" onclick="AdminModule.showMcpConnectModal()"><span class="material-symbols-outlined">cable</span> 连接 MCP Server</button>`;
      }
      html += `</div>`;
    }

    // 资源中心 Tab 特殊处理:文档资源 + 代码仓库拆成两张独立卡片(第 7 轮 #39)
    // html 此时是文档表格,嵌进文档卡;仓库卡挂列表与前置条件条
    if (tabKey === 'resources') {
      tableWrap.classList.add('resources-split');
      html = `
        <div class="rc-card">
          <div class="rc-card-head">
            <div>
              <h3><span class="material-symbols-outlined" style="font-size:17px;">description</span> 文档资源</h3>
              <p class="rc-sub">公司知识文档，AI 员工检索后用于回答</p>
            </div>
            <div class="rc-head-actions">
              <button class="add-agent-btn" onclick="AdminModule.showCreateModal()"><span class="material-symbols-outlined">add</span> 新增资源</button>
              <button class="add-agent-btn" onclick="AdminModule.showUploadModal()"><span class="material-symbols-outlined">upload_file</span> 上传文件</button>
            </div>
          </div>
          <div class="rc-search-row">
            <input id="resource-search-input" type="text" placeholder="搜索文档名称或正文内容，回车确认…"
              style="flex:1;height:38px;background:var(--bg-input);border:1px solid transparent;border-radius:999px;padding:0 18px;font-size:14px;"
              onkeydown="if(event.key==='Enter')AdminModule.searchResources()">
            <button onclick="AdminModule.searchResources()" style="padding:0 18px;border:none;border-radius:999px;background:var(--teal-700);color:white;font-size:14px;cursor:pointer;"><span class="material-symbols-outlined">search</span> 搜索</button>
          </div>
          <div id="rc-doc-body">${html}</div>
        </div>
        <div class="rc-card">
          <div class="rc-card-head">
            <div>
              <h3><span class="material-symbols-outlined" style="font-size:17px;">folder_open</span> 代码仓库</h3>
              <p class="rc-sub">接入 Git 仓库后，AI 员工可检索代码回答问题</p>
            </div>
            <div class="rc-head-actions">
              <button class="add-agent-btn" onclick="AdminModule.showCloneRepoModal()"><span class="material-symbols-outlined">add</span> 接入仓库</button>
            </div>
          </div>
          <div id="admin-repo-list" style="display:flex;flex-direction:column;gap:8px;padding:12px 16px;">
            <div style="padding:24px;text-align:center;color:var(--text-tertiary);background:var(--bg-page);border-radius:8px;font-size:13px;">加载中…</div>
          </div>
          <div id="admin-repo-env" style="margin:0 16px 14px;padding:10px 12px;background:var(--bg-hover);border-radius:8px;font-size:12px;color:var(--text-secondary);">
            <strong><span class="material-symbols-outlined" style="font-size:14px;vertical-align:-2px;">checklist</span> 拉取仓库前置条件：</strong>
            服务器已安装 Git CLI · 支持 HTTPS/SSH 协议 · 私有仓库需配置访问凭证
          </div>
        </div>`;
    } else {
      tableWrap.classList.remove('resources-split');
    }

    tableWrap.innerHTML = html;

    // 资源中心 Tab：异步加载仓库列表
    if (tabKey === 'resources') {
      this.loadRepoListInAdmin();
    }
  },

  /**
   * 渲染组织管理 Tab — 卡片式布局（对齐 Figma 27:2）
   */
  renderOrgTab(container, data) {
    let html = '<div style="display:flex;flex-direction:column;gap:12px;">';
    if (!data || data.length === 0) {
      html += '<div style="text-align:center;padding:40px;color:var(--text-tertiary);">暂无部门，点击下方按钮创建</div>';
    }
    data.forEach(dept => {
      const domainTags = (dept.domains || []).map(dm =>
        `<span style="display:inline-flex;align-items:center;gap:4px;padding:5px 12px;background:var(--bg-input);border-radius:20px;font-size:12px;color:var(--text-primary);cursor:pointer;"
          onclick="AdminModule.showEditModal('domain','${dm.id}')"
          title="点击编辑领域">
          <span style="width:6px;height:6px;border-radius:50%;background:#171717;display:inline-block;"></span>
          ${dm.name}
        </span>`
      ).join('');

      html += `
        <div style="background:white;border:1px solid var(--border-light);border-radius:12px;padding:17px 21px;box-shadow:var(--shadow-card);">
          <!-- 部门卡片头部 -->
          <div style="display:flex;align-items:center;justify-content:space-between;">
            <div style="display:flex;align-items:center;gap:12px;flex:1;">
              <span style="font-size:22px;">${msIcon(dept.emoji, 'inventory_2', 22)}</span>
              <div style="flex:1;">
                <div style="display:flex;align-items:center;gap:8px;">
                  <span style="font-size:16px;font-weight:500;color:var(--text-primary);">${dept.name}</span>
                  <span style="font-size:11px;color:#059669;background:#ECFDF5;padding:2px 8px;border-radius:12px;">· 对接人已配置</span>
                </div>
                <div style="font-size:13px;color:var(--text-secondary);margin-top:2px;">${dept.description || ''}</div>
              </div>
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
              <span style="font-size:11px;padding:3px 9px;background:#ECFDF5;color:#059669;border-radius:12px;font-weight:500;">启用</span>
              <button class="edit-btn" onclick="AdminModule.showEditModal('dept','${dept.id}')">编辑</button>
              <button class="edit-btn" style="color:#DC2626;" onclick="AdminModule.deleteItem('dept','${dept.id}','${dept.name}')">删除</button>
            </div>
          </div>
          <!-- 领域标签行 -->
          <div style="margin-top:16px;padding-left:34px;display:flex;flex-wrap:wrap;gap:8px;align-items:center;">
            ${domainTags}
            <button style="padding:5px 12px;border:1px dashed var(--border-default);border-radius:20px;background:transparent;font-size:12px;color:var(--text-secondary);cursor:pointer;"
              onclick="AdminModule.showCreateDomainModal('${dept.id}')">
              + 领域
            </button>
          </div>
        </div>
      `;
    });
    html += `
      <button style="padding:12px;border:1px dashed var(--border-default);border-radius:12px;background:transparent;font-size:14px;color:var(--text-secondary);cursor:pointer;margin-top:4px;"
        onclick="AdminModule.showCreateModal('dept')">
        ＋ 新增部门
      </button>
    `;
    html += '</div>';
    container.innerHTML = html;
  },

  /**
   * 新增领域模态框（快捷入口）
   */
  showCreateDomainModal(deptId) {
    const fields = [
      { name: 'name', label: '领域名称', type: 'text', value: '', required: true },
      { name: 'department_id', label: '所属部门 ID', type: 'text', value: deptId, required: true },
      { name: 'description', label: '描述', type: 'text', value: '' },
    ];
    this.showModal('新增领域', fields, null, 'domains');
  },

  /**
   * 渲染审计 Tab
   */
  renderAuditTab(container, logs) {
    // 权限策略概览
    let html = `
      <div style="padding:20px;">
        <div style="margin-bottom:24px;padding:16px;background:#ECFDF5;border-radius:8px;">
          <h4 style="font-size:14px;font-weight:600;margin-bottom:8px;"><span class="material-symbols-outlined" style="font-size:15px;vertical-align:-2px;">admin_panel_settings</span> 权限策略</h4>
          <ul style="font-size:13px;color:var(--text-secondary);line-height:22px;">
            <li>✓ 所有工具调用经过 PEP（Policy Enforcement Point）</li>
            <li>✓ Agent 只能访问其 Role Pack 中声明的资源</li>
            <li>✓ 跨部门协作需部门对接人授权</li>
            <li>✓ 知识候选审核通过前不参与共享检索</li>
            <li>✓ 证据打开时执行二次 ACL 校验</li>
          </ul>
        </div>
        <h4 style="font-size:14px;font-weight:600;margin-bottom:12px;"><span class="material-symbols-outlined" style="font-size:15px;vertical-align:-2px;">fact_check</span> 知识候选审核</h4>
        <div id="kc-review-queue" style="margin-bottom:24px;">
          <div style="text-align:center;padding:20px;color:var(--text-tertiary);font-size:13px;">加载中…</div>
        </div>
        <h4 style="font-size:14px;font-weight:600;margin-bottom:12px;"><span class="material-symbols-outlined" style="font-size:15px;vertical-align:-2px;">assignment</span> 审计日志</h4>
    `;

    if (!logs || logs.length === 0) {
      html += '<div style="text-align:center;padding:40px;color:var(--text-tertiary);">暂无审计日志</div>';
    } else {
      html += '<table class="admin-table"><thead><tr><th>操作人</th><th>动作</th><th>对象</th><th>详情</th><th>时间</th></tr></thead><tbody>';
      logs.forEach(l => {
        const actionColors = { create: '#059669', update: '#2563EB', delete: '#DC2626', login: '#737373' };
        const color = actionColors[l.action] || '#737373';
        html += `<tr>
          <td>${l.actor}</td>
          <td><span style="color:${color};font-weight:500;">${l.action}</span></td>
          <td>${l.target_type}: ${l.target_name || '-'}</td>
          <td style="font-size:12px;color:var(--text-secondary);">${l.detail || ''}</td>
          <td style="font-size:12px;color:var(--text-tertiary);">${l.created_at}</td>
        </tr>`;
      });
      html += '</tbody></table>';
    }
    html += '</div>';
    container.innerHTML = html;
    // 异步加载知识候选审核队列(SUBMITTED/IN_REVIEW 可操作)
    this.loadKnowledgeCandidates();
  },

  /**
   * 加载知识候选审核队列(对话沉淀入口提交的候选在这里审核)
   */
  async loadKnowledgeCandidates() {
    const wrap = document.getElementById('kc-review-queue');
    if (!wrap) return;
    try {
      const res = await fetch('/api/gov/knowledge-candidates?limit=50');
      const items = await res.json();
      if (!Array.isArray(items) || items.length === 0) {
        wrap.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-tertiary);font-size:13px;">暂无知识候选</div>';
        return;
      }
      const stateMeta = {
        SUBMITTED: { label: '待审核', color: '#B45309', bg: '#FFFBEB' },
        IN_REVIEW: { label: '审核中', color: '#2563EB', bg: '#EFF6FF' },
        APPROVED:  { label: '已通过', color: '#059669', bg: '#ECFDF5' },
        REJECTED:  { label: '已驳回', color: '#DC2626', bg: '#FEF2F2' },
        EXPIRED:   { label: '已失效', color: '#737373', bg: '#F5F5F5' },
      };
      const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      let html = '';
      items.forEach(k => {
        const st = stateMeta[k.state] || { label: k.state, color: '#737373', bg: '#F5F5F5' };
        const actionable = ['SUBMITTED', 'IN_REVIEW', 'EXPIRED'].includes(k.state);
        html += `
          <div style="border:1px solid var(--border-default);border-radius:10px;padding:12px 14px;margin-bottom:10px;background:white;">
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
              <span style="font-weight:600;font-size:13.5px;">${esc(k.title)}</span>
              <span style="font-size:11px;padding:2px 8px;border-radius:10px;color:${st.color};background:${st.bg};">${st.label}</span>
              <span style="font-size:12px;color:var(--text-tertiary);">${esc(k.owner)} · ${esc(k.domain)} · ${esc(k.created_at)}</span>
              <span style="margin-left:auto;display:flex;gap:8px;">
                ${actionable ? `
                <button onclick="AdminModule.reviewKnowledgeCandidate('${k.id}','APPROVE')"
                  style="padding:4px 12px;border:none;border-radius:999px;background:#0D9488;color:white;font-size:12px;cursor:pointer;">通过</button>
                <button onclick="AdminModule.reviewKnowledgeCandidate('${k.id}','REJECT')"
                  style="padding:4px 12px;border:1px solid #DC2626;border-radius:999px;background:white;color:#DC2626;font-size:12px;cursor:pointer;">驳回</button>` : ''}
              </span>
            </div>
            ${k.body_md ? `<details style="margin-top:8px;"><summary style="font-size:12px;color:var(--text-tertiary);cursor:pointer;">查看正文</summary><pre style="white-space:pre-wrap;font-size:12.5px;line-height:1.7;background:#F7FBFA;border-radius:8px;padding:10px 12px;margin:8px 0 0;max-height:260px;overflow:auto;">${esc(k.body_md)}</pre></details>` : ''}
          </div>`;
      });
      wrap.innerHTML = html;
    } catch (e) {
      console.warn('[admin] 知识候选队列加载失败', e);
      wrap.innerHTML = '<div style="text-align:center;padding:20px;color:#DC2626;font-size:13px;">加载失败,请刷新重试</div>';
    }
  },

  /**
   * 审核知识候选(通过/驳回),通过后进入共享检索
   */
  async reviewKnowledgeCandidate(id, decision) {
    try {
      const res = await fetch(`/api/gov/knowledge-candidates/${id}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, reviewer: 'admin', scope: 'COMPANY' }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '审核失败');
      Toast.success(data.message || '审核完成');
      this.loadKnowledgeCandidates();
    } catch (e) {
      console.warn('[admin] 知识候选审核失败', e);
      Toast.error(`审核失败: ${e.message}`);
    }
  },

  /**
   * 显示新增模态框
   */
  showCreateModal(subType) {
    // 修正 tab 名：dept -> departments, domain -> domains
    let tab = subType || this.activeTab;
    tab = tab === 'dept' ? 'departments' : (tab === 'domain' ? 'domains' : tab);
    const fields = this.getFormFields(tab);
    this.showModal(`新增${this.TABS[tab]?.label || tab}`, fields, null, tab);
  },

  /**
   * 显示编辑模态框
   */
  showEditModal(tab, id) {
    const items = this.cache[tab] || [];
    let item = items.find(i => i.id === id);

    // org tab 特殊处理
    if (tab === 'dept' || tab === 'domain') {
      // 在 org 数据中查找
      const orgData = this.cache['org'] || [];
      for (const dept of orgData) {
        if (tab === 'dept' && dept.id === id) { item = dept; break; }
        if (tab === 'domain') {
          for (const dm of (dept.domains || [])) {
            if (dm.id === id) { item = dm; break; }
          }
        }
      }
      tab = tab === 'dept' ? 'departments' : 'domains';
    }

    if (!item) return;

    const fields = this.getFormFields(tab, item);
    this.showModal(`编辑${this.TABS[this.activeTab]?.label || ''}`, fields, item.id, tab);
  },

  /**
   * 获取表单字段定义
   */
  getFormFields(tab, item = null) {
    // AI 生成草案预填：新建（item 为空）时优先读 _draft（采用后由 adoptAIGenDraft 清空）
    const draft = this._draft || {};
    const val = (key, def = '') => item && item[key] !== undefined ? item[key]
      : (draft[key] !== undefined ? draft[key] : def);

    const fieldSets = {
      'resources': [
        { name: 'name', label: '资源名称', type: 'text', value: val('name'), required: true },
        { name: 'type', label: '类型', type: 'select', value: val('type', 'document'), options: {'service': '服务', 'document': '文档', 'dataset': '数据集', 'knowledge': '知识库'} },
        { name: 'icon', label: '图标', type: 'text', value: val('icon', '📄') },
        { name: 'description', label: '描述', type: 'textarea', value: val('description') },
        { name: 'url', label: 'URL', type: 'text', value: val('url') },
        { name: 'owner', label: 'Owner', type: 'text', value: val('owner') },
      ],
      // skills 字段较多:half=两列网格、group=分组标题、rows=textarea 行数、mono=等宽字体
      'skills': [
        { name: 'name', label: '能力名称', type: 'text', value: val('name'), required: true, half: true, group: '基本信息' },
        { name: 'skill_key', label: 'Skill Key（唯一标识）', type: 'text', value: val('skill_key'), placeholder: '如 call-chain', half: true },
        { name: 'type', label: '类型', type: 'select', value: val('type', 'search'), options: {'search': '检索', 'analysis': '分析', 'generation': '生成', 'api': 'API', 'workflow': '工作流'}, half: true },
        { name: 'version', label: '版本', type: 'text', value: val('version', '1.0.0'), half: true },
        { name: 'state', label: '状态', type: 'select', value: val('state', 'RELEASED'), options: {'DRAFT': '草稿', 'IN_REVIEW': '审核中', 'RELEASED': '已发布', 'RETIRED': '已下线'}, half: true, group: '状态与归属' },
        { name: 'risk_level', label: '风险等级', type: 'select', value: val('risk_level', 'LOW'), options: {'LOW': '低', 'MEDIUM': '中', 'HIGH': '高'}, half: true },
        { name: 'owner', label: 'Owner', type: 'text', value: val('owner'), half: true },
        { name: 'description', label: '描述（步骤编排/前置条件/输出契约）', type: 'textarea', value: val('description'), rows: 4, group: '内容' },
        { name: 'instructions', label: '指令体（SKILL.md 正文，运行时注入提示词）', type: 'textarea', value: val('instructions'), placeholder: 'Markdown 指令：执行步骤、约束、输出格式…（≥50 字）', rows: 8 },
        { name: 'config', label: 'Skill Manifest（YAML/JSON）', type: 'textarea', value: val('config'), placeholder: '可选：粘贴 Skill Manifest YAML', rows: 6, mono: true },
      ],
      'tools': [
        { name: 'name', label: '工具名称', type: 'text', value: val('name'), required: true },
        { name: 'tool_key', label: 'Tool Key（唯一标识）', type: 'text', value: val('tool_key'), placeholder: '如 searchCode' },
        { name: 'type', label: '类型', type: 'select', value: val('type', 'mcp'), options: {'mcp': 'MCP', 'api': 'API', 'internal': '内部工具'} },
        { name: 'mode', label: '权限模式', type: 'select', value: val('mode', 'READ_ONLY'), options: {'READ_ONLY': '只读（推荐）', 'WRITE': '可写（需审批）'} },
        { name: 'endpoint', label: '端点 URL', type: 'text', value: val('endpoint'), placeholder: 'MCP Server 地址或 API endpoint' },
        { name: 'risk_level', label: '风险等级', type: 'select', value: val('risk_level', 'LOW'), options: {'LOW': '低', 'MEDIUM': '中', 'HIGH': '高'} },
        { name: 'timeout_ms', label: '超时（毫秒）', type: 'text', value: val('timeout_ms', '5000') },
        { name: 'description', label: '描述（输入/输出 Schema）', type: 'textarea', value: val('description') },
        { name: 'config', label: 'Config（JSON：headers/transport）', type: 'textarea', value: val('config'), placeholder: '{"headers":{"appKey":"..."},"transport":"sse"}' },
        { name: 'read_only', label: '只读（兼容旧字段）', type: 'select', value: val('read_only', 'true'), options: {'true': '是', 'false': '否'} },
        { name: 'owner', label: 'Owner', type: 'text', value: val('owner') },
      ],
      'role-packs': [
        { name: 'name', label: '岗位名称', type: 'text', value: val('name'), required: true },
        { name: 'version', label: '版本', type: 'text', value: val('version', '1.0.0') },
        { name: 'owner', label: 'Owner', type: 'text', value: val('owner') },
        // MCP 工具勾选（存 config.tools）：内置工具恒定全开不进选项；勾选=为该岗位包开通对应 MCP Server
        { name: 'tools', label: 'MCP 工具（勾选开通；内置工具默认全开）', type: 'multiselect',
          value: (item && item.config && Array.isArray(item.config.tools)) ? item.config.tools : [],
          source: '/api/admin/tools/options', valueKey: 'value', labelKey: 'label' },
      ],
      'agents': [
        { name: 'name', label: '员工姓名', type: 'text', value: val('name'), required: true },
        { name: 'title', label: '职位', type: 'text', value: val('role', val('title')), required: true },
        { name: 'emoji', label: '头像 Emoji', type: 'text', value: val('emoji', '🧑‍💻') },
        { name: 'department_id', label: '所属部门', type: 'asyncselect', value: val('department_id'), source: '/api/admin/departments', valueKey: 'id', labelKey: 'name', placeholder: '- 选择部门 -' },
        { name: 'domain_id', label: '所属领域', type: 'asyncselect', value: val('domain_id'), source: '/api/admin/domains', valueKey: 'id', labelKey: 'name', placeholder: '- 选择领域 -' },
        { name: 'status', label: '生命周期', type: 'select', value: val('status', 'online'), options: {'online': '已上线', 'indexing': '索引中', 'trial': '试运行', 'pending_check': '待校验', 'maintenance': '维护中'} },
        { name: 'owner', label: 'Owner', type: 'text', value: val('owner') },
        { name: 'description', label: '职责描述', type: 'textarea', value: val('description') },
        // Harness Engineering：直绑能力（skill_key 列表，优先于岗位包配置）+ 行为准则
        { name: 'skills', label: '绑定能力（Skills，直绑优先于岗位包）', type: 'multiselect', value: val('skills', []), source: '/api/admin/skills', valueKey: 'skill_key', labelKey: 'name' },
        // 直绑 MCP 工具（直绑优先于岗位包）：内置工具恒定全开不进选项；勾选=为该员工开通对应 MCP Server
        { name: 'tools', label: 'MCP 工具（勾选开通，直绑优先于岗位包；内置工具默认全开）', type: 'multiselect', value: val('tools', []), source: '/api/admin/tools/options', valueKey: 'value', labelKey: 'label' },
        // 直绑知识资源（资源中心已上传文档）：勾选后该员工可见文档收敛到勾选范围；全不勾=全部文档可见
        { name: 'resources', label: '知识资源（已上传文档，勾选绑定；全不勾=全部可见）', type: 'multiselect', value: val('resources', []), source: '/api/admin/resources?type=document', valueKey: 'name', labelKey: 'name' },
        // 绑定代码仓库（AgentRepoBinding 同步）：绑定后代码检索工具自动限定在授权仓库范围内
        { name: 'repo_ids', label: '绑定代码仓库（限定代码检索范围，不绑=全局）', type: 'multiselect', value: val('repo_ids', []), source: '/api/gov/repositories', valueKey: 'id', labelKey: 'name' },
        { name: 'agents_md', label: '行为准则（AGENTS.md）', type: 'textarea', value: val('agents_md'), placeholder: 'Markdown 格式：角色边界、输出规范、禁忌事项…' },
      ],
      'departments': [
        { name: 'name', label: '部门名称', type: 'text', value: val('name'), required: true },
        { name: 'emoji', label: '图标', type: 'text', value: val('emoji', '📦') },
        { name: 'description', label: '描述', type: 'text', value: val('description') },
      ],
      'domains': [
        { name: 'name', label: '领域名称', type: 'text', value: val('name'), required: true },
        { name: 'department_id', label: '所属部门 ID', type: 'text', value: val('department_id'), required: true },
        { name: 'description', label: '描述', type: 'text', value: val('description') },
      ],
    };

    return fieldSets[tab] || [];
  },

  /**
   * 资源中心检索:调用后端 /resources/search,渲染命中列表(名称/正文徽章+片段高亮)
   * 关键词为空时恢复完整列表
   */
  async searchResources() {
    const input = document.getElementById('resource-search-input');
    const q = (input && input.value || '').trim();
    if (!q) { this.loadTab('resources'); return; }
    // 双卡布局下只覆写文档卡内容区,保留卡片头与代码仓库卡
    const docBody = document.getElementById('rc-doc-body');
    if (!docBody) return;

    const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    let hits;
    try {
      hits = await fetch(`/api/admin/resources/search?q=${encodeURIComponent(q)}`).then(r => r.json());
    } catch (e) {
      docBody.innerHTML = `<div style="padding:30px;text-align:center;color:#DC2626;">搜索失败:${esc(e.message)}</div>`;
      return;
    }

    // 高亮片段中的关键词(先转义再包 <mark>)
    const mark = (text) => esc(text).replace(new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'), m => `<mark style="background:#FEF3C7;padding:0 2px;border-radius:2px;">${m}</mark>`);

    let html = `<div style="padding:12px 16px 0;font-size:13px;color:var(--text-secondary);">
      关键词「${esc(q)}」命中 ${hits.length} 条 <a href="javascript:AdminModule.loadTab('resources')" style="color:var(--teal-700);">清空返回</a></div>
      <div style="padding:12px 16px;">`;
    if (!hits.length) {
      html += `<div style="padding:40px;text-align:center;color:var(--text-tertiary);">没有找到匹配的文档</div>`;
    }
    hits.forEach(h => {
      const badge = h.match_in === 'content'
        ? '<span style="font-size:11px;padding:2px 8px;border-radius:10px;background:#EFF6FF;color:#2563EB;">正文命中</span>'
        : '<span style="font-size:11px;padding:2px 8px;border-radius:10px;background:#F3F4F6;color:#737373;">名称命中</span>';
      html += `<div style="padding:14px 16px;border:1px solid var(--border-default,#e5e5e5);border-radius:10px;margin-bottom:10px;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:${h.snippet ? '8px' : '0'};">
          <span style="font-size:15px;font-weight:600;">${msIcon(h.icon)} ${esc(h.name)}</span>${badge}
          <span style="flex:1;"></span>
          ${(h.id) ? `<button class="edit-btn" onclick="AdminModule.previewResource('${h.id}', '${esc(h.name).replace(/'/g, "\\'")}')">预览</button>` : ''}
        </div>
        ${h.snippet ? `<div style="font-size:13px;color:var(--text-secondary);line-height:1.7;">${mark(h.snippet)}</div>` : ''}
      </div>`;
    });
    html += '</div>';
    docBody.innerHTML = html;
  },

  /**
   * 预览资源 Markdown 全文:三段式弹窗,正文用 ChatModule.renderMarkdown 渲染(守卫调用)
   */
  async previewResource(id, name) {
    const old = document.getElementById('admin-preview-modal');
    if (old) old.remove();

    const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const modal = document.createElement('div');
    modal.id = 'admin-preview-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:1000;display:flex;align-items:center;justify-content:center;';
    modal.innerHTML = `
      <div style="background:white;border-radius:12px;width:860px;max-width:94vw;max-height:88vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
        <div style="display:flex;align-items:center;padding:18px 28px;border-bottom:1px solid var(--border-default,#e5e5e5);">
          <h3 style="font-size:17px;font-weight:600;margin:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(name)}</h3>
          <button onclick="document.getElementById('admin-preview-modal').remove()" style="width:30px;height:30px;border:none;background:transparent;font-size:20px;color:var(--text-tertiary);cursor:pointer;">×</button>
        </div>
        <div id="admin-preview-body" class="ai-answer-content" style="flex:1;overflow-y:auto;padding:24px 32px;font-size:14px;line-height:1.8;">正在加载文档内容…</div>
      </div>`;
    document.body.appendChild(modal);
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

    const body = document.getElementById('admin-preview-body');
    try {
      const data = await fetch(`/api/admin/resources/${id}/md`).then(r => r.json());
      if (data.content) {
        // 优先复用聊天模块的 Markdown 渲染;不存在时退化为转义纯文本
        body.innerHTML = (window.ChatModule && ChatModule.renderMarkdown)
          ? ChatModule.renderMarkdown(data.content)
          : `<pre style="white-space:pre-wrap;font-family:inherit;">${esc(data.content)}</pre>`;
      } else {
        body.textContent = data.detail || '该文档暂无解析内容';
      }
    } catch (e) {
      body.innerHTML = `<div style="color:#DC2626;">加载失败:${esc(e.message)}</div>`;
    }
  },

  /**
   * 工具中心卡片网格渲染(名称大字+端点+徽章+操作按钮)
   */
  renderToolsTab(container, items) {
    const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    // 底部操作行：连接 MCP Server（引导式，推荐）+ 手动新增工具（标准表单）
    const actionRow = `<div class="add-agent-row" style="display:flex;gap:8px;margin-top:14px;">
      <button class="add-agent-btn" onclick="AdminModule.showMcpConnectModal()"><span class="material-symbols-outlined">cable</span> 连接 MCP Server（推荐）</button>
      <button class="add-agent-btn" onclick="AdminModule.showCreateModal('tools')"><span class="material-symbols-outlined">add</span> 手动新增工具</button>
    </div>`;
    if (!items.length) {
      container.innerHTML = `<div style="padding:40px;text-align:center;color:var(--text-tertiary);">暂无工具，点击下方按钮连接 MCP Server 或手动新增</div>` + actionRow;
      return;
    }
    const riskColors = {LOW:'#059669', MEDIUM:'#D97706', HIGH:'#DC2626'};
    const riskBg = {LOW:'#ECFDF5', MEDIUM:'#FEF3C7', HIGH:'#FEE2E2'};
    const cards = items.map(item => {
      const mode = item.mode || 'READ_ONLY';
      const risk = item.risk_level || 'LOW';
      const isMcp = !!item.endpoint;
      const viewBtn = isMcp
        ? `<button class="edit-btn" style="font-size:13px;" onclick="AdminModule.viewMcpTools('${item.id}', '${esc(item.name).replace(/'/g, "\\'")}')">查看工具</button> ` : '';
      return `<div style="background:white;border:1px solid var(--border-default,#e5e5e5);border-radius:12px;padding:18px 20px;display:flex;flex-direction:column;gap:8px;">
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="font-size:16px;font-weight:600;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"><span class="material-symbols-outlined" style="font-size:16px;vertical-align:-2px;">build</span> ${esc(item.name)}</span>
          <span style="font-size:11px;padding:2px 8px;border-radius:10px;background:var(--bg-hover,#f3f4f6);color:var(--text-secondary);">${esc(item.type || '-')}</span>
        </div>
        <div style="font-family:Consolas,Menlo,monospace;font-size:12px;color:var(--text-tertiary);">${esc(item.tool_key || '-')}</div>
        <div style="font-size:12px;color:var(--text-tertiary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(item.endpoint || '')}">${esc(item.endpoint || '（内置工具，无端点）')}</div>
        <div style="display:flex;gap:6px;align-items:center;">
          <span style="font-size:11px;padding:2px 8px;border-radius:4px;background:${mode === 'WRITE' ? '#FEE2E2' : '#ECFDF5'};color:${mode === 'WRITE' ? '#DC2626' : '#059669'};">${esc(mode)}</span>
          <span style="font-size:11px;padding:2px 8px;border-radius:4px;background:${riskBg[risk]||'#F3F4F6'};color:${riskColors[risk]||'#737373'};">${esc(risk)}</span>
          <span style="font-size:11px;color:var(--text-tertiary);margin-left:auto;">${esc(item.owner || '')}</span>
        </div>
        <div style="border-top:1px solid var(--border-default,#e5e5e5);padding-top:10px;margin-top:2px;">
          ${viewBtn}<button class="edit-btn" style="font-size:13px;" onclick="AdminModule.showEditModal('tools', '${item.id}')">编辑</button>
          <button class="edit-btn" style="color:#DC2626;font-size:13px;" onclick="AdminModule.deleteItem('tools', '${item.id}', '${esc(item.name).replace(/'/g, "\\'")}')">删除</button>
        </div>
      </div>`;
    }).join('');
    container.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px;">${cards}</div>` + actionRow;
  },

  /**
   * MCP 工具清单渲染(共享:查看工具弹窗与接入测试弹窗复用)
   * 每个工具一小卡:等宽名称+描述+有 input_schema 时折叠参数表
   */
  _renderMcpToolList(tools) {
    const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    if (!tools || !tools.length) {
      return '<div style="font-size:12px;color:var(--text-tertiary);">（该 server 未暴露任何工具）</div>';
    }
    return tools.map(t => {
      // 参数表:input_schema.properties 逐行(名称/类型/必填/描述)
      let schemaHtml = '';
      const props = t.input_schema && t.input_schema.properties;
      if (props && Object.keys(props).length) {
        const required = new Set(t.input_schema.required || []);
        const rows = Object.entries(props).map(([pname, p]) => `<tr>
          <td style="padding:4px 8px;font-family:Consolas,Menlo,monospace;font-size:11px;">${esc(pname)}</td>
          <td style="padding:4px 8px;font-size:11px;color:var(--text-secondary);">${esc(p.type || '-')}</td>
          <td style="padding:4px 8px;font-size:11px;white-space:nowrap;">${required.has(pname) ? '<span style="color:#DC2626;">必填</span>' : '可选'}</td>
          <td style="padding:4px 8px;font-size:11px;color:var(--text-tertiary);">${esc(p.description || '')}</td>
        </tr>`).join('');
        schemaHtml = `<details style="margin-top:6px;">
          <summary style="font-size:11px;color:var(--text-secondary);cursor:pointer;">参数 (${Object.keys(props).length})</summary>
          <table style="width:100%;border-collapse:collapse;margin-top:4px;background:var(--bg-hover,#f9fafb);border-radius:6px;">${rows}</table>
        </details>`;
      }
      return `<div style="padding:8px 10px;border-radius:8px;background:var(--bg-hover,#f9fafb);margin-top:6px;">
        <div style="font-family:Consolas,Menlo,monospace;font-size:12px;font-weight:600;">${esc(t.name)}</div>
        <div style="font-size:12px;color:var(--text-secondary);margin-top:2px;">${esc(t.description || '无描述')}</div>
        ${schemaHtml}
      </div>`;
    }).join('');
  },

  /**
   * 查看 Skill 内容(只读弹窗):基本信息 + 描述 + 指令体(Markdown 渲染) + Manifest
   * 数据取自 skills 缓存,不进编辑表单即可通读 Skill 全文
   */
  viewSkill(id) {
    const items = this.cache['skills'] || [];
    const item = items.find(s => String(s.id) === String(id));
    if (!item) { this._toast('未找到该 Skill', 'error'); return; }
    const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const old = document.getElementById('admin-skill-view-modal');
    if (old) old.remove();

    // 指令体优先用聊天模块的 Markdown 渲染,退化转义纯文本
    const instrHtml = item.instructions
      ? ((window.ChatModule && ChatModule.renderMarkdown)
          ? ChatModule.renderMarkdown(item.instructions)
          : `<pre style="white-space:pre-wrap;font-family:inherit;margin:0;">${esc(item.instructions)}</pre>`)
      : '<div style="color:var(--text-tertiary);font-size:13px;">（未填写指令体）</div>';
    const section = (label, inner) => `
      <div style="margin-top:16px;">
        <div style="font-size:13px;font-weight:600;color:var(--text-secondary);margin-bottom:6px;padding-bottom:4px;border-bottom:1px solid var(--border-default,#e5e5e5);">${label}</div>
        ${inner}
      </div>`;
    const metaRow = (k, v) => `<div style="display:flex;font-size:13px;padding:3px 0;">
      <span style="width:90px;color:var(--text-tertiary);flex-shrink:0;">${k}</span><span>${esc(v || '-')}</span></div>`;

    const modal = document.createElement('div');
    modal.id = 'admin-skill-view-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:1000;display:flex;align-items:center;justify-content:center;';
    modal.innerHTML = `
      <div style="background:white;border-radius:12px;width:720px;max-width:94vw;max-height:86vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
        <div style="display:flex;align-items:center;padding:20px 28px 14px;border-bottom:1px solid var(--border-default,#e5e5e5);">
          <h3 style="font-size:17px;font-weight:600;margin:0;flex:1;"><span class="material-symbols-outlined" style="font-size:17px;vertical-align:-3px;">extension</span> ${esc(item.name)}</h3>
          <button onclick="document.getElementById('admin-skill-view-modal').remove()" style="width:30px;height:30px;border:none;background:transparent;font-size:20px;color:var(--text-tertiary);cursor:pointer;">×</button>
        </div>
        <div style="flex:1;overflow-y:auto;padding:16px 28px 24px;">
          ${section('基本信息',
            metaRow('Skill Key', item.skill_key) + metaRow('类型', item.type) + metaRow('版本', item.version)
            + metaRow('状态', item.state) + metaRow('风险等级', item.risk_level) + metaRow('Owner', item.owner))}
          ${section('描述', `<div style="font-size:13px;white-space:pre-wrap;">${esc(item.description || '（无）')}</div>`)}
          ${section('指令体（SKILL.md）', `<div class="ai-answer-content" style="font-size:13px;">${instrHtml}</div>`)}
          ${item.config ? section('Manifest', `<pre style="white-space:pre-wrap;font-family:Consolas,Menlo,monospace;font-size:12px;background:var(--bg-hover,#f9fafb);border-radius:8px;padding:10px 12px;margin:0;">${esc(item.config)}</pre>`) : ''}
        </div>
        <div style="display:flex;gap:8px;padding:14px 28px;border-top:1px solid var(--border-default,#e5e5e5);">
          <button onclick="document.getElementById('admin-skill-view-modal').remove();AdminModule.showEditModal('skills','${item.id}')"
            style="flex:1;padding:10px;border:1px solid var(--border-default);border-radius:8px;background:white;font-size:14px;cursor:pointer;">去编辑</button>
          <button onclick="document.getElementById('admin-skill-view-modal').remove()"
            style="flex:1;padding:10px;border:none;border-radius:999px;background:var(--teal-700);color:white;font-size:14px;cursor:pointer;">关闭</button>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
  },

  /**
   * 查看 MCP Server 实时工具清单(不落库,实时连接拉取)
   */
  async viewMcpTools(id, name) {
    const old = document.getElementById('admin-mcp-tools-modal');
    if (old) old.remove();

    const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const modal = document.createElement('div');
    modal.id = 'admin-mcp-tools-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:1000;display:flex;align-items:center;justify-content:center;';
    modal.innerHTML = `
      <div style="background:white;border-radius:12px;width:720px;max-width:94vw;max-height:86vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
        <div style="display:flex;align-items:center;padding:18px 28px;border-bottom:1px solid var(--border-default,#e5e5e5);">
          <h3 style="font-size:17px;font-weight:600;margin:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(name)} — 工具清单</h3>
          <button onclick="document.getElementById('admin-mcp-tools-modal').remove()" style="width:30px;height:30px;border:none;background:transparent;font-size:20px;color:var(--text-tertiary);cursor:pointer;">×</button>
        </div>
        <div id="admin-mcp-tools-body" style="flex:1;overflow-y:auto;padding:20px 28px;">正在连接 MCP Server 拉取工具清单…</div>
      </div>`;
    document.body.appendChild(modal);
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

    const body = document.getElementById('admin-mcp-tools-body');
    try {
      const res = await fetch(`/api/admin/tools/${id}/tools`);
      const data = await res.json();
      if (res.ok && data.ok) {
        body.innerHTML = `<div style="font-size:13px;color:var(--text-secondary);margin-bottom:4px;">共发现 ${(data.tools || []).length} 个工具</div>`
          + this._renderMcpToolList(data.tools);
      } else {
        body.innerHTML = `<div style="padding:12px;border-radius:8px;background:#FEF2F2;color:#DC2626;font-size:13px;">✕ ${esc(data.detail || '连接失败')}</div>`;
      }
    } catch (e) {
      body.innerHTML = `<div style="padding:12px;border-radius:8px;background:#FEF2F2;color:#DC2626;font-size:13px;">✕ 网络错误:${esc(e.message)}</div>`;
    }
  },

  /**
   * 显示模态框
   */
  showModal(title, fields, itemId, tab) {
    // 移除已有模态框
    const old = document.getElementById('admin-modal');
    if (old) old.remove();

    // 单字段渲染(textarea 支持 rows 行数与 mono 等宽字体)
    const renderField = (f) => {
      const value = f.value || '';
      const required = f.required ? ' <span style="color:#DC2626;">*</span>' : '';

      if (f.type === 'textarea') {
        const mono = f.mono ? 'font-family:Consolas,Menlo,monospace;font-size:13px;' : 'font-family:inherit;';
        return `<div class="form-group"><label>${f.label}${required}</label><textarea name="${f.name}" rows="${f.rows || 3}" style="width:100%;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:8px 13px;font-size:14px;${mono}resize:vertical;">${value}</textarea></div>`;
      }
      if (f.type === 'select') {
        const opts = Object.entries(f.options).map(([v, l]) =>
          `<option value="${v}" ${value === v ? 'selected' : ''}>${l}</option>`).join('');
        return `<div class="form-group"><label>${f.label}${required}</label><select name="${f.name}" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;">${opts}</select></div>`;
      }
      // 异步下拉（选项来自接口）：先渲染占位，showModal 完成后由 _fillSelect 填充
      if (f.type === 'asyncselect') {
        return `<div class="form-group"><label>${f.label}${required}</label><select name="${f.name}" data-value="${value}" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;"><option value="">加载中…</option></select></div>`;
      }
      // 多选（checkbox 组）：渲染容器，showModal 完成后由 _fillMultiselect 异步填充选项
      if (f.type === 'multiselect') {
        return `<div class="form-group"><label>${f.label}${required}</label>
          <div id="ms-${f.name}" class="ms-box">
            <div class="ms-empty">加载中…</div>
          </div></div>`;
      }
      return `<div class="form-group"><label>${f.label}${required}</label><div class="input-margin"><input type="text" name="${f.name}" value="${value}" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;"></div></div>`;
    };

    // 组装表单:group 插分组标题;连续 half 字段收进两列网格
    let formHtml = '';
    let halfBuf = [];
    let lastGroup = null;
    const flushHalf = () => {
      if (!halfBuf.length) return;
      formHtml += `<div style="display:grid;grid-template-columns:1fr 1fr;gap:0 16px;">${halfBuf.join('')}</div>`;
      halfBuf = [];
    };
    fields.forEach(f => {
      if (f.group && f.group !== lastGroup) {
        flushHalf();
        lastGroup = f.group;
        formHtml += `<div style="font-size:13px;font-weight:600;color:var(--text-secondary,#666);margin:16px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--border-default,#e5e5e5);">${f.group}</div>`;
      }
      const html = renderField(f);
      if (f.half) halfBuf.push(html);
      else { flushHalf(); formHtml += html; }
    });
    flushHalf();

    const modal = document.createElement('div');
    modal.id = 'admin-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:1000;display:flex;align-items:center;justify-content:center;';
    // 三段式:标题头 / 滚动表单体 / 吸底按钮条(按钮移出 form,submitForm 按 id 取 form 不受影响)
    modal.innerHTML = `
      <div style="background:white;border-radius:12px;width:720px;max-width:94vw;max-height:86vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
        <h3 style="font-size:18px;font-weight:600;margin:0;padding:22px 32px 16px;border-bottom:1px solid var(--border-default,#e5e5e5);">${title}</h3>
        <form id="admin-form" style="flex:1;overflow-y:auto;padding:8px 32px 20px;">${formHtml}</form>
        <div style="display:flex;gap:8px;padding:14px 32px;border-top:1px solid var(--border-default,#e5e5e5);background:white;">
          <button type="button" onclick="document.getElementById('admin-modal').remove()"
            style="flex:1;padding:10px;border:1px solid var(--border-default);border-radius:8px;background:white;font-size:14px;cursor:pointer;">取消</button>
          ${tab === 'skills' ? `<button type="button" onclick="AdminModule.validateSkillForm()"
            style="flex:1;padding:10px;border:1px solid #2563EB;border-radius:8px;background:white;color:#2563EB;font-size:14px;cursor:pointer;">校验</button>` : ''}
          <button type="button" onclick="AdminModule.submitForm('${tab}', '${itemId || ''}')"
            style="flex:1;padding:10px;border:none;border-radius:999px;background:var(--teal-700);color:white;font-size:14px;cursor:pointer;">保存</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);

    // 点击遮罩关闭
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

    // 异步填充 multiselect / asyncselect 选项
    fields.forEach(f => {
      if (f.type === 'multiselect') this._fillMultiselect(f);
      if (f.type === 'asyncselect') this._fillSelect(f);
    });
  },

  /**
   * 填充 asyncselect 下拉选项
   * 当前值可能是 ID 也可能是显示名（GET /agents 返回显示名），两种都尝试匹配
   */
  async _fillSelect(f) {
    const sel = document.querySelector(`#admin-form select[name="${f.name}"]`);
    if (!sel) return;
    const current = sel.dataset.value || '';
    try {
      const items = await fetch(f.source).then(r => r.json());
      const opts = (Array.isArray(items) ? items : []).map(it => {
        const v = it[f.valueKey] || it.name;
        const label = it[f.labelKey] || v;
        const hit = current && (current === v || current === label);
        return `<option value="${v}" ${hit ? 'selected' : ''}>${label}</option>`;
      }).join('');
      sel.innerHTML = `<option value="">${f.placeholder || '- 请选择 -'}</option>` + opts;
      // 当前值不在选项里（如已删除的部门）：保留原值兜底，避免误清空
      if (current && !sel.value) {
        sel.insertAdjacentHTML('beforeend', `<option value="${current}" selected>${current}（待重新选择）</option>`);
      }
    } catch (e) {
      sel.innerHTML = `<option value="${current}">${current || '选项加载失败'}</option>`;
    }
  },

  /**
   * 填充 multiselect 字段的 checkbox 选项
   * f.source 拉取列表，valueKey 作值、labelKey 作显示名，f.value 数组中的项预勾选
   */
  async _fillMultiselect(f) {
    const box = document.getElementById(`ms-${f.name}`);
    if (!box) return;
    try {
      const items = await fetch(f.source).then(r => r.json());
      const selected = Array.isArray(f.value) ? f.value : [];
      if (!Array.isArray(items) || items.length === 0) {
        box.innerHTML = '<div class="ms-empty">暂无可选项，请先在对应中心创建</div>';
        return;
      }
      box.innerHTML = items.map(it => {
        const v = it[f.valueKey] || it.name;
        const checked = selected.includes(v) ? 'checked' : '';
        return `<label class="ms-item">
          <input type="checkbox" class="ms-check" name="${f.name}" value="${v}" ${checked}>
          <span class="ms-name">${it[f.labelKey] || v}</span>
          <span class="ms-id" title="${v}">${v}</span>
        </label>`;
      }).join('');
    } catch (e) {
      box.innerHTML = '<div class="ms-empty" style="color:#DC2626;">选项加载失败，请重试</div>';
    }
  },

  /**
   * 提交表单
   */
  async submitForm(tab, itemId) {
    // 修正 tab 名到 API 路径（dept -> departments, domain -> domains）
    const apiTab = tab === 'dept' ? 'departments' : (tab === 'domain' ? 'domains' : tab);

    const form = document.getElementById('admin-form');
    const formData = new FormData(form);
    const body = {};
    // checkbox（multiselect）同名多值，需 getAll 收集为数组（空数组=清空绑定），避免被 forEach 覆盖成单值
    const multiNames = new Set();
    form.querySelectorAll('input[type="checkbox"][name]').forEach(c => multiNames.add(c.name));
    formData.forEach((v, k) => { if (!multiNames.has(k)) body[k] = v; });
    multiNames.forEach(k => { body[k] = formData.getAll(k); });

    // 岗位包：工具白名单收进 config.tools，其余 config 键（权限/承诺/资源等）原样保留
    if (tab === 'role-packs') {
      const existing = itemId ? ((this.cache[tab] || []).find(i => i.id === itemId) || {}) : {};
      body.config = { ...(existing.config || {}), tools: body.tools || [] };
      delete body.tools;
    }

    const method = itemId ? 'PUT' : 'POST';
    const url = itemId
      ? `/api/admin/${apiTab}/${itemId}`
      : `/api/admin/${apiTab}`;

    try {
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (res.ok) {
        document.getElementById('admin-modal').remove();
        // 重新加载当前 Tab
        const reloadTab = ['departments', 'domains'].includes(tab) ? 'org' : tab;
        this.loadTab(reloadTab);
      } else {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        Toast.error(`保存失败: ${err.detail || res.statusText}`);
      }
    } catch (e) {
      Toast.error(`网络错误: ${e.message}`);
    }
  },

  /**
   * 删除项
   */
  async deleteItem(tab, id, name) {
    const confirmed = await Toast.confirm(`确认删除「${name}」？此操作不可撤销。`, '删除');
    if (!confirmed) return;

    try {
      // 组织管理的 tab 键是单数 dept/domain，API 路径是复数 departments/domains（与 submitForm 映射保持一致）
      const apiTab = tab === 'dept' ? 'departments' : (tab === 'domain' ? 'domains' : tab);
      const res = await fetch(`/api/admin/${apiTab}/${id}`, { method: 'DELETE' });
      if (res.ok) {
        const reloadTab = ['departments', 'domains', 'dept', 'domain'].includes(tab) ? 'org' : tab;
        this.loadTab(reloadTab);
      } else {
        Toast.error('删除失败');
      }
    } catch (e) {
      Toast.error(`网络错误: ${e.message}`);
    }
  },

  // ════════════════════════════════════════════
  //  Skill：校验 / AI 生成 / 导入（Harness Engineering）
  // ════════════════════════════════════════════

  /**
   * 表单内「校验」按钮：调用确定性校验端点，结果渲染在表单顶部
   */
  async validateSkillForm() {
    const form = document.getElementById('admin-form');
    if (!form) return;
    const formData = new FormData(form);
    const body = {};
    formData.forEach((v, k) => body[k] = v);
    try {
      const res = await fetch('/api/admin/skills/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const report = await res.json();
      this._renderValidationBar(report);
    } catch (e) {
      Toast.error(`校验请求失败: ${e.message}`);
    }
  },

  /**
   * 在表单顶部渲染校验结果条（errors 红 / warnings 黄）
   */
  _renderValidationBar(report) {
    const old = document.getElementById('validation-bar');
    if (old) old.remove();
    const form = document.getElementById('admin-form');
    if (!form) return;
    const ok = report.ok;
    const lines = [
      ...(report.errors || []).map(e => `✕ ${e}`),
      ...(report.warnings || []).map(w => `⚠ ${w}`),
    ];
    const bar = document.createElement('div');
    bar.id = 'validation-bar';
    bar.style.cssText = `margin-bottom:16px;padding:12px;border-radius:8px;font-size:13px;background:${ok ? '#ECFDF5' : '#FEF2F2'};color:${ok ? '#059669' : '#DC2626'};`;
    bar.innerHTML = `<div style="font-weight:600;${lines.length ? 'margin-bottom:6px;' : ''}">${ok ? '✓ 校验通过' : '✕ 校验未通过'}</div>`
      + lines.map(l => `<div style="margin-top:2px;">${l}</div>`).join('');
    form.prepend(bar);
  },

  /**
   * AI 生成 Skill 弹窗
   */
  showSkillAIGenModal() {
    const old = document.getElementById('skill-aigen-modal');
    if (old) old.remove();
    const modal = document.createElement('div');
    modal.id = 'skill-aigen-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:1000;display:flex;align-items:center;justify-content:center;';
    modal.innerHTML = `
      <div style="background:white;border-radius:12px;padding:32px;width:560px;max-height:85vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
        <h3 style="font-size:18px;font-weight:600;margin-bottom:8px;"><span class="material-symbols-outlined" style="font-size:20px;vertical-align:-4px;">auto_awesome</span> AI 生成能力（Skill）</h3>
        <p style="font-size:12px;color:var(--text-secondary);margin-bottom:20px;">描述能力需求，AI 生成草案并经过确定性校验（最多 3 轮自修复）。采用后可在表单中继续编辑再保存。</p>
        <div class="form-group">
          <label>能力名称 <span style="color:#DC2626;">*</span></label>
          <input type="text" id="aigen-skill-name" placeholder="如：会议纪要整理" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;">
        </div>
        <div class="form-group" style="margin-top:12px;">
          <label>类型</label>
          <select id="aigen-skill-type" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;">
            <option value="generation">生成</option>
            <option value="search">检索</option>
            <option value="analysis">分析</option>
            <option value="api">API</option>
            <option value="workflow">工作流</option>
          </select>
        </div>
        <div class="form-group" style="margin-top:12px;">
          <label>需求提示（可选）</label>
          <textarea id="aigen-skill-hint" rows="3" placeholder="补充输入输出、执行步骤、约束等要求…" style="width:100%;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:8px 13px;font-size:14px;resize:vertical;"></textarea>
        </div>
        <div id="aigen-result" style="margin-top:16px;"></div>
        <div style="display:flex;gap:8px;margin-top:24px;">
          <button type="button" onclick="document.getElementById('skill-aigen-modal').remove()"
            style="flex:1;padding:10px;border:1px solid var(--border-default);border-radius:8px;background:white;font-size:14px;cursor:pointer;">取消</button>
          <button type="button" id="aigen-run-btn" onclick="AdminModule.runSkillAIGen()"
            style="flex:1;padding:10px;border:none;border-radius:999px;background:var(--teal-700);color:white;font-size:14px;cursor:pointer;">生成</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
  },

  /**
   * 调用 AI 生成端点（后端含 3 轮校验自修复），渲染预览与校验报告
   */
  async runSkillAIGen() {
    const name = document.getElementById('aigen-skill-name').value.trim();
    if (!name) { Toast.error('请填写能力名称'); return; }
    const type = document.getElementById('aigen-skill-type').value;
    const hint = document.getElementById('aigen-skill-hint').value.trim();
    const btn = document.getElementById('aigen-run-btn');
    const box = document.getElementById('aigen-result');
    btn.disabled = true;
    btn.textContent = '生成中（约 10s）…';
    box.innerHTML = '<div style="font-size:13px;color:var(--text-tertiary);">AI 正在生成并自检，请稍候…</div>';
    try {
      const res = await fetch('/api/admin/skills/ai-generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, type, hint }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
      this._lastAIGenPreview = data.preview;
      box.innerHTML = this._renderAIGenPreview(data);
    } catch (e) {
      box.innerHTML = `<div style="padding:12px;border-radius:8px;background:#FEF2F2;color:#DC2626;font-size:13px;">✕ 生成失败：${e.message}</div>`;
    } finally {
      btn.disabled = false;
      btn.textContent = '生成';
    }
  },

  /**
   * 渲染 AI 生成预览 + 校验报告 + 采用按钮
   */
  _renderAIGenPreview(data) {
    const p = data.preview || {};
    const v = data.validation || {};
    const lines = [
      ...(v.errors || []).map(e => `✕ ${e}`),
      ...(v.warnings || []).map(w => `⚠ ${w}`),
    ];
    return `
      <div style="padding:12px;border-radius:8px;background:${v.ok ? '#ECFDF5' : '#FEF3C7'};font-size:13px;margin-bottom:12px;">
        <div style="font-weight:600;color:${v.ok ? '#059669' : '#92400E'};">${v.ok ? '✓ 校验通过' : '⚠ 3 轮自修复后仍未完全通过，采用后可手工修正'}（${data.attempts || 1} 轮）</div>
        ${lines.map(l => `<div style="margin-top:2px;color:#92400E;">${l}</div>`).join('')}
      </div>
      <div style="padding:12px;background:var(--bg-page);border-radius:8px;font-size:13px;">
        <div><b>${p.name || ''}</b> <span style="font-family:monospace;color:var(--text-tertiary);">${p.skill_key || ''}</span></div>
        <div style="color:var(--text-secondary);margin-top:4px;">${p.description || ''}</div>
        <div style="margin-top:6px;color:var(--text-tertiary);">类型 ${p.type || '-'} ｜ 版本 ${p.version || '-'} ｜ 风险 ${p.risk_level || '-'}</div>
        <details style="margin-top:8px;">
          <summary style="cursor:pointer;color:#2563EB;">查看指令体（${(p.instructions || '').length} 字）</summary>
          <pre style="white-space:pre-wrap;font-size:12px;background:white;padding:8px;border-radius:6px;margin-top:6px;max-height:200px;overflow-y:auto;">${p.instructions || ''}</pre>
        </details>
      </div>
      <button type="button" onclick="AdminModule.adoptAIGenDraft()"
        style="width:100%;margin-top:12px;padding:10px;border:none;border-radius:999px;background:var(--teal-700);color:white;font-size:14px;cursor:pointer;">采用此草案（进入表单继续编辑）</button>
    `;
  },

  /**
   * 采用 AI 草案：写入 _draft 预填新建表单（showCreateModal 消费后立即清空）
   */
  adoptAIGenDraft() {
    if (!this._lastAIGenPreview) return;
    this._draft = { ...this._lastAIGenPreview };
    const modal = document.getElementById('skill-aigen-modal');
    if (modal) modal.remove();
    this.showCreateModal('skills');
    this._draft = null;
  },

  /**
   * 导入 Skill 弹窗（本地 SKILL.md / JSON / YAML Manifest）
   */
  showSkillImportModal() {
    const old = document.getElementById('skill-import-modal');
    if (old) old.remove();
    const modal = document.createElement('div');
    modal.id = 'skill-import-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:1000;display:flex;align-items:center;justify-content:center;';
    modal.innerHTML = `
      <div style="background:white;border-radius:12px;padding:32px;width:560px;max-height:85vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
        <h3 style="font-size:18px;font-weight:600;margin-bottom:8px;"><span class="material-symbols-outlined" style="font-size:20px;vertical-align:-4px;">download</span> 导入能力（Skill）</h3>
        <p style="font-size:12px;color:var(--text-secondary);margin-bottom:20px;">支持 SKILL.md（--- frontmatter --- 正文）或 JSON / YAML Manifest。导入前会经过确定性校验，合格后以 DRAFT 状态落库。</p>
        <div class="form-group">
          <label>选择文件（.md / .yaml / .json）</label>
          <input type="file" accept=".md,.yaml,.yml,.json,.txt" onchange="AdminModule._readImportFile(this)"
            style="width:100%;font-size:13px;padding:8px;background:var(--bg-input);border-radius:8px;">
        </div>
        <div class="form-group" style="margin-top:12px;">
          <label>内容（可手工粘贴/修改）</label>
          <textarea id="import-skill-content" rows="12" placeholder="---&#10;name: 能力名称&#10;skill_key: my-skill&#10;type: workflow&#10;version: 1.0.0&#10;risk_level: LOW&#10;---&#10;&#10;# 指令正文…" style="width:100%;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:8px 13px;font-size:12px;font-family:monospace;resize:vertical;"></textarea>
        </div>
        <div id="import-result" style="margin-top:12px;"></div>
        <div style="display:flex;gap:8px;margin-top:24px;">
          <button type="button" onclick="document.getElementById('skill-import-modal').remove()"
            style="flex:1;padding:10px;border:1px solid var(--border-default);border-radius:8px;background:white;font-size:14px;cursor:pointer;">取消</button>
          <button type="button" id="import-run-btn" onclick="AdminModule.runSkillImport()"
            style="flex:1;padding:10px;border:none;border-radius:999px;background:var(--teal-700);color:white;font-size:14px;cursor:pointer;">导入</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
  },

  /**
   * 读取本地文件内容到导入 textarea
   */
  _readImportFile(input) {
    const file = input.files && input.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const ta = document.getElementById('import-skill-content');
      if (ta) ta.value = reader.result;
    };
    reader.readAsText(file);
  },

  /**
   * 执行导入：422 时展示校验明细，409 提示重复
   */
  async runSkillImport() {
    const content = document.getElementById('import-skill-content').value;
    if (!content.trim()) { Toast.error('导入内容为空'); return; }
    const btn = document.getElementById('import-run-btn');
    const box = document.getElementById('import-result');
    btn.disabled = true;
    btn.textContent = '导入中…';
    box.innerHTML = '';
    try {
      const res = await fetch('/api/admin/skills/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      });
      const data = await res.json();
      if (res.ok) {
        document.getElementById('skill-import-modal').remove();
        Toast.success('导入成功（DRAFT 状态，请在能力中心完善后发布）');
        this.loadTab('skills');
      } else {
        const detail = data.detail;
        if (detail && detail.validation) {
          // 422：确定性校验未通过，展示错误明细
          this._renderImportErrors(detail.validation);
        } else {
          const msg = typeof detail === 'string' ? detail : JSON.stringify(detail);
          box.innerHTML = `<div style="padding:12px;border-radius:8px;background:#FEF2F2;color:#DC2626;font-size:13px;">✕ ${msg}</div>`;
        }
      }
    } catch (e) {
      box.innerHTML = `<div style="padding:12px;border-radius:8px;background:#FEF2F2;color:#DC2626;font-size:13px;">✕ 网络错误：${e.message}</div>`;
    } finally {
      btn.disabled = false;
      btn.textContent = '导入';
    }
  },

  /**
   * 在导入弹窗中渲染校验错误明细
   */
  _renderImportErrors(validation) {
    const box = document.getElementById('import-result');
    if (!box) return;
    const lines = [
      ...(validation.errors || []).map(e => `✕ ${e}`),
      ...(validation.warnings || []).map(w => `⚠ ${w}`),
    ];
    box.innerHTML = `<div style="padding:12px;border-radius:8px;background:#FEF2F2;font-size:13px;">
      <div style="font-weight:600;color:#DC2626;margin-bottom:6px;">✕ 校验未通过，请修正后重试</div>
      ${lines.map(l => `<div style="margin-top:2px;color:#DC2626;">${l}</div>`).join('')}
    </div>`;
  },

  // ════════════════════════════════════════════
  //  MCP Server 接入（粘贴 mcpServers JSON → 测试连接 → 落库）
  //  Tool 表一行 = 一个 MCP Server：endpoint=url，config={"headers":{...}}
  // ════════════════════════════════════════════

  /**
   * MCP Server 接入弹窗
   */
  showMcpConnectModal() {
    const old = document.getElementById('mcp-connect-modal');
    if (old) old.remove();
    const modal = document.createElement('div');
    modal.id = 'mcp-connect-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:1000;display:flex;align-items:center;justify-content:center;';
    modal.innerHTML = `
      <div style="background:white;border-radius:12px;padding:32px;width:600px;max-height:85vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
        <h3 style="font-size:18px;font-weight:600;margin-bottom:8px;"><span class="material-symbols-outlined" style="font-size:20px;vertical-align:-4px;">cable</span> 连接 MCP Server</h3>
        <p style="font-size:12px;color:var(--text-secondary);margin-bottom:20px;">粘贴 mcpServers 配置 JSON，先测试连接预览发现的工具，确认后落库。员工（Agent）绑定后即可在对话中调用远端工具。</p>
        <div class="form-group">
          <label>MCP 配置（mcpServers JSON）</label>
          <textarea id="mcp-config-json" rows="8" placeholder='{"mcpServers":{"my-mcp-server":{"type":"mcp","url":"http://host:port/sse","headers":{"appKey":"..."}}}}' style="width:100%;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:8px 13px;font-size:12px;font-family:monospace;resize:vertical;"></textarea>
        </div>
        <div id="mcp-test-result" style="margin-top:12px;"></div>
        <div style="display:flex;gap:8px;margin-top:24px;">
          <button type="button" onclick="document.getElementById('mcp-connect-modal').remove()"
            style="flex:1;padding:10px;border:1px solid var(--border-default);border-radius:8px;background:white;font-size:14px;cursor:pointer;">取消</button>
          <button type="button" id="mcp-test-btn" onclick="AdminModule.runMcpTest()"
            style="flex:1;padding:10px;border:none;border-radius:999px;background:var(--teal-700);color:white;font-size:14px;cursor:pointer;">测试连接</button>
          <button type="button" id="mcp-adopt-btn" onclick="AdminModule.runMcpAdopt()" disabled
            style="flex:1;padding:10px;border:none;border-radius:999px;background:var(--teal-700);color:white;font-size:14px;cursor:pointer;opacity:0.5;">确认接入</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
    this._mcpTested = null;  // 测试成功的 server 清单（供确认接入使用）
  },

  /**
   * 解析弹窗中的 mcpServers JSON，返回 {serverName: {url, headers}} 映射
   */
  _parseMcpConfig() {
    const raw = document.getElementById('mcp-config-json').value;
    const cfg = JSON.parse(raw);
    const servers = cfg.mcpServers || cfg;
    const out = {};
    for (const [name, s] of Object.entries(servers)) {
      if (s && s.url) out[name] = { url: s.url, headers: s.headers || {} };
    }
    return out;
  },

  /**
   * 测试连接：逐个 server 调 test-connection，渲染发现的工具清单
   */
  async runMcpTest() {
    const box = document.getElementById('mcp-test-result');
    const btn = document.getElementById('mcp-test-btn');
    let servers;
    try {
      servers = this._parseMcpConfig();
    } catch (e) {
      box.innerHTML = `<div style="padding:12px;border-radius:8px;background:#FEF2F2;color:#DC2626;font-size:13px;">✕ JSON 解析失败：${e.message}</div>`;
      return;
    }
    if (!Object.keys(servers).length) {
      box.innerHTML = `<div style="padding:12px;border-radius:8px;background:#FEF2F2;color:#DC2626;font-size:13px;">✕ 未找到有效的 server 配置（需要 url 字段）</div>`;
      return;
    }
    btn.disabled = true;
    btn.textContent = '连接中…';
    box.innerHTML = '';
    const tested = [];
    for (const [name, s] of Object.entries(servers)) {
      try {
        const res = await fetch('/api/admin/tools/test-connection', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ endpoint: s.url, config: JSON.stringify({ headers: s.headers }) }),
        });
        const data = await res.json();
        if (res.ok && data.ok) {
          tested.push({ name, ...s });
          // 工具清单渲染与「查看工具」弹窗共用 _renderMcpToolList
          box.innerHTML += `<div style="padding:12px;border-radius:8px;background:#ECFDF5;margin-bottom:8px;">
            <div style="font-weight:600;color:#059669;font-size:13px;">✓ ${name} — 发现 ${(data.tools || []).length} 个工具</div>
            <div style="margin-top:6px;max-height:200px;overflow-y:auto;">${this._renderMcpToolList(data.tools)}</div>
          </div>`;
        } else {
          box.innerHTML += `<div style="padding:12px;border-radius:8px;background:#FEF2F2;color:#DC2626;font-size:13px;margin-bottom:8px;">✕ ${name} — ${data.detail || '连接失败'}</div>`;
        }
      } catch (e) {
        box.innerHTML += `<div style="padding:12px;border-radius:8px;background:#FEF2F2;color:#DC2626;font-size:13px;margin-bottom:8px;">✕ ${name} — 网络错误：${e.message}</div>`;
      }
    }
    this._mcpTested = tested;
    const adoptBtn = document.getElementById('mcp-adopt-btn');
    adoptBtn.disabled = tested.length === 0;
    adoptBtn.style.opacity = tested.length ? '1' : '0.5';
    btn.disabled = false;
    btn.textContent = '测试连接';
  },

  /**
   * 确认接入：对测试成功的 server 逐个落库（Tool 表一行 = 一个 MCP Server）
   */
  async runMcpAdopt() {
    const tested = this._mcpTested || [];
    if (!tested.length) { Toast.error('请先测试连接'); return; }
    const btn = document.getElementById('mcp-adopt-btn');
    btn.disabled = true;
    btn.textContent = '接入中…';
    let okCount = 0, failMsgs = [];
    for (const s of tested) {
      const slug = s.name.replace(/[^a-zA-Z0-9_-]/g, '_');
      try {
        const res = await fetch('/api/admin/tools', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: s.name,
            tool_key: slug,
            type: 'mcp',
            mode: 'READ_ONLY',
            endpoint: s.url,
            risk_level: 'LOW',
            timeout_ms: 15000,
            description: `MCP Server：${s.url}`,
            config: JSON.stringify({ headers: s.headers, transport: 'sse' }),
          }),
        });
        if (res.ok) okCount++;
        else failMsgs.push(`${s.name}: ${(await res.json()).detail || '创建失败'}`);
      } catch (e) {
        failMsgs.push(`${s.name}: ${e.message}`);
      }
    }
    document.getElementById('mcp-connect-modal').remove();
    if (okCount) Toast.success(`已接入 ${okCount} 个 MCP Server，到员工/岗位包中绑定即可使用`);
    if (failMsgs.length) Toast.error(failMsgs.join('；'));
    this.loadTab('tools');
  },

  // ════════════════════════════════════════════
  //  8 步 Agent 创建向导（对齐产品 PRD）
  //  基本信息 -> 归属 -> 组装岗位包 -> 权限 -> 输出承诺 -> 预检 -> 试运行 -> 提交上线
  // ════════════════════════════════════════════
  wizardStep: 0,
  wizardData: {},
  WIZARD_STEPS: [
    { title: '基本信息',   desc: '配置 Agent 的姓名、头像、职位与职责描述',     icon: 'person' },
    { title: '归属',       desc: '选择部门与领域，决定对接人与专业范围',         icon: 'corporate_fare' },
    { title: '组装岗位包', desc: '选择资源、能力、工具，打包为岗位包',           icon: 'inventory_2' },
    { title: '权限',       desc: '配置工具白名单与调用预算',                     icon: 'lock' },
    { title: '输出承诺',   desc: '设定响应时效、质量指标与升级策略',             icon: 'monitoring' },
    { title: '预检',       desc: '校验配置完整性，识别阻断项与建议项',           icon: 'check_circle' },
    { title: '试运行',     desc: '选择发布模式，设定试运行监控指标',             icon: 'science' },
    { title: '提交上线',   desc: '确认配置并提交，创建岗位包与 Agent',           icon: 'rocket_launch' },
  ],

  /**
   * 启动向导
   */
  startWizard(step) {
    this.wizardStep = step ? step - 1 : 0;
    this.wizardData = {};
    this.renderWizard();
    // 触发首步的动态数据加载
    this._loadStepDynamicData(this.wizardStep);
  },

  /**
   * 渲染向导弹窗
   */
  renderWizard() {
    const old = document.getElementById('wizard-modal');
    if (old) old.remove();

    const step = this.wizardStep;
    const stepInfo = this.WIZARD_STEPS[step];
    const total = this.WIZARD_STEPS.length;
    const isLast = step === total - 1;
    const isFirst = step === 0;

    // 步骤指示器
    const indicators = this.WIZARD_STEPS.map((s, i) => {
      const active = i === step;
      const done = i < step;
      const bg = active ? '#171717' : (done ? '#059669' : '#F0F0F0');
      const color = active || done ? 'white' : '#737373';
      return `<div style="display:flex;align-items:center;gap:6px;">
        <div style="width:24px;height:24px;border-radius:50%;background:${bg};color:${color};display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;">${done ? '✓' : i+1}</div>
        <span style="font-size:11px;color:${active ? '#171717' : '#A1A1A1'};white-space:nowrap;">${s.title}</span>
        ${i < total - 1 ? '<span style="color:#D4D4D4;margin:0 4px;">→</span>' : ''}
      </div>`;
    }).join('');

    // 步骤内容
    const content = this.getWizardStepContent(step);

    const modal = document.createElement('div');
    modal.id = 'wizard-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:2000;display:flex;align-items:center;justify-content:center;';
    modal.innerHTML = `
      <div style="background:white;border-radius:16px;padding:32px;width:640px;max-height:85vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
        <!-- 标题 -->
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;">
          <div>
            <h3 style="font-size:20px;font-weight:600;"><span class="material-symbols-outlined" style="font-size:22px;vertical-align:-4px;">${stepInfo.icon}</span> ${stepInfo.title}</h3>
            <p style="font-size:13px;color:var(--text-secondary);margin-top:4px;">${stepInfo.desc}（步骤 ${step + 1}/${total}）</p>
          </div>
          <button onclick="document.getElementById('wizard-modal').remove()" style="width:32px;height:32px;border:none;background:transparent;font-size:20px;color:var(--text-tertiary);cursor:pointer;">×</button>
        </div>

        <!-- 步骤进度条 -->
        <div style="display:flex;align-items:center;flex-wrap:wrap;gap:2px;margin-bottom:24px;padding:12px;background:var(--bg-page);border-radius:8px;">
          ${indicators}
        </div>

        <!-- 内容区 -->
        <div id="wizard-content" style="min-height:200px;margin-bottom:24px;">
          ${content}
        </div>

        <!-- 导航按钮 -->
        <div style="display:flex;gap:8px;justify-content:space-between;">
          <button onclick="AdminModule.wizardPrev()" style="padding:10px 20px;border:1px solid var(--border-default);border-radius:999px;background:white;font-size:14px;cursor:pointer;${isFirst ? 'visibility:hidden;' : ''}">上一步</button>
          <span style="font-size:12px;color:var(--text-tertiary);align-self:center;">${step + 1} / ${total}</span>
          ${isLast
            ? '<button onclick="AdminModule.wizardFinish()" style="padding:10px 20px;border:none;border-radius:999px;background:var(--teal-700);color:white;font-size:14px;cursor:pointer;">提交上线</button>'
            : `<button onclick="AdminModule.wizardNext()" style="padding:10px 20px;border:none;border-radius:999px;background:var(--teal-700);color:white;font-size:14px;cursor:pointer;">下一步</button>`
          }
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
  },

  wizardNext() {
    // 收集当前步骤的表单数据
    this._collectStepData(this.wizardStep);
    if (this.wizardStep < this.WIZARD_STEPS.length - 1) {
      this.wizardStep++;
      this.renderWizard();
      // 异步加载下一步需要的动态数据
      this._loadStepDynamicData(this.wizardStep);
    }
  },

  /**
   * 跳转到指定向导步骤并重新加载该步动态数据
   * （renderWizard 只渲染静态骨架，部门/领域下拉与资源/Skill/Tool 列表需异步加载）
   */
  _wizardJump(step) {
    this.wizardStep = step;
    this.renderWizard();
    this._loadStepDynamicData(step);
  },

  wizardPrev() {
    if (this.wizardStep > 0) {
      this._wizardJump(this.wizardStep - 1);
    }
  },

  /**
   * 收集每一步的表单数据到 wizardData
   */
  _collectStepData(step) {
    const get = (id) => {
      const el = document.getElementById(id);
      return el ? el.value : '';
    };
    const getChecked = (name) => {
      return Array.from(document.querySelectorAll(`input[name="${name}"]:checked`)).map(c => c.value);
    };

    switch (step) {
      case 0: // 基本信息
        this.wizardData.name = get('wiz-agent-name');
        this.wizardData.emoji = get('wiz-agent-emoji') || '🧑‍💻';
        this.wizardData.title = get('wiz-agent-title');
        this.wizardData.description = get('wiz-agent-desc');
        this.wizardData.agents_md = get('wiz-agent-agents-md');
        break;
      case 1: // 归属
        this.wizardData.department_id = get('wiz-dept');
        this.wizardData.domain_id = get('wiz-domain');
        this.wizardData.owner = get('wiz-owner') || 'admin';
        break;
      case 2: // 组装岗位包（资源 + Skill + Tool + 岗位包名）
        this.wizardData.resources = getChecked('wiz-resource');
        this.wizardData.skills = getChecked('wiz-skill');
        this.wizardData.tools = getChecked('wiz-tool');
        this.wizardData.role_pack_name = get('wiz-pack-name');
        this.wizardData.version = get('wiz-pack-version') || '1.0.0';
        break;
      case 3: // 权限
        this.wizardData.read_only = get('wiz-read-only') === 'true';
        this.wizardData.budget_steps = parseInt(get('wiz-budget-steps')) || 8;
        this.wizardData.budget_calls = parseInt(get('wiz-budget-calls')) || 6;
        this.wizardData.budget_timeout = parseInt(get('wiz-budget-timeout')) || 60;
        this.wizardData.budget_token = parseInt(get('wiz-budget-token')) || 48000;
        this.wizardData.acl_mode = get('wiz-acl-mode') || 'whitelist';
        break;
      case 4: // 输出承诺
        this.wizardData.sla_response = parseInt(get('wiz-sla-response')) || 30;
        this.wizardData.quality_target = parseInt(get('wiz-quality-target')) || 85;
        this.wizardData.escalation = get('wiz-escalation') || 'owner';
        break;
      case 5: // 预检（无表单，仅展示）
        break;
      case 6: // 试运行
        this.wizardData.publish_mode = get('wiz-publish-mode') || 'trial';
        this.wizardData.trial_days = parseInt(get('wiz-trial-days')) || 7;
        break;
      case 7: // 提交上线（无表单，仅确认）
        break;
    }
  },

  /**
   * 异步加载步骤需要的动态数据
   * - step 1: 加载部门/领域下拉
   * - step 2: 加载资源、Skill、Tool 列表（多选）
   */
  async _loadStepDynamicData(step) {
    if (step === 1) {
      // 步骤 1：归属 - 加载部门/领域
      try {
        const [depts, domains] = await Promise.all([
          fetch('/api/admin/departments').then(r => r.json()).catch(() => []),
          fetch('/api/admin/domains').then(r => r.json()).catch(() => []),
        ]);
        const deptSel = document.getElementById('wiz-dept');
        const domainSel = document.getElementById('wiz-domain');
        if (deptSel && Array.isArray(depts)) {
          deptSel.innerHTML = '<option value="">- 选择部门 -</option>' +
            depts.map(d => `<option value="${d.id}" ${this.wizardData.department_id === d.id ? 'selected' : ''}>${d.name || d.id}</option>`).join('');
        }
        if (domainSel && Array.isArray(domains)) {
          domainSel.innerHTML = '<option value="">- 选择领域 -</option>' +
            domains.map(d => `<option value="${d.id || d.name}" ${this.wizardData.domain_id === (d.id || d.name) ? 'selected' : ''}>${d.name || d.id}</option>`).join('');
        }
      } catch (e) {
        console.warn('[wizard] 加载部门/领域失败', e);
      }
    }
    if (step === 2) {
      // 步骤 2：组装岗位包 - 并行加载资源、Skill、Tool
      try {
        const [resources, skills, tools] = await Promise.all([
          fetch('/api/admin/resources').then(r => r.json()).catch(() => []),
          fetch('/api/admin/skills').then(r => r.json()).catch(() => []),
          fetch('/api/admin/tools').then(r => r.json()).catch(() => []),
        ]);

        const selectedResources = this.wizardData.resources || [];
        const selectedSkills = this.wizardData.skills || [];
        const selectedTools = this.wizardData.tools || [];

        const resList = document.getElementById('wiz-resource-list');
        if (resList) {
          if (Array.isArray(resources) && resources.length > 0) {
            resList.innerHTML = resources.map(r => {
              const checked = selectedResources.includes(r.name || r.id) ? 'checked' : '';
              return `<label style="display:flex;align-items:center;gap:8px;padding:10px;background:var(--bg-input);border-radius:8px;cursor:pointer;">
                <input type="checkbox" name="wiz-resource" value="${r.name || r.id}" ${checked}> ${msIcon(r.icon)}
                <span style="font-size:14px;">${r.name || r.id}</span>
                <span style="font-size:11px;color:var(--text-tertiary);margin-left:auto;">${r.type || ''}</span>
              </label>`;
            }).join('');
          } else {
            resList.innerHTML = '<div style="padding:12px;text-align:center;color:var(--text-tertiary);font-size:13px;">暂无资源，请先在"资源中心"创建</div>';
          }
        }

        const skillList = document.getElementById('wiz-skill-list');
        if (skillList) {
          if (Array.isArray(skills) && skills.length > 0) {
            skillList.innerHTML = skills.map(s => {
              // checkbox 值用 skill_key（Agent 直绑的标识）；checked 兼容历史"名称"数据
              const v = s.skill_key || s.name || s.id;
              const checked = (selectedSkills.includes(v) || selectedSkills.includes(s.name)) ? 'checked' : '';
              return `<label style="display:flex;align-items:center;gap:8px;padding:10px;background:var(--bg-input);border-radius:8px;cursor:pointer;">
                <input type="checkbox" name="wiz-skill" value="${v}" ${checked}> <span class="material-symbols-outlined" style="font-size:15px;vertical-align:-2px;">extension</span>
                <span style="font-size:14px;">${s.name || s.id}</span>
                <span style="font-size:11px;color:var(--text-tertiary);margin-left:auto;">${s.type || ''}</span>
              </label>`;
            }).join('');
          } else {
            skillList.innerHTML = '<div style="padding:12px;text-align:center;color:var(--text-tertiary);font-size:13px;">暂无能力，请先在"能力中心"创建</div>';
          }
        }

        const toolList = document.getElementById('wiz-tool-list');
        if (toolList) {
          if (Array.isArray(tools) && tools.length > 0) {
            toolList.innerHTML = tools.map(t => {
              const checked = selectedTools.includes(t.name || t.id) ? 'checked' : '';
              return `<label style="display:flex;align-items:center;gap:10px;padding:10px 14px;background:var(--bg-input);border-radius:8px;cursor:pointer;">
                <input type="checkbox" name="wiz-tool" value="${t.name || t.id}" ${checked}>
                <span style="font-size:14px;font-weight:500;font-family:monospace;">${t.name || t.id}</span>
                <span style="font-size:12px;color:var(--text-tertiary);">${t.endpoint || ''}</span>
                <span style="font-size:11px;color:var(--text-tertiary);margin-left:auto;">${t.read_only === 'true' || t.read_only === true ? '只读' : '可写'}</span>
              </label>`;
            }).join('');
          } else {
            toolList.innerHTML = '<div style="padding:12px;text-align:center;color:var(--text-tertiary);font-size:13px;">暂无工具，请先在"工具中心"创建</div>';
          }
        }
      } catch (e) {
        console.warn('[wizard] 加载资源/Skill/Tool 失败', e);
      }
    }
  },

  /**
   * 完成向导：先创建 RolePack，再创建 Agent 并绑定
   */
  async wizardFinish() {
    // 先收集最后一步的数据
    this._collectStepData(this.wizardStep);

    const data = this.wizardData;

    // 必填校验（对齐 8 步：步骤 0 填写基本信息）
    if (!data.name) {
      this._toast('✕ 请回到第 1 步填写员工姓名', 'error');
      this._wizardJump(0);
      return;
    }
    if (!data.title) {
      this._toast('✕ 请回到第 1 步填写职位', 'error');
      this._wizardJump(0);
      return;
    }
    if (!data.department_id || !data.domain_id) {
      this._toast('✕ 请回到第 2 步选择部门与领域', 'error');
      this._wizardJump(1);
      return;
    }
    if (!data.role_pack_name) {
      this._toast('✕ 请回到第 3 步填写岗位包名称', 'error');
      this._wizardJump(2);
      return;
    }

    // 显示加载中
    const finishBtn = document.querySelector('#wizard-modal button[onclick="AdminModule.wizardFinish()"]');
    if (finishBtn) {
      finishBtn.disabled = true;
      finishBtn.textContent = '正在创建…';
    }

    try {
      // 1. 先创建 RolePack
      const rolePackPayload = {
        name: data.role_pack_name,
        version: data.version || '1.0.0',
        owner: data.owner || 'admin',
        config: {
          resources: data.resources || [],
          skills: data.skills || [],
          tools: data.tools || [],
          permission: {
            read_only: data.read_only !== false,
            acl_mode: data.acl_mode || 'whitelist',
            budget: {
              steps: data.budget_steps || 8,
              calls: data.budget_calls || 6,
              timeout: data.budget_timeout || 60,
              token: data.budget_token || 48000,
            },
          },
          commitment: {
            sla_response: data.sla_response || 30,
            quality_target: data.quality_target || 85,
            escalation: data.escalation || 'owner',
          },
        },
      };

      const rpRes = await fetch('/api/admin/role-packs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(rolePackPayload),
      });

      if (!rpRes.ok) {
        const err = await rpRes.json().catch(() => ({}));
        throw new Error(`岗位包创建失败: ${err.detail || rpRes.status}`);
      }

      const rpResult = await rpRes.json();
      const rolePackId = rpResult.id;

      // 2. 创建 Agent 并绑定 role_pack_id
      const agentPayload = {
        name: data.name,
        title: data.title,
        emoji: data.emoji || '🧑‍💻',
        department_id: data.department_id,
        domain_id: data.domain_id,
        role_pack_id: rolePackId,
        status: data.publish_mode === 'online' ? 'online' : 'trial',
        version: 1,
        owner: data.owner || 'admin',
        description: data.description || '',
        resources: data.resources || [],
        tags: [...(data.skills || []), ...(data.tools || [])],
        // Harness Engineering：行为准则 + 直绑能力（skill_key 数组，优先于岗位包）
        agents_md: data.agents_md || '',
        skills: data.skills || [],
        adoption_rate: 0,
        session_count: 0,
      };

      const agRes = await fetch('/api/admin/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(agentPayload),
      });

      if (!agRes.ok) {
        const err = await agRes.json().catch(() => ({}));
        throw new Error(`员工创建失败: ${err.detail || agRes.status}`);
      }

      // 3. 关闭弹窗，刷新列表
      const modal = document.getElementById('wizard-modal');
      if (modal) modal.remove();
      this.loadTab(this.activeTab);

      // 成功提示
      this._toast(`✓ Agent "${data.name}" 创建成功！`, 'success');

    } catch (e) {
      console.error('[wizard] 创建失败', e);
      if (finishBtn) {
        finishBtn.disabled = false;
        finishBtn.textContent = '提交上线';
      }
      this._toast(`✕ 创建失败：${e.message}`, 'error');
    }
  },

  /**
   * 轻量 toast 提示（替代 alert）
   */
  _toast(msg, type) {
    const t = document.createElement('div');
    t.style.cssText = `position:fixed;top:24px;left:50%;transform:translateX(-50%);padding:12px 24px;border-radius:8px;font-size:14px;font-weight:500;z-index:3000;box-shadow:0 8px 24px rgba(0,0,0,0.15);animation:toast-in 0.3s ease;background:${type === 'success' ? '#059669' : '#DC2626'};color:white;`;
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => {
      t.style.transition = 'opacity 0.3s';
      t.style.opacity = '0';
      setTimeout(() => t.remove(), 300);
    }, 3000);
  },

  /**
   * 获取每个步骤的表单内容（8 步向导）
   */
  getWizardStepContent(step) {
    switch (step) {
      case 0: return this._stepBasic();
      case 1: return this._stepBelong();
      case 2: return this._stepRolePack();
      case 3: return this._stepPermission();
      case 4: return this._stepCommitment();
      case 5: return this._stepPreCheck();
      case 6: return this._stepTrial();
      case 7: return this._stepSubmit();
      default: return '';
    }
  },

  // 步骤 0：基本信息
  _stepBasic() {
    const d = this.wizardData;
    return `
      <div class="wiz-form">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
          <div class="form-group">
            <label>员工姓名 <span style="color:#DC2626;">*</span></label>
            <div class="input-margin"><input type="text" id="wiz-agent-name" value="${d.name || ''}" placeholder="如：林向阳" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;"></div>
          </div>
          <div class="form-group">
            <label>头像 Emoji</label>
            <div class="input-margin"><input type="text" id="wiz-agent-emoji" value="${d.emoji || '🧑‍💻'}" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;"></div>
          </div>
        </div>
        <div class="form-group">
          <label>职位 <span style="color:#DC2626;">*</span></label>
          <div class="input-margin"><input type="text" id="wiz-agent-title" value="${d.title || ''}" placeholder="如：订单域研发员工" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;"></div>
        </div>
        <div class="form-group">
          <label>职责描述</label>
          <div class="input-margin"><textarea id="wiz-agent-desc" rows="3" placeholder="描述 Agent 的职责范围…" style="width:100%;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:8px 13px;font-size:14px;resize:vertical;">${d.description || ''}</textarea></div>
        </div>
        <div class="form-group">
          <label>行为准则（AGENTS.md，可选）</label>
          <div class="input-margin"><textarea id="wiz-agent-agents-md" rows="4" placeholder="Markdown 格式：角色边界、输出规范、禁忌事项…（下一步可用 AI 生成）" style="width:100%;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:8px 13px;font-size:14px;resize:vertical;">${d.agents_md || ''}</textarea></div>
        </div>
        <div style="padding:12px;background:#FEF3C7;border-radius:8px;font-size:12px;color:#92400E;margin-top:12px;">
          <span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">lightbulb</span> 这些信息会展示在员工名片上，后续可在"员工管理"中编辑。
        </div>
      </div>
    `;
  },

  // 步骤 1：归属
  _stepBelong() {
    const d = this.wizardData;
    return `
      <div class="wiz-form">
        <div class="form-group">
          <label>所属部门 <span style="color:#DC2626;">*</span></label>
          <div class="input-margin">
            <select id="wiz-dept" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;">
              <option value="">加载中…</option>
            </select>
          </div>
        </div>
        <div class="form-group">
          <label>所属领域 <span style="color:#DC2626;">*</span></label>
          <div class="input-margin">
            <select id="wiz-domain" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;">
              <option value="">加载中…</option>
            </select>
          </div>
        </div>
        <div class="form-group">
          <label>Owner（负责人）</label>
          <div class="input-margin"><input type="text" id="wiz-owner" value="${d.owner || ''}" placeholder="如：张三" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;"></div>
        </div>
        <div style="margin-top:16px;padding:12px;background:var(--bg-hover);border-radius:8px;">
          <button type="button" onclick="AdminModule.wizardAIGenerate(this)"
            style="padding:8px 16px;border:none;border-radius:999px;background:var(--teal-700);color:white;font-size:13px;cursor:pointer;"><span class="material-symbols-outlined">auto_awesome</span> AI 生成配置草案</button>
          <div id="wiz-aigen-status" style="font-size:12px;color:var(--text-secondary);margin-top:8px;">
            根据已选部门/领域和第 1 步的职位，AI 自动生成姓名、Emoji、职责描述、AGENTS.md，并建议绑定库内能力（第 3 步预勾选）。
          </div>
        </div>
        <div style="padding:12px;background:#FEF3C7;border-radius:8px;font-size:12px;color:#92400E;margin-top:12px;">
          <span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">lightbulb</span> 每个 Agent 必须归属一个部门和一个领域。部门决定对接人，领域决定专业范围。
        </div>
      </div>
    `;
  },

  /**
   * 向导步骤 1：AI 生成配置草案
   * 只收集步骤 1（当前 DOM 是归属页）；步骤 0 数据已在「下一步」时入库 wizardData
   * 生成结果回填 wizardData，suggested_skills 在第 3 步渲染时预勾选
   */
  async wizardAIGenerate(btn) {
    this._collectStepData(1);
    const d = this.wizardData;
    if (!d.department_id || !d.domain_id) {
      this._toast('✕ 请先选择部门与领域', 'error');
      return;
    }
    if (!d.title) {
      this._toast('✕ 请先回到第 1 步填写职位', 'error');
      return;
    }
    btn.disabled = true;
    btn.textContent = '生成中（约 10s）…';
    try {
      const res = await fetch('/api/admin/agents/ai-generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          department_id: d.department_id,
          domain_id: d.domain_id,
          title: d.title,
          hint: d.description || '',
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
      const draft = data.draft || {};
      if (draft.name) d.name = draft.name;
      if (draft.emoji) d.emoji = draft.emoji;
      if (draft.description) d.description = draft.description;
      if (draft.agents_md) d.agents_md = draft.agents_md;
      if (Array.isArray(draft.suggested_skills)) d.skills = draft.suggested_skills;
      const filtered = (data.filtered_skills || []).length;
      this._toast(`✓ 草案已生成：${draft.name || ''}（建议能力 ${(d.skills || []).length} 项${filtered ? `，${filtered} 项不在库中已过滤` : ''}）`, 'success');
      const status = document.getElementById('wiz-aigen-status');
      if (status) status.textContent = '已回填姓名/Emoji/职责/AGENTS.md（回第 1 步可查看修改），建议能力将在第 3 步预勾选。';
    } catch (e) {
      this._toast(`✕ AI 生成失败：${e.message}`, 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = '<span class="material-symbols-outlined">auto_awesome</span> AI 生成配置草案';
    }
  },

  // 步骤 2：组装岗位包（资源 + Skill + Tool + 岗位包名）
  _stepRolePack() {
    const d = this.wizardData;
    return `
      <div class="wiz-form">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;">
          <div class="form-group">
            <label>岗位包名称 <span style="color:#DC2626;">*</span></label>
            <div class="input-margin"><input type="text" id="wiz-pack-name" value="${d.role_pack_name || ''}" placeholder="如：order-domain-agent" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;"></div>
          </div>
          <div class="form-group">
            <label>版本</label>
            <div class="input-margin"><input type="text" id="wiz-pack-version" value="${d.version || '1.0.0'}" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;"></div>
          </div>
        </div>

        <div class="form-group">
          <label><span class="material-symbols-outlined" style="font-size:14px;vertical-align:-2px;">folder</span> 接入资源（多选）</label>
          <div id="wiz-resource-list" style="display:flex;flex-direction:column;gap:8px;">
            <div style="padding:12px;text-align:center;color:var(--text-tertiary);font-size:13px;">正在加载资源列表…</div>
          </div>
        </div>

        <div class="form-group">
          <label><span class="material-symbols-outlined" style="font-size:14px;vertical-align:-2px;">extension</span> 配置能力 Skill（多选）</label>
          <div id="wiz-skill-list" style="display:flex;flex-direction:column;gap:8px;">
            <div style="padding:12px;text-align:center;color:var(--text-tertiary);font-size:13px;">正在加载能力列表…</div>
          </div>
        </div>

        <div class="form-group">
          <label><span class="material-symbols-outlined" style="font-size:14px;vertical-align:-2px;">build</span> 配置工具 MCP（多选）</label>
          <div id="wiz-tool-list" style="display:flex;flex-direction:column;gap:8px;">
            <div style="padding:12px;text-align:center;color:var(--text-tertiary);font-size:13px;">正在加载工具列表…</div>
          </div>
        </div>
      </div>
    `;
  },

  // 步骤 3：权限
  _stepPermission() {
    const d = this.wizardData;
    return `
      <div class="wiz-form">
        <div class="form-group">
          <label>工具权限模式</label>
          <div class="input-margin">
            <select id="wiz-read-only" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;">
              <option value="true" ${d.read_only !== false ? 'selected' : ''}>只读白名单（推荐）</option>
              <option value="false" ${d.read_only === false ? 'selected' : ''}>允许写操作（需审批）</option>
            </select>
          </div>
        </div>

        <div class="form-group">
          <label>ACL 模式</label>
          <div class="input-margin">
            <select id="wiz-acl-mode" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;">
              <option value="whitelist" ${d.acl_mode === 'whitelist' || !d.acl_mode ? 'selected' : ''}>白名单（仅允许声明资源）</option>
              <option value="domain" ${d.acl_mode === 'domain' ? 'selected' : ''}>领域内共享</option>
              <option value="open" ${d.acl_mode === 'open' ? 'selected' : ''}>开放（不推荐）</option>
            </select>
          </div>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
          <div class="form-group">
            <label>最大步数</label>
            <div class="input-margin"><input type="number" id="wiz-budget-steps" value="${d.budget_steps || 8}" min="1" max="50" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;"></div>
          </div>
          <div class="form-group">
            <label>工具调用次数</label>
            <div class="input-margin"><input type="number" id="wiz-budget-calls" value="${d.budget_calls || 6}" min="1" max="50" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;"></div>
          </div>
          <div class="form-group">
            <label>超时（秒）</label>
            <div class="input-margin"><input type="number" id="wiz-budget-timeout" value="${d.budget_timeout || 60}" min="10" max="600" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;"></div>
          </div>
          <div class="form-group">
            <label>Token 上限</label>
            <div class="input-margin"><input type="number" id="wiz-budget-token" value="${d.budget_token || 48000}" min="1000" step="1000" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;"></div>
          </div>
        </div>

        <div style="padding:12px;background:var(--brand-primary-light);border-radius:8px;font-size:12px;color:var(--brand-primary);margin-top:12px;">
          <span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">lock</span> 安全提示：所有工具调用经过 PEP（Policy Enforcement Point），跨部门协作需对接人授权。
        </div>
      </div>
    `;
  },

  // 步骤 4：输出承诺
  _stepCommitment() {
    const d = this.wizardData;
    return `
      <div class="wiz-form">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
          <div class="form-group">
            <label>响应时效 SLA（秒）</label>
            <div class="input-margin"><input type="number" id="wiz-sla-response" value="${d.sla_response || 30}" min="5" max="300" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;"></div>
          </div>
          <div class="form-group">
            <label>质量目标（采纳率 %）</label>
            <div class="input-margin"><input type="number" id="wiz-quality-target" value="${d.quality_target || 85}" min="0" max="100" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;"></div>
          </div>
        </div>

        <div class="form-group">
          <label>升级策略</label>
          <div class="input-margin">
            <select id="wiz-escalation" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;">
              <option value="owner" ${d.escalation === 'owner' || !d.escalation ? 'selected' : ''}>通知 Owner（默认）</option>
              <option value="dept" ${d.escalation === 'dept' ? 'selected' : ''}>升级到部门对接人</option>
              <option value="auto" ${d.escalation === 'auto' ? 'selected' : ''}>自动转人工客服</option>
            </select>
          </div>
        </div>

        <div style="padding:12px;background:var(--bg-page);border-radius:8px;margin-top:12px;">
          <div style="font-size:13px;font-weight:500;margin-bottom:8px;"><span class="material-symbols-outlined" style="font-size:14px;vertical-align:-2px;">assignment</span> 承诺样例：</div>
          <ul style="font-size:12px;color:var(--text-secondary);line-height:22px;">
            <li><span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">timer</span> 单次响应 ≤ ${d.sla_response || 30} 秒</li>
            <li><span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">monitoring</span> 试运行期采纳率目标 ≥ ${d.quality_target || 85}%</li>
            <li><span class="material-symbols-outlined" style="font-size:13px;vertical-align:-2px;">notification_important</span> 连续 3 次未达标自动 ${d.escalation === 'dept' ? '升级到部门对接人' : (d.escalation === 'auto' ? '转人工' : '通知 Owner')}</li>
          </ul>
        </div>
      </div>
    `;
  },

  // 步骤 5：预检（基于 wizardData 真实校验）
  _stepPreCheck() {
    const d = this.wizardData;
    const checks = [
      {
        label: '已填写员工姓名',
        ok: !!(d.name && d.name.trim()),
        severity: 'blocker',
      },
      {
        label: '已填写职位',
        ok: !!(d.title && d.title.trim()),
        severity: 'blocker',
      },
      {
        label: '已归属部门与领域',
        ok: !!(d.department_id && d.domain_id),
        severity: 'blocker',
      },
      {
        label: '已设定 Owner',
        ok: !!(d.owner && d.owner.trim()),
        severity: 'blocker',
      },
      {
        label: '已命名岗位包',
        ok: !!(d.role_pack_name && d.role_pack_name.trim()),
        severity: 'blocker',
      },
      {
        label: '至少绑定 1 个资源',
        ok: !!(d.resources && d.resources.length > 0),
        severity: 'warning',
      },
      {
        label: '至少配置 1 个 Skill',
        ok: !!(d.skills && d.skills.length > 0),
        severity: 'warning',
      },
      {
        label: '至少配置 1 个工具',
        ok: !!(d.tools && d.tools.length > 0),
        severity: 'warning',
      },
      {
        label: '权限为只读白名单',
        ok: d.read_only !== false,
        severity: 'info',
      },
      {
        label: '已设定输出承诺（SLA + 质量）',
        ok: !!(d.sla_response && d.quality_target),
        severity: 'warning',
      },
    ];

    const blockers = checks.filter(c => !c.ok && c.severity === 'blocker');
    const warnings = checks.filter(c => !c.ok && c.severity === 'warning');

    const sevLabel = { blocker: '阻断', warning: '建议', info: '信息' };
    const sevColor = { blocker: '#DC2626', warning: '#D97706', info: '#2563EB' };

    return `
      <div>
        <p style="font-size:13px;color:var(--text-secondary);margin-bottom:16px;">基于当前配置执行预检…</p>
        <div style="display:flex;flex-direction:column;gap:10px;">
          ${checks.map(c => `
            <div style="display:flex;align-items:center;gap:10px;padding:10px 14px;background:${c.ok ? '#ECFDF5' : (c.severity === 'blocker' ? '#FEE2E2' : '#FEF3C7')};border-radius:8px;">
              <span style="font-size:16px;">${c.ok ? '✓' : (c.severity === 'blocker' ? '✕' : '⚠')}</span>
              <span style="font-size:13px;flex:1;">${c.label}</span>
              <span style="font-size:11px;color:${c.ok ? '#059669' : sevColor[c.severity]};font-weight:500;">
                ${c.ok ? '通过' : sevLabel[c.severity]}
              </span>
            </div>
          `).join('')}
        </div>
        ${blockers.length > 0 ? `
          <div style="padding:12px;background:#FEE2E2;border-radius:8px;font-size:12px;color:#991B1B;margin-top:12px;">
            ✕ ${blockers.length} 项阻断未通过：请返回相应步骤补充后再提交。
          </div>
        ` : warnings.length > 0 ? `
          <div style="padding:12px;background:#FEF3C7;border-radius:8px;font-size:12px;color:#92400E;margin-top:12px;">
            ⚠ ${warnings.length} 项建议待完善：可以先进入试运行，建议后续补充。
          </div>
        ` : `
          <div style="padding:12px;background:#ECFDF5;border-radius:8px;font-size:12px;color:#065F46;margin-top:12px;">
            ✓ 全部检查通过，可以提交上线。
          </div>
        `}
      </div>
    `;
  },

  // 步骤 6：试运行
  _stepTrial() {
    const d = this.wizardData;
    return `
      <div class="wiz-form">
        <div class="form-group">
          <label>发布模式</label>
          <div class="input-margin">
            <select id="wiz-publish-mode" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;">
              <option value="trial" ${d.publish_mode === 'trial' || !d.publish_mode ? 'selected' : ''}>试运行（推荐）</option>
              <option value="online" ${d.publish_mode === 'online' ? 'selected' : ''}>直接上线</option>
            </select>
          </div>
        </div>
        <div class="form-group">
          <label>试运行天数</label>
          <div class="input-margin"><input type="number" id="wiz-trial-days" value="${d.trial_days || 7}" min="1" max="30" style="width:100%;height:40px;background:var(--bg-input);border:1px solid transparent;border-radius:8px;padding:0 13px;font-size:14px;"></div>
        </div>
        <div style="padding:12px;background:var(--bg-page);border-radius:8px;margin-top:12px;">
          <div style="font-size:13px;font-weight:500;margin-bottom:8px;"><span class="material-symbols-outlined" style="font-size:14px;vertical-align:-2px;">science</span> 试运行机制：</div>
          <ul style="font-size:12px;color:var(--text-secondary);line-height:22px;">
            <li>所有回答会标注"试运行"标记</li>
            <li>采纳率自动统计，不影响线上业务</li>
            <li>满 ${d.trial_days || 7} 天且采纳率达标后可手动转为"已上线"</li>
            <li>可随时回滚到"待校验"状态</li>
          </ul>
        </div>
      </div>
    `;
  },

  // 步骤 7：提交上线（确认信息摘要）
  _stepSubmit() {
    const d = this.wizardData;
    return `
      <div>
        <div style="text-align:center;margin-bottom:20px;">
          <div style="width:56px;height:56px;background:var(--teal-700);border-radius:18px;display:flex;align-items:center;justify-content:center;font-size:24px;color:white;margin:0 auto 12px;"><span class="material-symbols-outlined" style="font-size:24px;vertical-align:-2px;">rocket_launch</span></div>
          <h4 style="font-size:18px;font-weight:600;margin-bottom:4px;">确认并提交</h4>
          <p style="font-size:13px;color:var(--text-secondary);">点击"提交上线"将创建岗位包与 Agent</p>
        </div>

        <div style="padding:16px;background:var(--bg-page);border-radius:8px;font-size:13px;line-height:22px;">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px 16px;">
            <div><span style="color:var(--text-tertiary);">姓名：</span>${d.emoji || '🧑‍💻'} ${d.name || '-'}</div>
            <div><span style="color:var(--text-tertiary);">职位：</span>${d.title || '-'}</div>
            <div><span style="color:var(--text-tertiary);">部门/领域：</span>${d.department_id || '-'} / ${d.domain_id || '-'}</div>
            <div><span style="color:var(--text-tertiary);">Owner：</span>${d.owner || '-'}</div>
            <div><span style="color:var(--text-tertiary);">岗位包：</span>${d.role_pack_name || '-'} v${d.version || '1.0.0'}</div>
            <div><span style="color:var(--text-tertiary);">发布模式：</span>${d.publish_mode === 'online' ? '直接上线' : '试运行'}</div>
          </div>
          <hr style="border:none;border-top:1px solid var(--border-light);margin:12px 0;">
          <div><span style="color:var(--text-tertiary);">资源：</span>${(d.resources || []).length} 个 · <span style="color:var(--text-tertiary);">Skill：</span>${(d.skills || []).length} 个 · <span style="color:var(--text-tertiary);">工具：</span>${(d.tools || []).length} 个</div>
          <div><span style="color:var(--text-tertiary);">预算：</span>${d.budget_steps || 8} 步 / ${d.budget_calls || 6} 次调用 / ${d.budget_timeout || 60}s / ${(d.budget_token || 48000)/1000}k token</div>
          <div><span style="color:var(--text-tertiary);">承诺：</span>SLA ${d.sla_response || 30}s · 采纳率目标 ${d.quality_target || 85}%</div>
        </div>

        <div style="padding:12px;background:#FEF3C7;border-radius:8px;font-size:12px;color:#92400E;margin-top:12px;">
          ⚠ 提交后将写入数据库并记录审计日志，操作不可撤销。
        </div>
      </div>
    `;
  },
};

window.AdminModule = AdminModule;