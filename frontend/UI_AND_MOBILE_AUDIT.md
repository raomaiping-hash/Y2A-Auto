# Y2A-Auto 前端 · UI/交互逐页审查发现与移动端适配规范

> 分支：`rmp`　范围：全部 11 视图 + `AppLayout` + 共享 UI 组件（`styles/tokens.css`、`styles/components.css`、`components/ui/*`）
> 视口：375 / 768 / 1440　验收基线：`cd frontend && npm run build` 通过
> 契约：本文件为 t1 权威归档；每条发现含 `文件:行号 / 严重度 / 修复建议 / 归属 fixer 域`。

---

## 1. 结论摘要

- 全站具备良好响应式基础：`tokens.css` 有完整设计令牌，多处已实现 `@media` 栅格降级与表格卡片化，`AppLayout` 已有 `<=900px` 抽屉侧栏。
- 移动端硬伤集中在：**无底部导航**（抽屉是唯一路径）、**MonitorView / MonitorHistory 表格在 375px 横向滚动**、**触控目标 <44px**（`.btn-icon` 34 / `UiToggle` 22 高）、**UiModal 未底部抽屉化**、**断点 900/960/1080/1100/768/720/560 混用**、少量死代码与令牌错配。
- 桌面（1440）表现良好，工作重心在 `<=768px` 的导航、触控、卡片化与安全区。
- 唯一**跨任务构建阻断**：`MonitorView.vue:232` 的 TS2322（`:aria-pressed` 类型），归属于 page-fixer-b（配置管理页），修好后全量 `npm run build` 即恢复。

---

## 2. 逐视图 / 组件审查发现清单

> 严重度：`高` = 移动端阻断或明显交互缺陷；`中` = 体验折损；`低` = 代码/语义细节。
> 归属域：`ui-architect`（布局/全局/共享组件）、`page-fixer-a`（Dashboard/Tasks/TaskDetail）、`page-fixer-b`（Monitor/MonitorConfig/MonitorHistory）、`page-fixer-c`（Login/ManualReview/NotFound/PagePlaceholder）、`SettingsView` 归属 `page-fixer-b（配置管理页）`。

### 2.1 高（阻断 / 明显缺陷）

- **A1 | 移动端无底部导航，抽屉是唯一入口** — `frontend/src/layouts/AppLayout.vue:336`。`<=900px` 仅抽屉（hamburger 触发）。5 主路由（`/`、`/tasks`、`/review`、`/monitor`、`/settings`）应放底部导航。**归属：ui-architect**。建议：`<767px` 固定底部导航（图标+标签+安全区），`768–1023px` 抽屉，`>=1024px` 固定侧栏。**（已在 t2 落地）**

- **A2 | MonitorView「最近发现」表格 375px 横向滚动** — `frontend/src/views/MonitorView.vue:277-308`。`.table-wrap { overflow-x:auto }` + 6 列，375 下无法一次看懂。**归属：page-fixer-b**。建议：接入 `.table-cards` 卡片化（`components.css` 已提供），`td` 补 `data-label`。

- **A3 | MonitorHistoryView 表格（8 列）375px 横向滚动** — `frontend/src/views/MonitorHistoryView.vue:133-181`。列更多，必须卡片化。**归属：page-fixer-b**。建议：同 A2，复用 `.table-cards`。

- **A4 | 顶栏在 375px 拥挤** — `frontend/src/layouts/AppLayout.vue:116-126`。`.topbar-title` 无收缩/省略，窄屏被挤压。**归属：ui-architect**。建议：标题 `flex:1 1 auto; min-width:0; nowrap; ellipsis`，底部导航模式隐藏菜单按钮、新建任务图标化。**（t2 已落地）**

- **A5 | 全部 4 个 implementation 受 MonitorView 类型错误阻断** — `frontend/src/views/MonitorView.vue:232`。TS2322 `unknown`→`Booleanish`。**归属：page-fixer-b**。建议：`:aria-pressed="!!cfg.enabled"`（或收窄类型）。修好即恢复 t2/t3/t5 与 t6/t7/t8/t10。

### 2.2 中（体验折损）

- **B1 | `.btn-icon` 触控 34px <44px** — `frontend/src/styles/components.css:111`、`UiDropdown.vue:82`、`ThemeSwitcher.vue`。**归属：ui-architect**。建议：移动端 `min 40px`（推荐 44px）。**（t2 已统一 `.btn-icon` 40px）**

- **B2 | `UiToggle` 触控高度 22px 偏小** — `components.css:271/.toggle`、`UiToggle.vue`。**归属：ui-architect**。建议：移动端开关高度 ≥24px，外层 `.ui-toggle-row` `min-height:44px`。**（t2 已加大）**

- **B3 | `UiPagination` 移动端可能横向溢出** — `frontend/src/components/ui/UiPagination.vue:60-64`。`display:flex; gap:4px` 无换行，`totalPages` 大时溢出。**归属：ui-architect**。建议：`<768px` `flex-wrap:wrap`。**（t2 已落地）**

