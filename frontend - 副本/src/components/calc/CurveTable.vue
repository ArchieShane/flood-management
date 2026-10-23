<script setup>
import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'
import { fmt } from '../../utils/format'

const props = defineProps({ rows: { type: Array, required: true } })
const S = useScenarioStore()

const rpShort = r =>
  r.return_period_yr ? t('point.rpShortYears', { n: r.return_period_yr }) : t('point.rpShortCustom')
</script>

<template>
  <table class="curve">
    <thead>
      <tr>
        <th>{{ t('curve.rp') }}</th>
        <th class="r">{{ t('curve.intensity') }}<br /><span class="note">mm/h</span></th>
        <th class="r">{{ t('curve.peak') }}<br /><span class="note">m³/s</span></th>
        <th class="r">{{ t('curve.runoff') }}<br /><span class="note">m³</span></th>
        <th class="r">{{ t('curve.shortfall') }}<br /><span class="note">m³</span></th>
        <th>{{ t('curve.verdict') }}</th>
      </tr>
    </thead>
    <tbody>
      <tr
        v-for="r in props.rows"
        :key="r.return_period_yr"
        :class="{ on: r.return_period_yr === S.curveRp }"
        @click="S.setCurveRp(r.return_period_yr)"
      >
        <td><b>{{ rpShort(r) }}</b></td>
        <td class="r">{{ fmt(r.intensity_mm_hr, 1) }}</td>
        <td class="r">{{ fmt(r.peak_flow_m3s, 2) }}</td>
        <td class="r">{{ fmt(r.runoff_volume_m3) }}</td>
        <td class="r">
          <span v-if="r.shortfall_m3 > 0" style="color: var(--amber)">{{ fmt(r.shortfall_m3) }}</span>
          <template v-else>—</template>
        </td>
        <td>
<!-- line 为 null = 没跑过二维演算。必须先判它 —— 落到下面的 v-else
               会把「没算」显示成「需出动车队」，那是最糟糕的一种错 -->
          <span v-if="r.line === null" class="tag l">{{ t('curve.tagNone') }}</span>
          <span v-else-if="r.line === 1" class="tag b">{{ t('curve.tagLine1') }}</span>
          <span v-else-if="r.line === 2" class="tag s">{{ t('curve.tagLine2') }}</span>
          <span v-else class="tag d">{{ S.pumpBrief(r) }}</span>
        </td>
      </tr>
    </tbody>
  </table>
</template>
