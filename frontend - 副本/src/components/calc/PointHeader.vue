<script setup>
/* 这个点的台账与实测口径 —— 计算链上游的那几个数，先摆出来。
   `row` 既可以是算过的那一行，也可以是还没算时的默认参数（/api/storm-preset）：
   两者在这几个字段上同名同义，故选完点、还没按计算，这一屏就已经看得全。 */
import { computed } from 'vue'

import BasisTag from './BasisTag.vue'
import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'
import { causeLabel, critLabel, fmt, muniLabel } from '../../utils/format'
import { networkRowHtml } from '../../utils/mapHtml'

const props = defineProps({
  point: { type: Object, required: true },
  row: { type: Object, required: true },
})

const S = useScenarioStore()

const dsLabel = computed(
  () => ((S.curve && S.curve.dataset) || (S.preset && S.preset.dataset) || { label: '—' }).label,
)
const inCov = computed(() =>
  S.preset ? S.preset.in_scope : S.curve ? S.curve.in_scope : props.point.in_coverage,
)

/* 二维演算的积水量。跑过 ANUGA 的片区才有，其余点整行不出 —— 不摆一个 0。
   显示的时限取**片区**共用的那个 T（退水最慢的点定的，Al Bateen 是 19.75 h），
   不取本点自己的退水时刻：三道防线是按同一个 T 排的，两个数混着摆会看岔。 */
const pond = computed(() => S.pondingOf(props.point.uid))
const pondWindowH = computed(() => {
  const d = S.districtPondingOf(props.point.district_key)
  return d ? d.window_h : pond.value && pond.value.drain_h
})
</script>

<template>
  <div>
    <div style="display: flex; justify-content: space-between; gap: 10px; align-items: flex-start">
      <div>
        <b style="font-size: 14px">{{ props.point.uid }}</b>
        <span class="l">· {{ props.point.location }}</span>
        <div class="note" style="margin-top: 2px">
          {{ muniLabel(props.point.municipality) }} · {{ props.point.area }} ·
          {{ t('header.critLabel') }} {{ critLabel(props.point.criticality) }} ·
          {{ causeLabel(props.point.root_cause) }}
        </div>
      </div>
      <span class="tag n" style="cursor: pointer; padding: 4px 8px" @click="S.select(props.point.uid, false)">{{
        t('header.switchPoint')
      }}</span>
    </div>

    <div class="rows" style="margin-top: 9px">
      <div class="row">
        <span class="l">{{ t('header.rowNetwork') }}</span><b v-html="networkRowHtml(props.point)" />
      </div>
      <div class="row">
        <span class="l" v-html="t('header.rowQcap')" />
        <b>{{ fmt(props.row.qcap_m3s, 2) }} m³/s <BasisTag kind="qcap" :basis="props.row.qcap_basis" /></b>
      </div>
      <div class="row">
        <span class="l">{{ t('header.rowStorage') }}</span>
        <b
          >{{ fmt(props.row.pond_available_m3) }} m³
          <BasisTag kind="storage" :basis="props.row.storage_basis"
        /></b>
      </div>
      <div class="row">
        <span class="l" v-html="t('header.rowProfile')" />
        <b
          >{{ fmt(props.row.area_ha, 1) }} ha · {{ fmt(props.row.c_adjusted, 2) }} ·
          {{ fmt(props.row.tc_min, 0) }} min
          <BasisTag kind="catchment" :basis="props.row.catchment_basis"
        /></b>
      </div>
      <div class="row">
        <span class="l">{{ t('header.rowElevation') }}</span>
        <b>{{ props.point.elevation_m === null ? '—' : `${fmt(props.point.elevation_m, 1)} m · ${dsLabel}` }}</b>
      </div>
      <div v-if="pond" class="row">
        <span class="l">{{ t('header.rowPonding', { h: pondWindowH }) }}</span>
        <b
          >{{ fmt(pond.total_m3) }} m³
          <BasisTag kind="ponding" :basis="pond.basis"
        /></b>
      </div>
      <div class="row">
        <span class="l">{{ t('header.rowLedger') }}</span>
        <b>{{
          t('header.ledgerFmt', {
            pumps: fmt(props.point.pumps_qty),
            tankers: fmt(props.point.tankers_qty),
          })
        }}</b>
      </div>
    </div>

    <div v-if="pond" class="note" style="margin-top: 6px">
      {{
        pond.total_m3
          ? t('ponding.pointNote', {
              rp: pond.rp,
              dh: fmt(pond.drain_h, 2),
              peak: fmt(pond.peak_m3),
            })
          : t('ponding.pointNoteDry', { rp: pond.rp })
      }}
    </div>

    <div
      v-if="!inCov"
      class="note warn"
      style="margin-top: 8px; border-left: 2px solid var(--amber); padding-left: 8px"
      v-html="t('header.outOfCoverage')"
    />
  </div>
</template>
