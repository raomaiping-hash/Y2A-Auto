# Y2A-Auto 控制台（前端 SPA）

Vue 3 + Vite + TypeScript 单页应用，提供 Y2A-Auto 的 Web 管理控制台（深色仪表盘风格）。
构建产物由 Flask 托管在 `/ui/` 路径下，数据通过 `/api/v1` JSON API 获取。

## 技术栈

- **Vue 3**（`<script setup>` SFC）+ **Vite** + **TypeScript**
- **Vue Router**（History 模式，base `/ui/`）、**Pinia**（状态管理）
- **手写设计系统**：CSS 变量 tokens（`src/styles/tokens.css`）+ 基础样式（`base.css`）+ 组件类（`components.css`），不依赖 UI 框架
- **图标**：bootstrap-icons 字体（本地 vendored，`src/assets/icons/`，离线可用）

## 目录结构

```text
frontend/
├── index.html                 # 入口 HTML（favicon、挂载点）
├── vite.config.ts             # base=/ui/，dev 代理 /api → 127.0.0.1:5000
└── src/
    ├── main.ts                # 应用入口（样式 + Pinia + Router）
    ├── App.vue
    ├── api/                   # 后端接口层
    │   ├── client.ts          # fetch 封装（CSRF 头、401 处理、SSE）
    │   ├── endpoints.ts       # /api/v1 端点定义
    │   └── types.ts           # 与后端对齐的类型
    ├── stores/                # Pinia：auth / tasks / toast
    ├── composables/           # taskMeta（状态文案/色调、时间解析）
    ├── router/index.ts        # 路由 + 登录守卫
    ├── layouts/AppLayout.vue  # 侧边栏 + 顶栏外壳（含 SSE 连接）
    ├── components/ui/         # 手写 UI 组件库（Modal/Toast/Badge/…）
    ├── views/                 # 页面：登录/仪表盘/任务/审核/设置/监控
    └── styles/                # tokens.css / base.css / components.css
```

## 开发

```bash
# 安装依赖（环境若设置了 NODE_ENV=production，需显式包含 dev 依赖）
npm install --include=dev

# 启动 dev server（代理 /api 到本地 Flask，http://localhost:5173/ui/）
npm run dev

# 类型检查 + 生产构建（输出 dist/，由 Flask /ui 路由托管）
npm run build
```

> dev server 只代理 `/api`，页面访问请用 `http://localhost:5173/ui/`；
> 若直接由 Flask 托管（`python app.py` 后访问 `http://127.0.0.1:5000/ui/`），
> 修改源码后需先 `npm run build` 并刷新页面。

## 与后端约定

- 所有请求走 `/api/v1`（见根目录 `modules/api_v1.py`），统一返回 `{ success, message, ... }`
- 变更类请求（POST/PUT/PATCH/DELETE）必须携带 `X-CSRF-Token` 头（由 `/api/v1/auth/session` 或 `/api/v1/settings` 下发）
- 会话认证沿用 Flask session；401 时全局事件 `auth:unauthorized` 会触发跳转登录页
- 任务实时更新走 SSE：`/api/v1/tasks/stream`（`task_added`/`task_updated`/`task_progress`/`task_deleted`/`tasks_cleared`）
- 数据库时间字段为 UTC 无时区字符串，前端统一用 `parseDbTime`/`formatRelativeTime`/`formatDbTime`（`src/composables/taskMeta.ts`）解析显示

## 组件约定

- 颜色/间距/字号只消费 `tokens.css` 中的 CSS 变量，不写死色值
- 通用 UI 组件放 `components/ui/`，页面私有样式用 `<style scoped>`
- 用户提示统一走 `useToastStore()`（success/error/warning/info），危险操作必须用 `UiConfirm` 二次确认

## 主题（深色 / 浅色 / 跟随系统）

- 三种模式由 `stores/theme.ts` 管理，持久化在 `localStorage['y2a-theme']`，默认深色
- 实现机制：`document.documentElement.dataset.theme = 'dark' | 'light'`，`tokens.css` 中
  `:root, [data-theme='dark']` 为深色令牌，`[data-theme='light']` 覆盖颜色类令牌（字体/间距/布局共用）
- `index.html` 内联脚本在首帧前设置主题避免闪烁；「跟随系统」通过 `prefers-color-scheme` 监听实时切换
- 切换入口：顶栏右侧主题按钮（`components/ui/ThemeSwitcher.vue`）
- 新增样式时禁止写死颜色；半透明派生色用 `color-mix(in srgb, var(--xxx) N%, transparent)`
