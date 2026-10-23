<script setup>
/* 结果地图下方的「积水点」清单（/hotspots，backend sim_c1.extract_hotspots）：交付方指定的热点，
   逐态数取自交付统计值表——口径是「热点汇水区」与「热点 200 m」，不是全域。
   点一行 → 地图飞到该点（emit focus）；非第一态时每个数后面附相对第一态的变化。 */
import { computed } from 'vue'

import { t } from '../../i18n'
import { fmtInt, stateCode } from '../../utils/sim'

const props = defineProps({
  data: { type: Object, required: true },
  state: { type: String, default: null },
  active: { type: String, default: null },
})
const emit = defineEmits(['focus'])

const base = computed(() => props.data.states[0])
const isBase = computed(() => props.state === base.value)
const cur = row => row?.[props.state] || {}

const num = (x, d = 2) => (x == null ? '—' : Number(x).toFixed(d))
/** 相对基线态的变化（同单位、同小数位），没变不写 */
function delta(row, scope, key, d = 2) {
  if (isBase.value) return ''
  const a = row?.[props.state]?.[scope]?.[key]
  const b = row?.[base.value]?.[scope]?.[key]
  if (a == null || b == null) return ''
  const x = +(a - b).toFixed(d)
  const f = v => (d === 0 ? fmtInt(v) : v.toFixed(d))
  return x === 0 ? '' : x > 0 ? `+${f(x)}` : `−${f(-x)}`
}
const unconverged = computed(() => props.data.points.find(p => p.catchment_ha?.unconverged))
</script>

<template>
  <div class="hp">
    <div class="hp-head">
      <div class="bh">{{ t('sim.hotspots.title') }}</div>
      <span class="hp-sum">{{ t('sim.hotspots.lead', { n: data.points.length, state: stateCode(state) }) }}</span>
    </div>
    <div class="hp-scroll">
      <table class="hp-tab">
        <thead>
          <tr>
            <th>{{ t('sim.hotspots.id') }}</th>
            <th class="r">{{ t('sim.hotspots.near') }} (m)</th>
            <th class="r">{{ t('sim.hotspots.a30') }} (ha)</th>
            <th class="r">{{ t('sim.hotspots.vol') }} (m³)</th>
            <th class="r">{{ t('sim.hotspots.at') }} (h)</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in data.points" :key="p.id" :class="{ on: active === p.id }" @click="emit('focus', p.id)">
            <td><b>{{ p.id }}</b><span class="dim"> {{ p.district }}</span></td>
            <td class="r">{{ num(cur(p.stats).near_200m?.max_depth_m) }}<i>{{ delta(p.stats, 'near_200m', 'max_depth_m') }}</i></td>
            <td class="r">{{ num(cur(p.stats).catchment?.area_ge_0_30_ha) }}<i>{{ delta(p.stats, 'catchment', 'area_ge_0_30_ha') }}</i></td>
            <td class="r">{{ cur(p.stats).catchment?.max_volume_m3 == null ? '—' : fmtInt(cur(p.stats).catchment.max_volume_m3) }}<i>{{ delta(p.stats, 'catchment', 'max_volume_m3', 0) }}</i></td>
            <td class="r">{{ num(cur(p.stats).catchment?.max_volume_h) }}</td>
          </tr>
          <tr class="tot">
            <td><b>{{ t('sim.hotspots.total') }}</b></td>
            <td class="r">{{ num(cur(data.total).near_200m?.max_depth_m) }}<i>{{ delta(data.total, 'near_200m', 'max_depth_m') }}</i></td>
            <td class="r">{{ num(cur(data.total).catchment?.area_ge_0_30_ha) }}<i>{{ delta(data.total, 'catchment', 'area_ge_0_30_ha') }}</i></td>
            <td class="r">{{ cur(data.total).catchment?.max_volume_m3 == null ? '—' : fmtInt(cur(data.total).catchment.max_volume_m3) }}<i>{{ delta(data.total, 'catchment', 'max_volume_m3', 0) }}</i></td>
            <td class="r">{{ num(cur(data.total).catchment?.max_volume_h) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="!isBase" class="hp-note">{{ t('sim.hotspots.vsBase', { s: stateCode(base) }) }}；{{ t('sim.hotspots.totalNote') }}</p>
    <p v-else class="hp-note">{{ t('sim.hotspots.totalNote') }}</p>
    <p v-if="unconverged" class="hp-warn">{{ t('sim.hotspots.unconverged', { ha: fmtInt(unconverged.catchment_ha.surface) }) }}</p>
  </div>
</template>

<style scoped>
.hp { margin-top: 16px; border-top: 1px solid var(--line); padding-top: 14px; }
.hp-head { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.hp-head .bh { font-weight: 600; font-size: 15px; }
.hp-sum { color: var(--fg-2); font-size: 13px; }
.hp-scroll { overflow-x: auto; margin-top: 8px; }
.hp-tab { width: 100%; border-collapse: collapse; font-size: 13px; }
.hp-tab th { text-align: left; font-weight: 500; color: var(--muted); padding: 6px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
.hp-tab td { padding: 7px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
.hp-tab .r { text-align: right; font-variant-numeric: tabular-nums; }
.hp-tab tbody tr { cursor: pointer; }
.hp-tab tbody tr:hover, .hp-tab tbody tr.on { background: rgba(255, 255, 255, 0.05); }
.hp-tab tr.tot { cursor: default; background: rgba(255, 255, 255, 0.03); }
.hp-tab i { font-style: normal; color: var(--muted); font-size: 11.5px; margin-left: 6px; }
.dim { color: var(--muted); font-size: 12px; }
.hp-note { color: var(--muted); font-size: 12px; margin: 6px 0 0; }
.hp-warn { color: var(--amber); font-size: 12px; margin: 6px 0 0; }
</style>
