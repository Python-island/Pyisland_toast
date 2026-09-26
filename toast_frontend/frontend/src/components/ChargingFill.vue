<script setup>
import { computed } from 'vue'

// 胶囊背景层只负责电量填充，不另建通知队列或进出场动画。
const props = defineProps({ percent: { type: Number, default: null } })
const level = computed(() => Number.isFinite(props.percent)
  ? Math.max(0, Math.min(100, props.percent)) : null)
const fillStyle = computed(() => {
  const value = level.value ?? 0
  // 低电量红色、中等黄色、良好绿色；同色系渐变避免干扰白色文字。
  const colors = value <= 20 ? ['#b42335', '#d84646']
    : value <= 60 ? ['#886014', '#ac801c'] : ['#12634a', '#208253']
  return { width: `${value}%`, background: `linear-gradient(110deg, ${colors.join(', ')})` }
})
</script>

<template>
  <span class="charging-fill" aria-hidden="true" :style="fillStyle"></span>
</template>

<style scoped>
.charging-fill {
  position: absolute;
  inset: 0 auto 0 0;
  height: 100%;
  pointer-events: none;
  transition: width 0.4s ease;
}
</style>
