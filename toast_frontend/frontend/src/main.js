// Vue 应用入口：创建 App 实例并挂载到 #app 节点
import { createApp } from 'vue'
import './style.css'       // 全局样式（透明背景、禁止文本选择等）
import App from './App.vue'

createApp(App).mount('#app')