- **B4 | `UiModal` 移动端未底部抽屉化、内边距大** — `frontend/src/components/ui/UiModal.vue:62-86`。375 下仍居中弹窗 + `padding:24px`，脚部按钮 `justify-content:flex-end`。**归属：ui-architect**。建议：`<767px` 贴底抽屉、顶部圆角、脚部按钮全宽堆叠、底部 `env(safe-area-inset-bottom)`。**（t2 已落地）**

- **B5 | 断点混用** — 现状 `900/960/1080/1100/768/720/560` 并存。**归属：ui-architect**。建议：唯一断点 480/768/1024，逐步收敛。**（t2 已在 tokens.css 固化文档）**

- **B6 | 抽屉未锁 body 滚动、无焦点圈** — `AppLayout.vue:336-364`。`sidebar--open` 未锁滚动、无 focus trap/aria-modal。**归属：ui-architect**。建议：抽屉打开 `body{overflow:hidden}`+焦点管理。**（t2 已加滚动锁）**

- **B7 | 抽屉在非导航跳转后不自动关闭** — `AppLayout.vue:123-125` 顶栏「新建任务」是 RouterLink，不触发关闭；route 变化未统一处理。**归属：ui-architect**。建议：`watch(route.path)` 关闭抽屉。**（t2 已落地）**

- **B8 | 表格卡片化逻辑多视图重复** — `DashboardView.vue:506-565`、`TasksView.vue:476-568` 各自内联。**归属：ui-architect**。建议：提炼为共享 `.table-cards` 放 `components.css`。**（t2 已新增模板，供复用）**

- **B9 | MonitorView 栅格 `minmax(340px,1fr)` 超窄屏溢出** — `MonitorView.vue:363-367`。320px 视口横向溢出。**归属：page-fixer-b**。建议：`repeat(auto-fill, minmax(min(340px,100%),1fr))`。

- **B10 | 顶栏「新建任务」移动端恒显占位** — `AppLayout.vue:123`。**归属：ui-architect**。建议：窄屏图标化。**（t2 已落地）**

- **B11 | 弹层/下拉 aria 不全** — `UiModal.vue:42` 缺 `aria-labelledby`；`UiDropdown` 缺键盘导航。**归属：ui-architect**。建议：`useId` 绑定 `aria-labelledby`、菜单方向键可达。**（t2 已加 useId+labelledby）**

- **B12 | TaskDetail 操作区按钮过多，移动端拥挤** — `TaskDetailView.vue:322-347` 最多 8 按钮。**归属：page-fixer-a**。建议：`<767px` 收敛「主要操作 + 更多操作」。

- **B13 | SettingsView 双保存入口 + 分组导航在移动端冗长** — `SettingsView.vue:817-823 / 1128-1136` + `settings-nav` 10 组 chips。**归属：page-fixer-b**。建议：移动端分组导航横向滑动，保留单个保存入口。

### 2.3 低（代码/语义细节）

- **C1 | 死代码/空表达式** — `SettingsView.vue:916` `{{ f.step && ... ? '' : '' }}`。**归属：page-fixer-b**。建议：改为 `{{ form[f.key] }}`。

- **C2 | 令牌错配** — `SettingsView.vue:1450` `.range { accent-color: var(--primary, #4f7cff) }`，`--primary` 不存在。**归属：page-fixer-b**。建议：改用 `var(--accent)`。

- **C3 | 可点击元件非按钮语义** — `MonitorView.vue:228` 用 `<span>` 承载开关（已改 `<button>`）、`DashboardView.vue:218` 用 `tr @click` 导航。**归属：page-fixer-b / page-fixer-a**。建议：改用 `<button>` 或加 `role`+键盘可达。

- **C4 | LoginView 移动端横向 padding 偏大** — `frontend/src/views/LoginView.vue:131` `padding:44px 40px 28px`。**归属：page-fixer-c**。建议：`<=480px` 降 `padding:32px 20px 24px`。

- **C5 | DashboardView 移动端保留内联 `max-width`** — `DashboardView.vue:220` `max-width:380px`。**归属：page-fixer-a**。建议：删除内联宽度，交 `.clamp-2`。

- **C6 | 定时器/事件清理面检查** — 多个视图 `onBeforeUnmount` 清理 `pollTimer/qrTimer/logTimer`。基线已正确，后续改动需保持。

---

## 3. 移动端适配统一规范（供 fixer 执行）

> 与现有设计系统自洽：一律消费 `styles/tokens.css` 的色板/字号/间距/圆角 token 与 `components.css` 类名，不推翻设计语言。

### 3.1 断点（唯一权威，禁止再引入 900/1080/1100/720/560）

