<script setup>
import { ref, shallowRef, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { motion, AnimatePresence } from 'motion-v'
import { bridgeReady } from './bridge.js'
import { playLottie } from './icons.js'

const EASE = [0.22, 1, 0.36, 1]

// 跑马灯速度按像素计算，保证长文本以稳定速度滚动。
const MARQUEE_GAP = 48
const MARQUEE_SPEED = 70

// 这些时间需要和下方 Motion 进出场动画保持一致。
const ENTER_MEASURE_DELAY = 950
const EXIT_CLEANUP_DELAY = 450

// 队列项需要保持原始对象引用，供异步图标加载完成后做过期判断。
const current = shallowRef(null)
const visible = ref(false)
const scrolling = ref(false)
const scrollDuration = ref(8)
const iconMode = ref('none')
const staticText = ref(null)
const lottieContainer = ref(null)
const queue = []
let timer = null
let hideTimer = null
let measureTimer = null
let iconTimer = null
let lottieInstance = null
let bridge = null

function destroyLottie() {
  // Lottie 会持有 DOM 节点和 requestAnimationFrame 句柄。
  // toast 离场或新图标替换旧图标时，需要主动销毁。
  if (lottieInstance) {
    lottieInstance.destroy()
    lottieInstance = null
  }
}

function dismiss() {
  // 关闭时先只修改可见性，等出场动画完成后再真正清空当前项。
  // 这样 AnimatePresence 才能渲染收缩消失动画。
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
  if (measureTimer) {
    clearTimeout(measureTimer)
    measureTimer = null
  }
  if (iconTimer) {
    clearTimeout(iconTimer)
    iconTimer = null
  }
  visible.value = false
  hideTimer = setTimeout(() => {
    destroyLottie()
    current.value = null
    processQueue()
  }, EXIT_CLEANUP_DELAY)
}

function measureOverflow() {
  // 胶囊展开后再检测文本是否溢出，必要时切换为跑马灯。
  const content = staticText.value
  const host = content && content.parentElement
  if (!host || !content) return
  const itemWidth = content.offsetWidth
  if (itemWidth > host.clientWidth + 2) {
    scrollDuration.value = (itemWidth + MARQUEE_GAP) / MARQUEE_SPEED
    scrolling.value = true
  }
}

async function setupIcon(item) {
  // 图标加载是异步的，可能在 toast 已切换后才完成。
  // 写入结果前检查 current.value，避免过期结果污染当前 toast。
  await nextTick()
  const container = lottieContainer.value
  if (!container || !item.type) return
  destroyLottie()
  try {
    const animation = await playLottie(container, item.type)
    if (current.value !== item) {
      animation?.destroy()
      return
    }
    lottieInstance = animation
    iconMode.value = animation ? 'lottie' : 'default'
  } catch (error) {
    console.warn('[toast] failed to play lottie:', error)
    if (current.value === item) {
      iconMode.value = 'default'
    }
  }
}

function processQueue() {
  // toast 串行显示。current.value 存在时，说明正在等待当前 toast
  // 完成显示和出场动画。
  if (current.value) return
  const next = queue.shift()
  if (!next) return
  current.value = next
  scrolling.value = false
  destroyLottie()
  iconMode.value = next.icon ? 'image' : next.type ? 'pending' : 'none'
  visible.value = true
  timer = setTimeout(dismiss, next.duration)
  measureTimer = setTimeout(measureOverflow, ENTER_MEASURE_DELAY)
  if (next.type) {
    iconTimer = setTimeout(() => setupIcon(next), 200)
  }
}

function enqueue(message, type = '', duration = 3000, icon = '') {
  // 将桥接层传入的数据规范化为队列项。
  queue.push({ message, type, duration, icon })
  processQueue()
}

onMounted(async () => {
  // QWebChannel 只有在 QtWebEngine 内可用。
  // 普通浏览器预览时回退到独立 demo toast。
  bridge = await bridgeReady
  if (bridge && bridge.toastRequested) {
    bridge.toastRequested.connect((payload) => {
      try {
        const data = JSON.parse(payload)
        enqueue(data.message, data.type || '', data.duration || 3000, data.icon || '')
      } catch (e) {
        enqueue(String(payload))
      }
    })
  }

  if (!bridge) {
    setTimeout(() => enqueue('Standalone preview mode', '', 2500), 300)
    setTimeout(() => enqueue('Connect to PySide6 for live toasts', '', 3500), 3200)
  }
})

onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
  if (hideTimer) clearTimeout(hideTimer)
  if (measureTimer) clearTimeout(measureTimer)
  if (iconTimer) clearTimeout(iconTimer)
  destroyLottie()
})
</script>

