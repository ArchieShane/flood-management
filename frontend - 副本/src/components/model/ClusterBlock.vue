<script setup>
/* 选中的那个模型识别片区身上、**计算器用不到但必须看得见**的那些量。

   计算器那几行（A / C / tc / Qcap / 调蓄 → 三道防线）两套点是同一条链，由
   `PointHeader` / `DetailBlock` 照常显示；本块补的是片区独有的两件事：

   1. **二维演算的水力指标** —— 最大水深、分级历时、退水时刻、洼深与洼地库容。
      这是它之所以被识别出来的原因，不看这些就不知道这个「点」是怎么回事。
   2. **汇水区边界的出处** —— 片区的 A 是 D8 汇流实算，台账点是 Voronoi 代理。
      两个数并排摆着，代理偏多少一眼看得出。

   本块**不显示任何计算结论** —— 结论在上面那几块里，两套点同一套口径。 */
import { computed } from 'vue'

import { MECHANISM_COLOR } from '../../constants'
import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'
import { fmt } from '../../utils/format'

const S = useScenarioStore()

const f = computed(() => S.modelSelFeature)
const p = computed(() => (f.value ? f.value.properties : null))
const rec = computed(() => (S.sel ? S.byUid.get(S.sel) : null))
const run = computed(() => (S.model ? S.model.run : null))

const neverDrained = computed(
  () => !!(p.value && run.value && p.value.drain_time_h >= run.value.sim_hours),
)

/** 汇水区边界：D8 实算 vs Voronoi 代理。差多少是本块最该说清的一件事。 */
const boundary = computed(() => {
  const r = rec.value
  if (!r || !r.area_measured_ha) return null
  const d8 = r.area_measured_ha
  const vor = r.area_voronoi_ha
  return {
    d8,
    vor,
    ratio: vor ? vor / d8 : null,
    basis: r.catchment_boundary,
  }
})

const hydro = computed(() => {
  const x = p.value
  if (!x) return []
  return [
    [t('model.rowMaxDepth'), `${fmt(x.max_depth_m, 3)} m`],
    [t('model.rowMeanDepth'), `${fmt(x.mean_max_depth_m, 3)} m`],
    [t('model.rowArea'), `${fmt(x.area_m2 / 1e4, 2)} ha · ${fmt(x.cells)} ${t('model.cells')}`],
    [t('model.rowAreaGe30'), `${fmt(x.area_ge_0_30m_m2 / 1e4, 2)} ha`],
    [t('model.rowPeakTime'), `${fmt(x.peak_time_min)} min`],
    [t('model.rowDur30'), `${fmt(x.dur_ge_0_30m_h, 2)} h`],
    [t('model.rowDur15'), `${fmt(x.dur_ge_0_15m_h, 2)} h`],
    [
      t('model.rowDrain'),
      neverDrained.value
        ? t('model.neverDrained', { h: run.value.sim_hours })
        : `${fmt(x.drain_time_h, 2)} h`,
    ],
    [t('model.rowResid12'), `${fmt(x.depth_12h_m, 3)} m`],
    [t('model.rowResid24'), `${fmt(x.depth_24h_m, 3)} m`],
    [t('model.rowSink'), `${fmt(x.sink_depth_m, 2)} m`],
    [t('model.rowBasin'), `${fmt(x.basin_capacity_m3)} m³`],
    [t('model.rowSwmm'), `${fmt(x.swmm_inflow_m3, 1)} m³ · ${t('model.overRain', { x: fmt(x.swmm_over_rain, 2) })}`],
    [t('model.rowHazard'), `${fmt(x.max_hazard, 2)} · ${fmt(x.max_speed_ms, 2)} m/s`],
  ]
})
</script>

<template>
  <div v-if="p">
    <h3 style="display: flex; align-items: center; gap: 8px">
      <i
        style="width: 9px; height: 9px; border-radius: 50%; flex: none"
        :style="{ background: MECHANISM_COLOR[p.mechanism_key] }"
      />{{ t('model.clusterNo', { n: p.rank }) }}
      <span class="src" style="font-weight: 400">{{ p.mechanism }}</span>
    </h3>

    <!-- 汇水区边界：两套口径并排 -->
    <div v-if="boundary" class="rows" style="margin-bottom: 10px">
      <div class="row">
        <span class="l">{{ t('model.areaD8') }}</span
        ><b>{{ fmt(boundary.d8, 2) }} ha</b>
      </div>
      <div class="row">
        <span class="l">{{ t('model.areaVoronoi') }}</span
        ><b
          >{{ boundary.vor === null ? '—' : fmt(boundary.vor, 2) + ' ha'
          }}<span v-if="boundary.ratio" class="l"> · {{ fmt(boundary.ratio, 2) }}×</span></b
        >
      </div>
      <div class="row">
        <span class="l">{{ t('model.areaBasis') }}</span
        ><span class="src">{{ t(`model.boundary.${boundary.basis || 'unknown'}`) }}</span>
      </div>
    </div>
    <div class="note" style="margin-bottom: 12px">{{ t('model.areaNote') }}</div>

    <!-- 二维演算的水力指标 -->
    <div class="rows">
      <div v-for="([a, b]) in hydro" :key="a" class="row">
        <span class="l">{{ a }}</span><b style="text-align: right">{{ b }}</b>
      </div>
    </div>

    <a
      class="ghost"
      style="margin-top: 8px; text-decoration: none"
      :href="p.gmaps"
      target="_blank"
      rel="noopener noreferrer"
      >{{ t('model.openMaps') }}</a
    >
    <div class="note" style="margin-top: 8px">{{ t('model.popupNote') }}</div>
  </div>
</template>
