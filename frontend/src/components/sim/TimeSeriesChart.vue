<script setup>
/* 一条「随时间变化」的折线卡片：横轴为降雨开始后的小时数，纵轴一个指标；鼠标移上去读各时刻的值，不移动时显示峰值。
   总积水量 / 总积水面积 / 最大积水深度三张图共用（`VolumeCurve.vue` 取一次数据，三份一起传下来）。 */
import { computed, ref } from 'vue'

import { t } from '../../i18n'

const props = defineProps({
  title: { type: String, required: true },
  points: { type: Array, required: true },            // [{ m: 降雨起算分钟, v: 值 }]，已去掉 null
  unit: { type: String, required: true },
  axisY: { type: String, required: true },
  fmt: { type: Function, required: true },            // 读数的格式化
  note: { type: String, default: '' },
  rainMin: { type: Number, default: null },            // 降雨历时（min），给了就画雨停线
})

const W = 960
const HT = 280
const PAD = { l: 78, r: 24, t: 16, b: 42 }
const PW = W - PAD.l - PAD.r
const PH = HT - PAD.t - PAD.b

function niceTicks(max, count = 5) {
  const raw = max / count
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw)
  const top = Math.ceil(max / step) * step
  const out = []
  for (let v = 0; v <= top + step / 2; v += step) out.push(v)
  return { ticks: out, top, step }
}
/** 纵轴刻度：步长 ≥ 1 取整并加千分位，小数量级（km²、m）按步长留位，免得全显示成 0.1 / 0.2 */
const tickLabel = (v, step) => (step >= 1 ? Math.round(v).toLocaleString('en-US') : v.toFixed(Math.min(4, Math.ceil(-Math.log10(step)))))

const peak = computed(() => props.points.reduce((a, p) => (p.v > a.v ? p : a), { m: 0, v: 0 }))
const chart = computed(() => {
  const P = props.points
  if (P.length < 2 || !(peak.value.v > 0)) return null
  const T = P[P.length - 1].m
  const y = niceTicks(peak.value.v)
  const xT = niceTicks(T / 60, 8)
  const x = m => PAD.l + (m / T) * PW
  const yv = v => PAD.t + PH - (v / y.top) * PH
  const line = P.map(p => `${x(p.m).toFixed(1)},${yv(p.v).toFixed(1)}`).join(' ')
  return {
    line,
    area: `${PAD.l},${PAD.t + PH} ${line} ${x(T).toFixed(1)},${PAD.t + PH}`,
    left: y.ticks.map(v => ({ v, y: yv(v), label: tickLabel(v, y.step) })),
    bottom: xT.ticks.filter(h => h * 60 <= T + 1e-6).map(h => ({ h, x: x(h * 60) })),
    rainX: props.rainMin != null && props.rainMin < T ? x(props.rainMin) : null,
    x, y: yv, T,
  }
})

const hover = ref(null)
function onMove(ev) {
  const c = chart.value
  if (!c) return
  const r = ev.currentTarget.getBoundingClientRect()
  const m = ((((ev.clientX - r.left) / r.width) * W - PAD.l) / PW) * c.T
  let best = null
  for (const p of props.points) if (!best || Math.abs(p.m - m) < Math.abs(best.m - m)) best = p
  hover.value = m >= 0 && m <= c.T ? best : null
}
const cur = computed(() => hover.value || peak.value)
const clock = min => `T+${Math.floor(min / 60)}:${String(Math.round(min % 60)).padStart(2, '0')}`
</script>

<template>
  <section v-if="chart" class="sim-card vc">
    <div class="vc-head">
      <span class="vc-title">{{ title }}</span>
      <span class="vc-hover">{{ clock(cur.m) }} · {{ fmt(cur.v) }} {{ unit }}<template v-if="!hover"> ({{ t('sim.detail.volPeak') }})</template></span>
    </div>
    <svg class="vc-svg" :viewBox="`0 0 ${W} ${HT}`" role="img" :aria-label="title" @mousemove="onMove" @mouseleave="hover = null">
      <g v-for="g in chart.left" :key="'g' + g.v">
        <line :x1="PAD.l" :x2="W - PAD.r" :y1="g.y" :y2="g.y" class="vc-grid" />
        <text :x="PAD.l - 8" :y="g.y + 4" text-anchor="end" class="vc-tx">{{ g.label }}</text>
      </g>
      <text v-for="g in chart.bottom" :key="'b' + g.h" :x="g.x" :y="HT - PAD.b + 18" text-anchor="middle" class="vc-tx">{{ g.h }}</text>
      <polygon :points="chart.area" class="vc-fill" />
      <line v-if="chart.rainX != null" :x1="chart.rainX" :x2="chart.rainX" :y1="PAD.t" :y2="PAD.t + PH" class="vc-rain" />
      <text v-if="chart.rainX != null" :x="chart.rainX + 6" :y="PAD.t + 12" class="vc-tx">{{ t('sim.detail.volRainEnd') }}</text>
      <polyline :points="chart.line" class="vc-line" />
      <circle :cx="chart.x(cur.m)" :cy="chart.y(cur.v)" r="4" class="vc-dot" />
      <line :x1="PAD.l" :x2="W - PAD.r" :y1="PAD.t + PH" :y2="PAD.t + PH" class="vc-axis" />
      <text :x="PAD.l + PW / 2" :y="HT - 6" text-anchor="middle" class="vc-tx">{{ t('sim.detail.volAxisX') }}</text>
      <text :transform="`translate(14 ${PAD.t + PH / 2}) rotate(-90)`" text-anchor="middle" class="vc-tx">{{ axisY }}</text>
    </svg>
    <p v-if="note" class="vc-note">{{ note }}</p>
  </section>
</template>

<style>
.vc { padding: 16px 18px 12px; margin-top: 20px; }
.vc-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.vc-title { font-weight: 600; font-size: 15px; }
.vc-hover { margin-left: auto; color: var(--fg-2); font-size: 12px; font-variant-numeric: tabular-nums; }
.vc-svg { width: 100%; height: auto; display: block; margin-top: 6px; }
.vc-svg text { font-size: 12px; }
.vc-grid { stroke: var(--line); }
.vc-axis { stroke: var(--faint); }
.vc-tx { fill: var(--muted); }
.vc-fill { fill: var(--blue); opacity: 0.12; }
.vc-line { fill: none; stroke: var(--blue); stroke-width: 2; stroke-linejoin: round; }
.vc-dot { fill: var(--red); }
.vc-rain { stroke: var(--muted); stroke-dasharray: 4 4; }
.vc-note { color: var(--muted); font-size: 12px; line-height: 16px; margin: 4px 0 0; }
</style>
