<script setup>
import { ref, shallowRef, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { motion, AnimatePresence } from 'motion-v'
import { bridgeReady } from './bridge.js'
import { playLottie } from './icons.js'
import ChargingFill from './components/ChargingFill.vue'

const EASE = [0.22, 1, 0.36, 1]   // 自定义缓动曲线，用于进出动画

// 跑马灯速度按像素计算，保证长文本以稳定速度滚动。
const MARQUEE_GAP = 48          // 跑马灯中两段文本之间的间距（像素）
const MARQUEE_SPEED = 70        // 滚动速度（像素/秒）

// 这些时间需要和下方 Motion 进出场动画保持一致。
const ENTER_MEASURE_DELAY = 950  // 入场动画完成后再检测文本溢出的延迟
const EXIT_CLEANUP_DELAY = 450   // 出场动画完成后清理当前 toast 的延迟

// 队列项需要保持原始对象引用，供异步图标加载完成后做过期判断。
const current = shallowRef(null)  // 当前正在显示的 toast（shallowRef 避免深层响应式开销）
const visible = ref(false)        // 当前 toast 是否可见（控制出场动画）
const scrolling = ref(false)      // 文本是否溢出需要跑马灯滚动
const scrollDuration = ref(8)     // 跑马灯滚动一次的时长（秒）
const iconMode = ref('none')      // 图标显示模式：'none' | 'image' | 'lottie' | 'default' | 'pending'
const staticText = ref(null)      // 静态文本 DOM 引用，用于测量是否溢出
const lottieContainer = ref(null) // Lottie 动画容器 DOM 引用
const queue = []                  // toast 队列，串行显示
let timer = null          // 当前 toast 的显示时长定时器
let hideTimer = null      // 出场动画后的清理定时器
let measureTimer = null   // 文本溢出检测定时器
let iconTimer = null      // 图标加载定时器
let lottieInstance = null // 当前 Lottie 动画实例
let bridge = null         // QWebChannel 桥接对象
const presenceKey = ref(0)

function clearToasts() {
  // 手动休眠时立即清空当前项和等待项，不保留出场动画或延迟任务。
  for (const handle of [timer, hideTimer, measureTimer, iconTimer]) clearTimeout(handle)
  timer = hideTimer = measureTimer = iconTimer = null
  queue.length = 0
  destroyLottie()
  presenceKey.value += 1
  visible.value = false
  current.value = null
}

function destroyLottie() {
  // Lottie 会持有 DOM 节点和 requestAnimationFrame 句柄。
  // toast 离场或新图标替换旧图标时，需要主动销毁，避免内存泄漏。
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
    processQueue()   // 处理队列中的下一个 toast
  }, EXIT_CLEANUP_DELAY)
}

