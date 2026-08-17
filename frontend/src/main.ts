import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'

// 全局样式（顺序：tokens → base → components）
import './styles/tokens.css'
import './styles/base.css'
import './styles/components.css'
// 本地 vendored 图标字体
import './assets/icons/bootstrap-icons.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
