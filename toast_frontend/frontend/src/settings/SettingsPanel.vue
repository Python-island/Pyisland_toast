<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { settingsBridgeReady } from './bridge.js'

const form = reactive({
  enabled: true,
  base_url: '',
  api_key: '',
  model: '',
  system_prompt: '',
  temperature: 0.7,
  top_p: 1.0,
  max_tokens: 2048,
  timeout_seconds: 60,
})
const showKey = ref(false)
const status = ref('')
const error = ref(false)
const connected = ref(false)
let bridge = null

function applyPayload(payload) {
  const data = JSON.parse(payload)
  Object.assign(form, data)
}

function load() {
  if (!bridge) {
    status.value = '当前没有连接到 Pyisland。'
    error.value = true
    return
  }
  bridge.getSettings((payload) => {
    try {
      applyPayload(payload)
      showKey.value = false
      status.value = ''
      error.value = false
    } catch (loadError) {
      status.value = '无法读取当前设置。'
      error.value = true
      console.warn('[settings] 无法解析设置：', loadError)
    }
  })
}

function startDrag(event) {
  if (event.button !== 0 || event.target.closest('button')) return
  const origin = { x: event.screenX, y: event.screenY }
  function move(ev) {
    const dx = ev.screenX - origin.x
    const dy = ev.screenY - origin.y
    origin.x = ev.screenX
    origin.y = ev.screenY
    if (dx || dy) bridge?.dragBy?.(dx, dy)
  }
  function stop() {
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', stop)
    window.removeEventListener('pointercancel', stop)
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', stop)
  window.addEventListener('pointercancel', stop)
}

function save() {
  if (!bridge) {
    status.value = '当前没有连接到 Pyisland。'
    error.value = true
    return
  }
  status.value = '正在保存…'
  error.value = false
  bridge.saveSettings(JSON.stringify(form), (message) => {
    if (message) {
      status.value = message
      error.value = true
      return
    }
    status.value = '已保存，接下来的对话会使用新配置。'
    error.value = false
  })
}

function closePanel() {
  bridge?.closeWindow()
}

function keydown(event) {
  if (event.key === 'Escape') closePanel()
}

onMounted(async () => {
  bridge = await settingsBridgeReady
  connected.value = !!bridge
  bridge?.reloadRequested?.connect(load)
  window.addEventListener('keydown', keydown)
  load()
})

onBeforeUnmount(() => {
  bridge?.reloadRequested?.disconnect(load)
  window.removeEventListener('keydown', keydown)
})
</script>

<template>
  <main class="panel-stage">
    <section class="panel">
      <header class="panel-header" @pointerdown="startDrag">
        <div class="panel-title">
          <strong>Pyisland 设置</strong>
          <span>模型接口</span>
        </div>
        <button type="button" aria-label="关闭" @click="closePanel">×</button>
      </header>
      <form class="settings-form" @submit.prevent="save">
        <label class="check">
          <input v-model="form.enabled" type="checkbox" />
          <span>启用 AI</span>
        </label>
        <label>
          <span>接口地址</span>
          <input v-model="form.base_url" class="settings-input" autocomplete="off" spellcheck="false" placeholder="https://api.deepseek.com" />
        </label>
        <label>
          <span>密钥</span>
          <span class="secret">
            <input v-model="form.api_key" :type="showKey ? 'text' : 'password'" autocomplete="off" spellcheck="false" />
            <button type="button" @click="showKey = !showKey">{{ showKey ? '隐藏' : '显示' }}</button>
          </span>
        </label>
        <label>
          <span>模型</span>
          <input v-model="form.model" autocomplete="off" spellcheck="false" placeholder="deepseek-flash" />
        </label>
        <label>
          <span>系统提示词</span>
          <textarea v-model="form.system_prompt" rows="4" spellcheck="false" />
        </label>
        <div class="numbers">
          <label>
            <span>温度</span>
            <input v-model.number="form.temperature" type="number" min="0" max="2" step="0.1" />
          </label>
          <label>
            <span>Top P</span>
            <input v-model.number="form.top_p" type="number" min="0" max="1" step="0.1" />
          </label>
          <label>
            <span>最大输出</span>
            <input v-model.number="form.max_tokens" type="number" min="1" max="32768" step="1" />
          </label>
          <label>
            <span>超时（秒）</span>
            <input v-model.number="form.timeout_seconds" type="number" min="1" max="600" step="1" />
          </label>
        </div>
        <p class="hint">接口、密钥和模型都填写后，对话才会真正启用。保存只写入本机配置文件。</p>
        <p class="status" :class="{ 'status--error': error }" role="status">{{ status }}</p>
        <button class="save-button" type="submit" :disabled="!connected">保存</button>
      </form>
    </section>
  </main>
</template>

<style scoped>
.panel-stage {
  width: 100%;
  height: 100%;
  padding: 8px;
}

.panel {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 24px;
  background: rgba(28, 28, 32, 0.95);
  color: #f5f5f7;
  backdrop-filter: blur(16px);
}

.panel-header {
  min-height: 72px;
  padding: 16px 18px 14px 22px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  cursor: grab;
  user-select: none;
}

.panel-title {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.panel-header strong {
  font-size: 17px;
}

.panel-header span,
label > span,
.hint {
  color: rgba(245, 245, 247, 0.48);
  font-size: 12px;
}

.panel-header button,
.secret button {
  border: 0;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  cursor: pointer;
}

.panel-header button {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  margin-left: 16px;
  font-size: 22px;
}

.settings-form {
  min-width: 0;
  min-height: 0;
  flex: 1;
  padding: 16px 18px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(245, 245, 247, 0.35) transparent;
}

.settings-form::-webkit-scrollbar {
  width: 10px;
  height: 0;
}

.settings-form::-webkit-scrollbar-button {
  display: none;
  width: 0;
  height: 0;
}

.settings-form::-webkit-scrollbar-track {
  margin: 8px 0;
  background: transparent;
}

.settings-form::-webkit-scrollbar-thumb {
  border: 3px solid transparent;
  border-radius: 999px;
  background: rgba(245, 245, 247, 0.28);
  background-clip: padding-box;
}

.settings-form::-webkit-scrollbar-thumb:hover {
  background: rgba(245, 245, 247, 0.48);
  background-clip: padding-box;
}

label {
  min-width: 0;
  display: grid;
  gap: 6px;
}

.check {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

input,
textarea {
  width: 100%;
  min-width: 0;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.04);
  color: inherit;
  font: inherit;
  font-size: 14px;
}

input {
  height: 40px;
  padding: 0 12px;
}

textarea {
  padding: 10px 12px;
  resize: none;
  line-height: 1.5;
}

.secret {
  display: flex;
  align-items: center;
  gap: 8px;
}

.secret input {
  flex: 1;
}

.secret button {
  height: 40px;
  padding: 0 12px;
  flex: none;
  color: inherit;
  font-size: 13px;
}

.numbers {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.hint,
.status {
  margin: 0;
}

.status {
  min-height: 18px;
  color: rgba(245, 245, 247, 0.82);
  font-size: 13px;
}

.status--error {
  color: #ffb4b4;
}

.save-button {
  height: 42px;
  border: 0;
  border-radius: 999px;
  background: #f5f5f7;
  color: #1c1c20;
  font-size: 15px;
  cursor: pointer;
}

.save-button:disabled {
  opacity: 0.32;
  cursor: default;
}
</style>