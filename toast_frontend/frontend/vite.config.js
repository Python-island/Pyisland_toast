import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  // 使用相对路径，这样构建产物可以直接以 file:// 协议被 QtWebEngine 加载
  base: './',
  resolve: {
    alias: {
      // 显式指定 Vue 运行时构建（不含模板编译器，体积更小）
      vue: 'vue/dist/vue.runtime.esm-bundler.js',
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  define: {
    // 关闭 Vue Options API 与生产环境 devtools，减小打包体积
    __VUE_OPTIONS_API__: false,
    __VUE_PROD_DEVTOOLS__: false,
    __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: false,
  },
  build: {
    sourcemap: false,               // 不生成 source map，减小体积
    reportCompressedSize: false,    // 不报告压缩后大小，加快构建
    rollupOptions: {
      input: {
        toast: fileURLToPath(new URL('./index.html', import.meta.url)),
        ai: fileURLToPath(new URL('./ai.html', import.meta.url)),
        settings: fileURLToPath(new URL("./settings.html", import.meta.url)),
      },
    },
  },
})
