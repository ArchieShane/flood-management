import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { useScenarioStore } from '../stores/scenario'

/** 三块浮层（计算器侧栏 / 简报侧栏 / 工具条）的横向排布。
 *  原页面是 layout() 一把改 style.right，这里改成随窗宽与开合状态派生。 */
export function useLayout() {
  const S = useScenarioStore()
  const width = ref(window.innerWidth)
  const onResize = () => {
    width.value = window.innerWidth
  }

  onMounted(() => window.addEventListener('resize', onResize))
  onBeforeUnmount(() => window.removeEventListener('resize', onResize))

  // 简报只在够宽的屏上并排显示 —— 两条 420px 侧栏挤在窄屏上就没地图可看了
  const wide = computed(() => width.value >= 1560)
  const showBrief = computed(() => S.brief && wide.value)

  const briefRight = computed(() => (showBrief.value ? '0px' : '-440px'))
  const calcRight = computed(() => (S.panel ? (showBrief.value ? '420px' : '0px') : '-440px'))
  const toolsRight = computed(
    () => (S.panel ? 420 : 0) + (showBrief.value ? 420 : 0) + 16 + 'px',
  )

  return { width, wide, showBrief, briefRight, calcRight, toolsRight }
}
