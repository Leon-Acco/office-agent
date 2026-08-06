---
name: Office_Agent
colors:
  # 品牌主色（用户选定：深空蓝）
  brand_primary: "#1E40AF"
  brand_primary_hover: "#1E3A8A"
  brand_primary_light: "#EFF6FF"
  brand_primary_soft: "#DBEAFE"

  # 中性色基底
  bg_page: "#FAFAFA"
  bg_surface: "#FFFFFF"
  bg_input: "#F3F3F5"
  bg_hover: "#F5F5F5"
  bg_dark: "#171717"

  # 文字层级（4 级灰阶）
  text_primary: "#171717"
  text_secondary: "#737373"
  text_tertiary: "#A1A1A1"
  text_on_brand: "#FFFFFF"

  # 语义状态色
  status_success: "#059669"
  status_success_bg: "#ECFDF5"
  status_warning: "#D97706"
  status_warning_bg: "#FEF3C7"
  status_danger: "#DC2626"
  status_danger_bg: "#FEE2E2"
  status_info: "#0EA5E9"
  status_info_bg: "#F0F9FF"
  status_neutral: "#6B7280"
  status_neutral_bg: "#F3F4F6"

  # 吉祥物主题色（保持温暖橙黄，作为亲和力强调色）
  mascot_glow: "rgba(255,185,0,0.25)"
  mascot_glow2: "rgba(255,210,48,0.2)"
  accent_warm_orange: "#E17100"
  accent_sunshine: "#FFD237"

  # 边框
  border_default: "#E5E5E5"
  border_light: "#F0F0F0"
  border_strong: "#D1D5DB"

  # 图表色（保留当前主题）
  chart_primary: "#171717"
  chart_secondary: "#D4D4D4"

  # 阴影
  shadow_card: "0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.02)"
  shadow_modal: "0 20px 60px rgba(17, 24, 39, 0.15)"
  shadow_mascot: "0 20px 60px rgba(0,0,0,0.25)"
---

# Design System: Office_Agent（Agent 办公室）

**Project ID:** office-agent-v2
**Version:** 2.0（深空蓝主题 + Stitch 规范）
**Figma Source:** https://www.figma.com/design/jBSwYPcSvAxa1unHU3Et2M/AgentCompany

## 1. Visual Theme & Atmosphere

**视觉基调：克制的科技感 + 吉祥物的温暖。** 整体采用接近纯白的底色（#FAFAFA），配合极浅灰（#F3F3F5）的输入框与卡片次级背景，形成"纸面般的干净"层次。深空蓝（#1E40AF）作为主品牌色仅出现在主按钮、链接、激活态等关键触点上，避免视觉噪音。吉祥物 Mascot 的暖橙黄光晕（#FFD237）保留作为情感触点——只在登录页和过渡动画中出现，强化"AI 公司"的亲和力。

**信息层级哲学：用灰阶而非颜色区分层级。** 标题用接近纯黑的 #171717，次级内容用 #737373，辅助说明用 #A1A1A1——通过灰度递进引导视线，而非用花哨颜色抢夺注意力。状态色（成功绿/警告橙/危险红/信息蓝）仅用于徽章和状态指示器，不参与主视觉。整体风格参考 Linear、Notion、Vercel Dashboard 的"克制专业感"。

## 2. Color Palette & Roles

### Primary Foundation（品牌主色 · 深空蓝）
- **Deep Space Blue** `#1E40AF` — 主 CTA、激活态、品牌链接。用于"登录"按钮、侧边栏激活条、主要操作触发器
- **Midnight Blue** `#1E3A8A` — 主色 hover 加深态
- **Sky Tint** `#EFF6FF` — 主色浅底，用于徽章背景、信息提示条
- **Soft Sky** `#DBEAFE` — 主色柔光，用于 hover 背景与选中态填充

