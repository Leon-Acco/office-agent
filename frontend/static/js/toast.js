/**
 * 全局 Toast 通知组件
 * 替代原生 alert() / confirm()，提供优雅的弹窗提示
 */

/**
 * 资源/知识/部门等数据 icon 字段统一渲染为 Material Symbols
 * 数据库历史值是 emoji，做已知映射；未知值（用户自定义）转义后原样显示
 * @param {string} icon - 数据库存的 icon 值
 * @param {string} fallback - 空值时使用的 Material 图标名
 * @param {number} size - 图标字号（px）
 */
window.msIcon = function (icon, fallback = 'description', size = 15) {
  const map = {
    '📄': 'description', '📕': 'picture_as_pdf', '📘': 'description', '📗': 'table',
    '📙': 'slideshow', '📜': 'description', '🐍': 'code', '☕': 'code',
    '📦': 'inventory_2', '📁': 'folder', '📂': 'folder_open', '📚': 'menu_book',
    '🧩': 'extension', '🔧': 'build',
  };
  const name = map[icon] || (icon ? null : fallback);
  if (name) {
    return `<span class="material-symbols-outlined" style="font-size:${size}px;vertical-align:-2px;">${name}</span>`;
  }
  // 未知自定义 icon 原样显示（转义防注入）
  return String(icon).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
};

const Toast = {
  _container: null,

  /**
   * 初始化容器
   */
  _init() {
    if (this._container) return;
    this._container = document.createElement('div');
    this._container.id = 'toast-container';
    this._container.style.cssText = `
      position: fixed; top: 20px; right: 20px; z-index: 99999;
      display: flex; flex-direction: column; gap: 8px;
      pointer-events: none; max-width: 400px;
    `;
    document.body.appendChild(this._container);
  },

  /**
   * 显示 Toast
   * @param {string} message - 消息内容
   * @param {string} type - 类型：success / error / warning / info
   * @param {number} duration - 显示时长（毫秒），0 为不自动关闭
   */
  show(message, type = 'info', duration = 3000) {
    this._init();

    const colors = {
      success: { bg: '#059669', icon: '✓' },
      error: { bg: '#DC2626', icon: '✕' },
      warning: { bg: '#D97706', icon: '⚠' },
      info: { bg: '#1E40AF', icon: 'ℹ' },
    };
    const c = colors[type] || colors.info;

    const toast = document.createElement('div');
    toast.style.cssText = `
      display: flex; align-items: center; gap: 10px;
      padding: 12px 16px; background: white;
      border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
      border-left: 4px solid ${c.bg};
      pointer-events: auto; cursor: pointer;
      animation: toast-slide-in 0.3s ease;
      font-size: 13px; color: #171717; line-height: 1.5;
      max-width: 380px; word-break: break-word;
    `;
    toast.innerHTML = `
      <span style="color:${c.bg};font-size:16px;font-weight:bold;flex-shrink:0;">${c.icon}</span>
      <span style="flex:1;">${message}</span>
      <span style="color:#9CA3AF;font-size:16px;flex-shrink:0;margin-left:4px;" onclick="event.stopPropagation();this.parentElement.remove()">×</span>
    `;

    toast.onclick = () => toast.remove();
    this._container.appendChild(toast);

    // 动画样式
    if (!document.getElementById('toast-style')) {
      const style = document.createElement('style');
      style.id = 'toast-style';
      style.textContent = `
        @keyframes toast-slide-in {
          from { transform: translateX(100%); opacity: 0; }
          to { transform: translateX(0); opacity: 1; }
        }
        @keyframes toast-slide-out {
          from { transform: translateX(0); opacity: 1; }
          to { transform: translateX(100%); opacity: 0; }
        }
      `;
      document.head.appendChild(style);
    }

    if (duration > 0) {
      setTimeout(() => {
        toast.style.animation = 'toast-slide-out 0.3s ease forwards';
        setTimeout(() => toast.remove(), 300);
      }, duration);
    }

    return toast;
  },

  success(msg, duration) { return this.show(msg, 'success', duration); },
  error(msg, duration) { return this.show(msg, 'error', duration || 5000); },
  warning(msg, duration) { return this.show(msg, 'warning', duration); },
  info(msg, duration) { return this.show(msg, 'info', duration); },

  /**
   * 确认对话框（替代 confirm）
   * @param {string} message - 确认消息
   * @param {string} confirmText - 确认按钮文字
   * @returns {Promise<boolean>}
   */
  confirm(message, confirmText = '确认') {
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.style.cssText = `
        position: fixed; inset: 0; background: rgba(0,0,0,0.4);
        z-index: 99998; display: flex; align-items: center; justify-content: center;
        animation: toast-fade-in 0.2s ease;
      `;

      const dialog = document.createElement('div');
      dialog.style.cssText = `
        background: white; border-radius: 12px; padding: 24px;
        max-width: 400px; width: 90%; box-shadow: 0 20px 25px rgba(0,0,0,0.1);
      `;
      dialog.innerHTML = `
        <div style="font-size:15px;font-weight:600;color:#171717;margin-bottom:8px;">确认操作</div>
        <div style="font-size:13px;color:#6B7280;margin-bottom:20px;line-height:1.5;">${message}</div>
        <div style="display:flex;gap:8px;justify-content:flex-end;">
          <button id="toast-cancel" style="padding:8px 18px;border:1px solid #E5E7EB;border-radius:999px;background:white;font-size:13px;cursor:pointer;">取消</button>
          <button id="toast-ok" style="padding:8px 18px;border:none;border-radius:999px;background:#DC2626;color:white;font-size:13px;cursor:pointer;">${confirmText}</button>
        </div>
      `;

      overlay.appendChild(dialog);
      document.body.appendChild(overlay);

      dialog.querySelector('#toast-cancel').onclick = () => { overlay.remove(); resolve(false); };
      dialog.querySelector('#toast-ok').onclick = () => { overlay.remove(); resolve(true); };
      overlay.onclick = (e) => { if (e.target === overlay) { overlay.remove(); resolve(false); } };
    });
  },
};

// 全局暴露
window.Toast = Toast;
