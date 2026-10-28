<script setup>
/* 全市应对设备配置：L2 之后地表留下的水，按两档分担 ——
   · L2 sugg 页签 = 第一档，固定设施（泵站 / 压力管 / 排海管 / 调蓄塘），承担全市总水量的 45%；
   · L3 页签 = 第二档，移动泵与罐车，承担 20%。
   数据取 `/equipment`（成果目录里的两份设备配置文件）：只有全市总量和数量，没有位置、也不是逐台设备；
   管长、扬程、效率是占位值。没有这份数据的任务接口 404，本块整块不出现。 */
import { computed } from 'vue'

import { t } from '../../i18n'
import { fmtInt } from '../../utils/sim'
import '../../styles/rda.css'

const props = defineProps({
  data: { type: Object, default: null },     // /equipment 的返回（由详情页取）；没有就整块不出现
  tab: { type: String, default: 'fixed' },   // 'fixed' = L2 sugg 固定设施，'mobile' = L3 移动泵与罐车；由右上角的 L2 sugg / L3 按钮切
  rainLabel: { type: String, default: '' },
})

const n1 = v => (v == null ? '—' : Number(v).toLocaleString('en-US', { maximumFractionDigits: 1 }))
const wan = v => (v == null ? '—' : n1(Number(v) / 1e4))
const pct = v => `${Math.round(Number(v) * 100)}%`

const inp = computed(() => props.data?.fixed.inputs || {})
const budget = computed(() => {
  const i = inp.value
  return [
    ['total', i.total_water_m3, ''],
    ['retained', i.L2_surface_retained_5h_m3, `${n1(i.L2_surface_retained_pct_of_total)}%`],
    ['fixed', i.volume_fixed_m3, pct(i.share_fixed)],
    ['mobile', i.volume_mobile_m3, pct(i.share_mobile)],
    ['unassigned', i.unassigned_m3, ''],
  ]
})

const asFixed = computed(() => props.data?.fixed.assumptions || {})
const fixedRows = computed(() => (props.data?.fixed.scenarios || [])
  .slice().sort((a, b) => a.drain_time_h - b.drain_time_h || b.external_share - a.external_share))
const asMobile = computed(() => props.data?.mobile.assumptions || {})
const mobileRows = computed(() => (props.data?.mobile.scenarios || [])
  .slice().sort((a, b) => b.drain_time_h - a.drain_time_h || a.tanker_share - b.tanker_share))

/** 「需要 n（缺 m）」：缺口为 0 就只写需要数 */
const need = x => (x.additional_needed > 0 ? t('sim.equip.needGap', { n: fmtInt(x.count_needed), g: fmtInt(x.additional_needed) }) : fmtInt(x.count_needed))
</script>