### Accent & Interactive（强调与交互）
- **Warm Orange** `#E17100` — 仅用于"提示性"文字（如登录页"移动鼠标，光球会与你对视"），强化温暖感
- **Sunshine** `#FFD237` — 仅用于 Mascot 吉祥物光晕，不进入业务 UI
- **Deep Charcoal** `#171717` — 次按钮、图表主色、深色背景

### Typography & Text Hierarchy（4 级灰阶）
- **Ink Black** `#171717` — 标题、主文本（H1-H3、卡片主数据）
- **Graphite** `#737373` — 次级内容（描述文本、meta 信息）
- **Silver** `#A1A1A1` — 辅助说明（时间戳、目标值、placeholder）
- **Mist White** `#FFFFFF` — 主色按钮上的文字、深色背景上的文字

### Functional States（语义状态 · 与品牌色解耦）
- **Success Green** `#059669` / bg `#ECFDF5` — "可用"、"已发布"
- **Warning Amber** `#D97706` / bg `#FEF3C7` — "索引中"、"试运行"、"待校验"
- **Danger Red** `#DC2626` / bg `#FEE2E2` — "受限"、"已过期"
- **Info Sky** `#0EA5E9` / bg `#F0F9FF` — 提示信息
- **Neutral Gray** `#6B7280` / bg `#F3F4F6` — "维护中"、"默认徽章"

## 3. Typography Rules

### Hierarchy & Weights

| 元素 | 字号 | 字重 | 行高 | 字间距 | 用途 |
|:---|:---|:---|:---|:---|:---|
| H1 页面标题 | 24px | 500 (Medium) | 36px | 0 | 每个页面顶部主标题 |
| H2 区块标题 | 20px | 500 | 30px | 0 | "一家全部由 AI 员工组成的公司" |
| H3 卡片标题 | 18px | 500 | 27px | 0 | "本周会话量"、"部门与员工" |
| KPI Value | 30px | 500 | 30px | 0 | KPI 数字（如 72%） |
| Body Large | 16px | 400 | 24px | 0 | 副标题、描述段落 |
| Body Base | 14px | 400 | 21px | 0 | 主正文、表格 |
| Body Small | 13px | 400 | 20px | 0 | 标签、次级文本 |
| Caption | 12px | 400 | 18px | 0 | meta、时间戳 |
| Micro | 11px | 500 | 16px | 0 | 徽章、状态指示 |
| Button | 14px | 500 | 20px | 0 | 按钮文字 |

**字体族：** `'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`
**字体特征：** Inter 是 geometric sans-serif，数字字形等宽便于数据展示；中文 fallback 到苹方/微软雅黑保持现代感。所有数字、英文优先渲染 Inter。

### Spacing Principles
- **8 倍数系统**：4 / 8 / 12 / 16 / 24 / 32 / 48 / 64
- **页面容器外边距**：48px（Figma 主流值）
- **卡片内边距**：21px（KPI 卡） / 24px（内容卡）
- **组件间垂直节奏**：16px 主流，8px 紧凑，24px 宽松

## 4. Component Stylings

### Buttons

**主按钮（Primary CTA · 深空蓝）**
```css
background: var(--brand-primary);    /* #1E40AF */
color: var(--text-on-brand);         /* #FFFFFF */
border: none;
border-radius: var(--radius-md);     /* 8px */
padding: 12px 24px;                  /* Figma: 44px 高 */
font-size: 14px; font-weight: 500;
transition: background 0.15s ease;
/* hover: background → #1E3A8A */
/* disabled: opacity 0.5; cursor: not-allowed */
```
**气质：** 沉稳、专业、有分量感。8px 圆角避免"过甜"，44px 高度保证触达性。

**次按钮（Secondary）**
```css
background: white;
color: var(--text-primary);
border: 1px solid var(--border-default);  /* #E5E5E5 */
border-radius: 8px;
/* hover: border-color → #D1D5DB; background → #F9FAFB */
```

**Ghost 按钮（列表项内轻量操作）**
仅文字 + 透明背景，hover 时填充 `#F5F5F5`。

