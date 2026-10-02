<script setup>
/* 各重现期一条堆叠条：管网排走 / 调蓄吸收 / 留给车队，同一基准可横向比。
   基准取「三段之和」的最大值 —— 第二、三道带淤积裕量，和会略大于径流总量，
   拿径流总量当基准会把最不利那条截掉一截。 */
import { computed } from 'vue'

import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'
import { fmt } from '../../utils/format'

const props = defineProps({ rows: { type: Array, required: true } })
const S = useScenarioStore()

const max = computed(() =>
  Math.max(1, ...props.rows.map(r => r.network_drained_m3 + r.storage_used_m3 + r.shortfall_m3)),
)
const w = v => Math.max(0, (100 * v) / max.value)
const rpShort = r =>
  r.return_period_yr ? t('point.rpShortYears', { n: r.return_period_yr }) : t('point.rpShortCustom')
</script>

<template>
  <div
    v-for="r in props.rows"
    :key="r.return_period_yr"
    style="margin-bottom: 8px; cursor: pointer"
    @click="S.setCurveRp(r.return_period_yr)"
  >
    <div style="display: flex; justify-content: space-between; gap: 8px">
      <span :class="{ l: r.return_period_yr !== S.curveRp }">{{ rpShort(r) }}</span>
      <span class="l"
        >{{ fmt(r.runoff_volume_m3) }} m³<template v-if="r.shortfall_m3 > 0">
          ·
          <span style="color: var(--amber)">{{ t('curve.pending') }} {{ fmt(r.shortfall_m3) }}</span></template
        ></span
      >
    </div>
    <div
      class="bar"
      style="margin-top: 4px"
      :style="
        r.return_period_yr === S.curveRp
          ? { outline: '1px solid rgba(255,255,255,.35)', outlineOffset: '1px' }
          : null
      "
    >
      <i :style="{ left: 0, width: w(r.network_drained_m3) + '%', background: 'var(--blue)' }" />
      <i
        :style="{
          left: w(r.network_drained_m3) + '%',
          width: w(r.storage_used_m3) + '%',
          background: 'var(--green)',
        }"
      />
      <i
        :style="{
          left: w(r.network_drained_m3) + w(r.storage_used_m3) + '%',
          width: w(r.shortfall_m3) + '%',
          background: 'var(--amber)',
        }"
      />
    </div>
  </div>
</template>