| 名称 | 断点 | 语义 | 用途 |
| --- | --- | --- | --- |
| `--bp-xs` | `<=479px` | 小屏手机（375 基准） | 单列堆叠、极窄安全区 |
| `--bp-sm` | `>=480px` | 大屏手机/小平板 | 允许双列 |
| `--bp-md` | `<768px` | 移动端统一分界 | 底部导航 / 卡片化 / 底部抽屉 |
| `--bp-lg` | `768–1023px` | 平板 | 抽屉侧栏 / 双列 |
| `--bp-xl` | `>=1024px` | 桌面 | 固定侧栏 / 多列 |

统一写法：移动端基础样式直接写，或 `@media (max-width:767px)`；平板 `@media (min-width:768px) and (max-width:1023px)`；桌面 `@media (min-width:1024px)`。新增布局 token：`--bottomnav-height: 64px`。

### 3.2 导航策略

- `>=1024px`：固定左栏 `--sidebar-width: 236px`，顶栏无菜单按钮。
- `768–1023px`：侧栏变抽屉（hamburger + 遮罩），顶栏显示菜单按钮。
- `<767px`：**固定底部导航**（`position:fixed; bottom:0`），5 主路由图标+短标签，`height:64px`，`padding-bottom: env(safe-area-inset-bottom)`；内容区 `padding-bottom: 64px + env(safe-area-inset-bottom)`；隐藏侧栏与顶栏菜单按钮；激活项 `--accent` 高亮。
- 抽屉/底部导航均处理：打开时 `body{overflow:hidden}`，`route.path` 变化自动关闭并滚动到顶。

### 3.3 栅格堆叠

| 布局 | 桌面(>=1024) | 平板(768-1023) | 移动(<767) |
| --- | --- | --- | --- |
| KPI/队列（Dashboard） | 4 | 2 | 1 |
| 主从详情（TaskDetail） | `minmax(0,1fr) 340px` | 1 列 | 1 列 |
| 配置表单（MonitorConfig） | 2（末卡跨全宽） | 1 | 1 |
| 设置字段 / grid-2 | 2 | 2 | 1 |
| 监控卡片（monitor-grid） | auto-fill≥340 | auto-fill≥340 | 1 |

统一：`repeat(auto-fill, minmax(min(340px,100%),1fr))`；所有 grid 容器 `<768` 收敛 `grid-template-columns:1fr`；所有 `.flex.gap-*` `<768` 允许 `flex-wrap:wrap`（`components.css` 已提供，保持）。

### 3.4 表格 → 卡片化（统一模板，供所有含 `.table` 视图复用）

在 `components.css` 已新增 `.table-cards`（`@media (max-width:767px)`），规则按 `data-label` 生成列名标签、主列（`data-label="标题"` / `data-label="视频"`）转列向并 `order:-1`、忽略表头、末列 `.ta-right` 顶边分隔。视图接入需：给 `td` 补 `data-label="列名"`，主列 `clamp-1/clamp-2` + `min-width:0`。

### 3.5 触控目标与交互

- 移动端所有可点元素最小 **44×44px**；`.btn-icon` 至少 40px。
- `UiToggle` 移动端开关高度 ≥24px，外层可点 `min-height:44px`。
- `UiPagination` 移动端 `flex-wrap:wrap` 防溢出。
- 下拉/主题菜单移动端贴起点展开，避免被折叠。

### 3.6 弹层（底部抽屉）与安全区

- `UiModal`：`<767px` 贴底抽屉（`align-items:flex-end`、顶部圆角、`max-height:88vh`、脚部按钮全宽 `flex-direction:column`、底部 `env(safe-area-inset-bottom)`）。
- 所有固定层（toast/modal/drawer/bottom-nav）底部感知 `env(safe-area-inset-bottom)`。
- `UiToastHost` 移动端 `left:16px; right:16px; width:auto`。

### 3.7 字号/间距（移动端收敛）

- 页面标题 `--fs-2xl(1.65rem)` `<480px` 降至 `1.35rem`。
- 内容 padding：桌面 `--sp-6`、移动 `--sp-4`；卡片内 padding 桌面 `--sp-5`、移动 `--sp-4`。
- 可访问性：模态/抽屉补 `aria-labelledby`、focus trap、`Esc` 关闭、焦点可达。

---

## 4. 归属与优先级总览

| 优先级 | 事项 | 归属 |
| --- | --- | --- |
| P0 | A1 底部导航 / A4 顶栏收缩 / B5 断点 / B1-B3 / B4 Modal / B6-B8 / B10-B11 触控与弹层 | ui-architect（t2 已落地） |
| P0 | A5 MonitorView 构建阻断 / A2、A3、B9 监控表格卡片化 / B13、C1、C2 Settings | page-fixer-b |
| P1 | B12 TaskDetail 操作区 / C5 Dashboard 内联宽度 | page-fixer-a |
| P1 | C4 Login 内边距 | page-fixer-c |

> 截图建议：本地 `vite dev` 后按 375/768/1440 截图对比；重点复核 Monitor「最近发现」与 MonitorHistory 的 375 横向滚动、AppLayout 375 顶栏拥挤、UiPagination 多页溢出三处。