### Cards & Containers

**内容卡片（KPI 卡 / 区块容器）**
- 圆角：12px（比按钮稍大，视觉权重更高）
- 阴影：`0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.02)` — 极浅双层
- 内边距：21px（紧凑型 KPI）/ 24px（标准内容卡）
- 边框：**无**，完全靠阴影区分层级

**登录卡片（右栏表单容器）**
- 整块白色背景，无独立卡片阴影
- 表单最大宽度 448px，垂直居中
- 输入框之间垂直间距 32px

**员工名片弹层（Modal）**
- 圆角：16px（最大值，强化层级）
- 阴影：`0 20px 60px rgba(17, 24, 39, 0.15)` — 深阴影
- 顶部 4px 色带表示状态（绿/橙/红/灰）

### Navigation

**侧边栏（220px 宽，Figma 256px 略宽）**
```css
width: 220px;
background: white;
border-right: 1px solid var(--border-default);
padding: 16px;
```
**导航项（nav-item）**
- 默认态：透明背景，`#737373` 文字
- Hover：`#F5F5F5` 背景
- Active：`var(--brand-primary-soft)` 浅蓝填充 + 左侧 3px 蓝色指示条 + 文字变 `#171717`
- 每项高度 56px（Figma 主流值），圆角 8px
- 图标 20px，与文字间距 12px

**底部用户区**
- 56px 高度
- 头像 32px 圆形（首字符 fallback）
- 顶部 1px 分隔线

### Inputs & Forms

```css
height: 44px;
background: var(--bg-input);          /* #F3F3F5 */
border: 1px solid transparent;
border-radius: 8px;
padding: 0 13px;
font-size: 14px;
/* focus: border-color → #1E40AF; background → white */
/* error: border-color → #DC2626 */
```
**特征：** 默认态无边框（靠灰色填充区分），focus 时才显式描边——降低视觉噪音。

### Domain-Specific Components

**Mascot 吉祥物（240×240）**
- 三层结构：外光晕（模糊 64px） + 内光晕（模糊 24px） + 核心（径向渐变 #FFFFFF → #D6D3D1）
- 动画：3 秒一个周期的浮动（`translateY(-6px)`） + 光晕脉冲 + 嘴部呼吸
- 眼睛瞳孔跟随鼠标（`transform: translate()` 0.08s 过渡）

**KPI 数字卡片**
- 三段式：label / value+change / target
- 主数字 30px Medium，变化值 13px Medium 绿色（`#34D399`）
- 目标值 12px 灰色辅助说明

**状态徽章（Lifecycle Badge）**
- 胶囊形（`border-radius: 12px`），padding `2px 8px`
- 文字 10px Medium
- 浅底 + 深字双色配（如 `#ECFDF5` bg + `#059669` text）

## 5. Layout Principles

### Grid & Structure

- **最大内容宽度**：1152px（参考 Figma 容器宽度）
- **侧边栏宽度**：220px（Figma 256px，实测 220 更紧凑）
- **顶栏高度**：56px
- **KPI 网格**：`repeat(4, 1fr)` 间距 16px
- **双栏内容**：`1fr 340px`（主内容 + 侧边面板）
- **员工卡片网格**：`repeat(3, 1fr)` 桌面 / `repeat(2, 1fr)` 平板 / `1fr` 手机
- **知识卡片网格**：`repeat(3, 1fr)` / `repeat(2, 1fr)` / `1fr`

### Whitespace Strategy

- **基础单位**：8 倍数（4/8/12/16/24/32/48）
- **页面外边距**：48px（Figma 容器标准）
- **卡片间垂直节奏**：16px（主流） / 24px（区块分隔）
- **表单字段间距**：32px（避免密集感）

### Alignment & Visual Balance

- **页面标题左对齐**，副标题左对齐，标题下方间距 4px
- **登录页严格 50/50**（Figma 775.5/775.5）
- **数据看板左密右疏**：KPI 横铺 4 个 + 主图表占大栏 + 右侧 340px 侧栏
- **吉祥物永远居中**（登录页 + 过渡页）

