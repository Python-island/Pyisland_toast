<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { motion } from 'motion-v'
import { aiBridgeReady } from './bridge.js'
import { EASE } from './tokens.js'

const input = ref(null)
const prompt = ref('')
const messages = ref([])
const scrollArea = ref(null)
let bridge = null

function focusInput() {
  nextTick(() => input.value?.focus())
}

function submit() {
  const value = prompt.value.trim()
  if (!value || !bridge) return
  bridge.submitPrompt(value)
  prompt.value = ''
}

function userActivity() {
  bridge?.userActivity()
}

function updateConversation(payload) {
  try {
    messages.value = JSON.parse(payload)
    nextTick(() => {
      if (scrollArea.value) scrollArea.value.scrollTop = scrollArea.value.scrollHeight
    })
  } catch (error) {
    console.warn('[ai] 无法解析会话：', error)
  }
}

function clearDraft() {
  prompt.value = ''
}

function closePanel() {
  clearDraft()
  bridge?.closePanel()
}

function keydown(event) {
  if (event.key === 'Escape') {
    closePanel()
    return
  }
  if (event.key === 'Enter' && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault()
    submit()
  }
}

onMounted(async () => {
  bridge = await aiBridgeReady
  bridge?.focusRequested?.connect(focusInput)
  bridge?.conversationUpdated?.connect(updateConversation)
  bridge?.panelClosed?.connect(clearDraft)
  bridge?.getConversation?.((payload) => updateConversation(payload))
  window.addEventListener('keydown', keydown)
  focusInput()
})

onBeforeUnmount(() => {
  bridge?.focusRequested?.disconnect(focusInput)
  bridge?.conversationUpdated?.disconnect(updateConversation)
  bridge?.panelClosed?.disconnect(clearDraft)
  window.removeEventListener('keydown', keydown)
})
</script>

<template>
  <main class="panel-stage">
    <section class="panel">
      <header class="panel-header">
        <div class="panel-title">
          <strong>Pyisland AI</strong>
          <span>使用Windows-MCP中工具调用</span>
        </div>
        <button type="button" aria-label="关闭" @click="closePanel">×</button>
      </header>
      <div
        ref="scrollArea"
        class="messages"
        aria-live="polite"
        @pointerdown="userActivity"
        @wheel.passive="userActivity"
      >
        <motion.article
          v-for="(message, index) in messages"
          :key="`${index}-${message.content}`"
          class="message"
          :class="`message--${message.role}`"
          :initial="{ opacity: 0, y: 12 }"
          :animate="{ opacity: 1, y: 0 }"
          :transition="{ duration: 0.28, delay: Math.min(index, 8) * 0.04, ease: EASE }"
        >
          <span>{{ message.role === 'user' ? '你' : 'AI' }}</span>
          <p>{{ message.content }}</p>
        </motion.article>
      </div>
      <form class="composer" @submit.prevent="submit">
        <input
          ref="input"
          v-model="prompt"
          aria-label="询问 Pyisland AI"
          autocomplete="off"
          class="ai-input"
          placeholder="问点什么，按 Enter 发送"
          @input="userActivity"
        />
        <button class="send-button" type="submit" aria-label="发送" :disabled="!prompt.trim()">↵</button>
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
}

.panel-title {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.panel-header strong {
  font-size: 17px;
}

.panel-header span {
  color: rgba(245, 245, 247, 0.48);
  font-size: 12px;
}

.panel-header button {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  margin-left: 16px;
  border: 0;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.08);
  font-size: 22px;
  cursor: pointer;
}


.messages {
  flex: 1;
  min-width: 0;
  padding: 20px 12px 20px 20px;
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(245, 245, 247, 0.35) transparent;
}

.messages::-webkit-scrollbar {
  width: 10px;
  height: 0;
}

.messages::-webkit-scrollbar-button {
  display: none;
  width: 0;
  height: 0;
}

.messages::-webkit-scrollbar-track {
  margin: 8px 0;
  background: transparent;
}

.messages::-webkit-scrollbar-thumb {
  border: 3px solid transparent;
  border-radius: 999px;
  background: rgba(245, 245, 247, 0.28);
  background-clip: padding-box;
}

.messages::-webkit-scrollbar-thumb:hover {
  background: rgba(245, 245, 247, 0.48);
  background-clip: padding-box;
}

.message {
  max-width: 88%;
  min-width: 0;
  margin-bottom: 14px;
  display: grid;
  gap: 5px;
}

.message > span {
  color: rgba(245, 245, 247, 0.5);
  font-size: 11px;
}

.message p {
  margin: 0;
  padding: 11px 14px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.08);
  font-size: 14px;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.message--user {
  margin-left: auto;
  text-align: right;
}

.message--user p {
  background: #d7efff;
  color: #13202b;
}

.composer {
  height: 58px;
  margin: 0 12px 12px;
  padding: 0 10px 0 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.04);
}

.ai-input {
  min-width: 0;
  flex: 1;
  border: 0;
  outline: 0;
  background: transparent;
  color: inherit;
  font-size: 15px;
  line-height: 1;
}

.ai-input::placeholder {
  color: rgba(245, 245, 247, 0.48);
}

.send-button {
  width: 36px;
  height: 36px;
  flex: none;
  border: 0;
  border-radius: 50%;
  background: #f5f5f7;
  color: #1c1c20;
  font-size: 18px;
  cursor: pointer;
}

.send-button:disabled {
  opacity: 0.32;
  cursor: default;
}
</style>
