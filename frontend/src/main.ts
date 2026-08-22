import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { useThemeStore } from './stores/theme'

// 全局样式（顺序：tokens → base → components）
import './styles/tokens.css'
import './styles/base.css'
import './styles/components.css'
// 本地 vendored 图标字体
import './assets/icons/bootstrap-icons.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)

// 主题初始化（index.html 内联脚本已提前设置，这里补齐系统主题变化监听）
useThemeStore().init()

app.mount('#app')