<template>
  <div class="stage">
    <AnimatePresence>
      <motion.div
        v-if="current && visible"
        key="snackbar"
        class="snackbar"
        :class="[{ 'snackbar--scrolling': scrolling }, `snackbar--icon-${iconMode}`]"
        role="status"
        aria-live="polite"
        :initial="{ width: '48px', scale: 0.5, opacity: 0 }"
        :animate="{
          width: ['48px', 'auto'],
          scale: [0.5, 1.1, 1],
          opacity: 1,
        }"
        :transition="{
          width: { duration: 0.75, ease: EASE, delay: 0.1 },
          scale: { duration: 0.55, ease: EASE, times: [0, 0.55, 1] },
          opacity: { duration: 0.15 },
        }"
        :exit="{
          width: '48px',
          scale: 0.7,
          opacity: 0,
          transition: { duration: 0.4, ease: EASE },
        }"
      >
        <span v-if="iconMode !== 'none'" class="snackbar__icon">
          <img
            v-if="iconMode === 'image'"
            class="snackbar__image"
            :src="current.icon"
            alt=""
          />
          <span v-else ref="lottieContainer" class="snackbar__lottie"></span>
          <svg
            v-if="iconMode === 'default'"
            class="snackbar__default-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
            <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
          </svg>
        </span>
        <motion.span
          class="snackbar__text"
          :initial="{ opacity: 0 }"
          :animate="{ opacity: 1, transition: { duration: 0.24, delay: 0.48, ease: 'easeOut' } }"
          :exit="{ opacity: 0, transition: { duration: 0.12 } }"
        >
          <span v-if="!scrolling" ref="staticText" class="text-static">{{ current.message }}</span>
          <span
            v-else
            class="marquee-track"
            :style="{ animationDuration: `${scrollDuration}s` }"
          >
            <span class="marquee-item">{{ current.message }}</span>
            <span class="marquee-item" aria-hidden="true">{{ current.message }}</span>
          </span>
        </motion.span>
      </motion.div>
    </AnimatePresence>
  </div>
</template>

<style scoped>
.stage {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
}

.snackbar {
  height: 48px;
  padding: 12px 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border-radius: 9999px;
  background: rgba(28, 28, 32, 0.92);
  color: #f5f5f7;
  font-size: 15px;
  line-height: 1.4;
  letter-spacing: 0.1px;
  white-space: nowrap;
  overflow: hidden;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

.snackbar--icon-none {
  gap: 0;
}

.snackbar__icon {
  position: relative;
  width: 26px;
  height: 26px;
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.snackbar__lottie {
  position: absolute;
  inset: 0;
}

.snackbar__lottie svg {
  width: 100%;
  height: 100%;
}

.snackbar__image {
  width: 24px;
  height: 24px;
  object-fit: contain;
}

.snackbar__default-icon {
  width: 17px;
  height: 17px;
  color: #f5f5f7;
}

.snackbar__text {
  position: relative;
  max-width: 320px;
  display: inline-flex;
  overflow: hidden;
  text-overflow: ellipsis;
}

.text-static {
  white-space: nowrap;
}

.snackbar--scrolling .snackbar__text {
  -webkit-mask-image: linear-gradient(
    to right,
    transparent,
    #000 24px,
    #000 calc(100% - 24px),
    transparent
  );
  mask-image: linear-gradient(
    to right,
    transparent,
    #000 24px,
    #000 calc(100% - 24px),
    transparent
  );
}

.marquee-track {
  display: inline-flex;
  flex: none;
  white-space: nowrap;
  animation-name: marquee;
  animation-timing-function: linear;
  animation-delay: 0.6s;
  animation-iteration-count: infinite;
}

.marquee-item {
  flex: none;
  padding-right: 48px;
}

@keyframes marquee {
  from {
    transform: translateX(0);
  }
  to {
    transform: translateX(-50%);
  }
}
</style>