### Responsive Behavior

| 断点 | 宽度 | 行为 |
|:---|:---|:---|
| Desktop | ≥1280px | 完整双栏 + 4 列 KPI |
| Laptop | 1024-1279px | 双栏 + 2 列 KPI |
| Tablet | 768-1023px | 单栏登录 + 2 列卡片 + 折叠侧边栏 |
| Mobile | <768px | 单栏 + 1 列卡片 + 抽屉式导航 |

**触达性**：所有可点击元素 ≥ 44×44px（iOS HIG 标准）。

## 6. Design System Notes for Stitch Generation

### Language to Use

**正向描述词（用于 Stitch prompt）：**
> "Clean, professional, enterprise-grade dashboard with deep space blue (#1E40AF) as primary. Minimal grayscale palette with 4-level text hierarchy. 8px rounded corners, generous whitespace (48px page margins), subtle dual-layer shadows. Reference style: Linear, Notion, Vercel Dashboard. Trustworthy but not boring — warm orange Mascot accent appears only on login page for emotional touch."

**反向描述词（要避免）：**
> "Avoid: neon colors, glassmorphism, heavy gradients, big shadows, playful illustrations in business UI. Do not use warm colors (orange/red/yellow) for primary actions — they are reserved for status badges and Mascot only."

### Color References

- 主 CTA：`#1E40AF` on `#FFFFFF`（对比度 8.6:1，AAA 级）
- 次 CTA：`#171717` text on `#FFFFFF` + `#E5E5E5` border
- 危险按钮：`#DC2626` on `#FFFFFF`
- KPI 数字：`#171717` 30px Medium
- 状态徽章：浅底深字双色（如 `#ECFDF5` + `#059669`）

### Component Prompts

**生成登录页：**
> "Enterprise SaaS login page, strict 50/50 two-column split. Left: white background with centered floating 3D light orb mascot (warm yellow glow), brand logo top-left, tagline '一家全部由 AI 员工组成的公司', subtitle, bottom security note. Right: white panel with centered 448px form, '欢迎回来' H1, email/password inputs (gray-filled, no border by default), full-width deep blue login button. Subtle blur glow in top-right corner. Max width 1551px, height 100vh."

**生成 KPI 仪表盘：**
> "Clean enterprise dashboard. Top: 4-column KPI grid with large 30px medium numbers, small gray labels, green change indicators, gray target text. Below: two-column layout (1fr + 340px) with bar chart on left (black + gray bars, no chart border) and department list on right (emoji + name + domains + member count badge). Generous 48px margins, 16px gaps, 12px rounded cards with subtle 1px shadow."

**生成员工名片弹窗：**
> "Agent business card modal, 420px wide, 16px rounded corners, 4px colored top stripe (green=available, amber=indexing, red=restricted, gray=maintenance). 56x56 rounded avatar with emoji, name + status badge + role + department. 4-column metric grid (adoption rate, sessions, version, owner) with hairline dividers. Resource tags as small gray pills. Two-button footer: primary blue 'Ask this agent' + secondary 'Close'."

### Incremental Iteration

**调整品牌色：** 修改 `--brand-primary` 一个变量，主按钮、激活态、链接全部跟随变化。状态色独立不跟随。

**调整密度：** 修改 `--space-4` (16px) 的倍数即可全局调整紧凑度。

**增加新状态色：** 在 `tokens.css` 添加 `--status-xxx` + `--status-xxx-bg`，在 `STATUS_MAP` 添加映射，组件无需改动。

**暗色模式预留：** 所有颜色走 CSS 变量，未来只需重定义 `:root[data-theme="dark"]` 即可切换。

---

**版本历史：**
- v2.0 (2026-07-21)：引入深空蓝主题，统一设计令牌，对齐 Figma 设计稿
- v1.0：初始版本，橙黄主题（仅 Mascot 保留）