function measureOverflow() {
  // 胶囊展开后再检测文本是否溢出，必要时切换为跑马灯。
  const content = staticText.value
  const host = content && content.parentElement
  if (!host || !content) return
  const itemWidth = content.offsetWidth
  // 文本宽度超过容器宽度时，开启跑马灯滚动
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
    // 如果加载期间 toast 已切换，销毁刚加载的动画并放弃
    if (current.value !== item) {
      animation?.destroy()
      return
    }
    lottieInstance = animation
    iconMode.value = animation ? 'lottie' : 'default'
  } catch (error) {
    console.warn('[toast] failed to play lottie:', error)
    if (current.value === item) {
      iconMode.value = 'default'   // 加载失败回退到默认图标
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
  // 根据队列项决定初始图标模式
  iconMode.value = next.icon ? 'image' : next.type ? 'pending' : 'none'
  visible.value = true
  timer = setTimeout(dismiss, next.duration)
  measureTimer = setTimeout(measureOverflow, ENTER_MEASURE_DELAY)
  if (next.type) {
    iconTimer = setTimeout(() => setupIcon(next), 200)  // 延迟加载动画，避场动画冲突
  }
}

function enqueue(message, type = '', duration = 3000, icon = '', variant = 'default', battery = null) {
  // 将桥接层传入的数据规范化为队列项。
  const percent = typeof battery?.percent === 'number' && Number.isFinite(battery.percent)
    ? Math.max(0, Math.min(100, Math.round(battery.percent))) : null
  queue.push({ message, type, duration, icon, variant, battery: { percent } })
  processQueue()
}

onMounted(async () => {
  // QWebChannel 只有在 QtWebEngine 内可用。
  // 普通浏览器预览时回退到独立 demo toast。
  bridge = await bridgeReady
  if (bridge && bridge.toastRequested) {
    bridge.clearRequested.connect(clearToasts)
    // 监听 Python 端通过 toastRequested 信号发来的 JSON 数据
    bridge.toastRequested.connect((payload) => {
      try {
        const data = JSON.parse(payload)
        enqueue(data.message, data.type || '', data.duration || 3000, data.icon || '',
          data.variant || 'default', data.battery)
      } catch (e) {
        enqueue(String(payload))  // 解析失败时把原始字符串当作消息
      }
    })
  }

  if (!bridge) {
    // 浏览器独立预览模式：显示两条 demo toast
    setTimeout(() => enqueue('Standalone preview mode', '', 2500), 300)
    setTimeout(() => enqueue('Connect to PySide6 for live toasts', '', 3500), 3200)
  }
})

onBeforeUnmount(() => {
  bridge?.clearRequested?.disconnect(clearToasts)
  // 组件卸载时清理所有定时器和 Lottie 实例
  if (timer) clearTimeout(timer)
  if (hideTimer) clearTimeout(hideTimer)
  if (measureTimer) clearTimeout(measureTimer)
  if (iconTimer) clearTimeout(iconTimer)
  destroyLottie()
})
</script>

<template>
  <div class="stage">
    <!-- AnimatePresence 负责在 toast 移除时保留 DOM 以播放出场动画 -->
    <AnimatePresence :key="presenceKey">
      <!-- snackbar 胶囊本体：从 48px 圆点展开为自适应宽度的圆角胶囊 -->
      <motion.div
        v-if="current && visible"
        key="snackbar"
        class="snackbar"
        :class="[{ 'snackbar--scrolling': scrolling, 'snackbar--charging': current.variant === 'charging' }, `snackbar--icon-${iconMode}`]"
        role="status"
        aria-live="polite"
        :initial="{ width: '48px', scale: 0.5, opacity: 0 }"
        :animate="{
          width: ['48px', 'auto'],
          scale: [0.5, 1.1, 1],     // 先放大回弹再归位，模拟弹性效果
          opacity: 1,
        }"
        :transition="{
          width: { duration: 0.75, ease: EASE, delay: 0.1 },
          scale: { duration: 0.55, ease: EASE, times: [0, 0.55, 1] },
          opacity: { duration: 0.15 },
        }"
        :exit="{
          width: '48px',           // 出场时收缩回圆点
          scale: 0.7,
          opacity: 0,
          transition: { duration: 0.4, ease: EASE },
        }"
      >
        <!-- 充电胶囊沿用外层动画，背景按电量比例填充，文字在上层显示。 -->
        <ChargingFill v-if="current.variant === 'charging'" :percent="current.battery.percent" />
        <!-- 图标区域：根据 iconMode 渲染图片、Lottie 动画或默认 SVG -->
        <span v-if="iconMode !== 'none'" class="snackbar__icon">
          <img
            v-if="iconMode === 'image'"
            class="snackbar__image"
            :src="current.icon"
            alt=""
          />
          <span v-else ref="lottieContainer" class="snackbar__lottie"></span>
          <!-- 默认图标：一个铃铛 SVG，Lottie 加载失败时使用 -->
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
        <!-- 文本区域：静态文本或跑马灯滚动文本 -->
        <motion.span
          class="snackbar__text"
          :initial="{ opacity: 0 }"
          :animate="{ opacity: 1, transition: { duration: 0.24, delay: 0.48, ease: 'easeOut' } }"
          :exit="{ opacity: 0, transition: { duration: 0.12 } }"
        >
          <!-- 非滚动模式：直接显示文本（同时用于测量宽度） -->
          <span v-if="!scrolling" ref="staticText" class="text-static">{{ current.message }}</span>
          <!-- 滚动模式：两份相同文本首尾相接，通过 translateX(-50%) 实现无缝循环 -->
          <span
            v-else
            class="marquee-track"
            :style="{ animationDuration: `${scrollDuration}s` }"
          >
            <span class="marquee-item">{{ current.message }}</span>
            <span class="marquee-item" aria-hidden="true">{{ current.message }}</span>
          </span>
        </motion.span>
        <motion.span
          v-if="current.variant === 'charging'"
          class="snackbar__battery-level"
          :initial="{ opacity: 0 }"
          :animate="{ opacity: 1, transition: { duration: 0.24, delay: 0.48 } }"
          :exit="{ opacity: 0, transition: { duration: 0.12 } }"
        >{{ current.battery.percent === null ? '电量未知' : `${current.battery.percent}%` }}</motion.span>
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
  position: relative;
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

.snackbar--charging {
  background: rgba(24, 30, 29, 0.96);
}

.snackbar__battery-level {
  position: relative;
  flex: none;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
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