<template>
  <section v-if="data" class="sim-card sd-rda sd-equip">
    <div class="rda-ui">
      <h3>{{ t('sim.equip.title') }}</h3>
      <p class="muted small">{{ t('sim.equip.sub', { rain: rainLabel }) }}</p>
      <p class="warn small">{{ t('sim.equip.caveat') }}</p>

      <div class="kpis three">
        <div v-for="[k, v, p] in budget" :key="k">
          <b>{{ wan(v) }}</b>
          <span>{{ t(`sim.equip.budget.${k}`) }}{{ p ? ` · ${p}` : '' }}（{{ t('sim.equip.wan') }}）</span>
        </div>
      </div>

      <div v-if="tab === 'fixed'" class="pane">
        <h4>{{ t('sim.equip.tabFixed', { p: pct(inp.share_fixed) }) }}</h4>
        <p class="muted small">{{ t('sim.equip.fixedNote', { n: asFixed.fixed_pump.pumps_per_station, q: asFixed.fixed_pump.unit_flow_m3s }) }}</p>
        <div class="dev-scroll">
          <table class="tbl small-t">
            <thead>
              <tr>
                <th>{{ t('sim.equip.col.drain') }}</th><th>{{ t('sim.equip.col.ext') }}</th><th>{{ t('sim.equip.col.flow') }}</th>
                <th>{{ t('sim.equip.col.stations') }}</th><th>{{ t('sim.equip.col.pumps') }}</th><th>{{ t('sim.equip.col.pipe') }}</th>
                <th>{{ t('sim.equip.col.outfall') }}</th><th>{{ t('sim.equip.col.pond') }}</th><th>{{ t('sim.equip.col.area') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in fixedRows" :key="s.id">
                <td>{{ s.drain_time_h }} h</td><td>{{ pct(s.external_share) }}</td><td>{{ n1(s.total_flow_required_m3s) }}</td>
                <td>{{ s.pump_stations.count }}</td><td>{{ s.pump_stations.pumps_total }}</td>
                <td>DN{{ s.pressure_pipe.dn_mm }} × {{ s.pressure_pipe.count }}（{{ n1(s.pressure_pipe.total_length_km) }} km）</td>
                <td>{{ s.external_discharge.outfall_pipe.count ? `DN${s.external_discharge.outfall_pipe.dn_mm} × ${s.external_discharge.outfall_pipe.count}（${n1(s.external_discharge.outfall_pipe.total_length_km)} km）` : '—' }}</td>
                <td>{{ s.ponds.count ? t('sim.equip.pondCell', { n: s.ponds.count, v: wan(s.ponds.total_volume_m3) }) : '—' }}</td>
                <td>{{ s.ponds.count ? t('sim.equip.areaCell', { a: n1(s.ponds.net_area_ha), g: n1(s.ponds.area_with_slopes_roads_ha) }) : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="muted small">{{ t('sim.equip.fixedAssume', {
          od: asFixed.outfall_pipe.dn_mm, ov: asFixed.outfall_pipe.velocity_ms, pv: asFixed.pressure_pipe_velocity_ms,
          vol: wan(asFixed.pond.volume_m3), d: asFixed.pond.depth_m, f: asFixed.pond.freeboard_silt_factor, fp: asFixed.pond.footprint_factor,
          pl: asFixed.pressure_pipe_length_each_m, ol: asFixed.outfall_pipe.length_each_m, h: asFixed.pump_head_m, e: asFixed.pump_efficiency }) }}</p>
      </div>

      <div v-else class="pane">
        <h4>{{ t('sim.equip.tabMobile', { p: pct(inp.share_mobile) }) }}</h4>
        <p class="muted small">{{ t('sim.equip.mobileNote', { n: asMobile.existing_movable_pumps.count, q: n1(asMobile.existing_movable_pumps.total_flow_m3s) }) }}</p>
        <div class="dev-scroll">
          <table class="tbl small-t">
            <thead>
              <tr>
                <th>{{ t('sim.equip.col.drain') }}</th><th>{{ t('sim.equip.col.tanker') }}</th><th>{{ t('sim.equip.col.volPump') }}</th>
                <th>{{ t('sim.equip.col.volTanker') }}</th><th>{{ t('sim.equip.col.flowPump') }}</th>
                <th>{{ t('sim.equip.col.median', { q: asMobile.mobile_pump_units_m3s.mobile_median }) }}</th>
                <th>{{ t('sim.equip.col.large', { q: asMobile.mobile_pump_units_m3s.mobile_large }) }}</th>
                <th>{{ t('sim.equip.col.tankers') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in mobileRows" :key="s.id">
                <td>{{ s.drain_time_h }} h</td><td>{{ pct(s.tanker_share) }}</td><td>{{ wan(s.volume_by_mobile_pumps_m3) }}</td>
                <td>{{ s.volume_by_tankers_m3 ? wan(s.volume_by_tankers_m3) : '—' }}</td><td>{{ n1(s.mobile_pump_flow_required_m3s) }}</td>
                <td :class="{ warn: s.mobile_pumps.mobile_median.additional_needed > 0 }">{{ need(s.mobile_pumps.mobile_median) }}</td>
                <td :class="{ warn: s.mobile_pumps.mobile_large.additional_needed > 0 }">{{ need(s.mobile_pumps.mobile_large) }}</td>
                <td>{{ s.tankers.count ? t('sim.equip.tankerCell', { n: fmtInt(s.tankers.count), t: s.tankers.trips_each }) : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="muted small">{{ t('sim.equip.mobileAssume', {
          c: asMobile.tanker.capacity_m3, r: asMobile.tanker.round_trip_h, hl: asMobile.hose_length_each_m, h: asMobile.pump_head_m, e: asMobile.pump_efficiency }) }}</p>
      </div>
    </div>
  </section>
</template>
