<script setup>
/* 全市应对设备配置：L2 之后地表留下的水，按两档分担 ——
   · L2 sugg = 第一档，固定设施（泵站 / 压力管 / 排海管 / 调蓄塘），承担全市总水量的 45%；
   · L3 = 第二档，移动泵与罐车，承担 20%。
   数据由详情页取 `/equipment`（成果目录里的两份设备配置文件）：只有全市总量和数量，没有位置、也不是逐台设备；
   管长、扬程、效率是占位值。放在详情页右栏（420 px 宽），一个场景一张小卡，不画宽表。 */
import { computed } from 'vue'

import { t } from '../../i18n'
import { fmtInt } from '../../utils/sim'
import '../../styles/rda.css'

const props = defineProps({
  data: { type: Object, default: null },     // /equipment 的返回；没有就整块不出现
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

const outfallText = s => {
  const o = s.external_discharge.outfall_pipe
  return o.count ? t('sim.equip.outfall', { d: o.dn_mm, n: o.count, km: n1(o.total_length_km) }) : t('sim.equip.noOutfall')
}
const pondText = s => {
  const p = s.ponds
  return p.count ? t('sim.equip.ponds', { n: p.count, v: wan(p.total_volume_m3), a: n1(p.net_area_ha), g: n1(p.area_with_slopes_roads_ha) }) : t('sim.equip.noPonds')
}
/** 「中型泵（1.47 m³/s）需 46 台（缺 4）」：缺口为 0 就不写缺 */
const pumpText = (key, x, q) => t(`sim.equip.${key}`, { q, n: fmtInt(x.count_needed) }) + (x.additional_needed > 0 ? t('sim.equip.gap', { g: fmtInt(x.additional_needed) }) : '')
</script>

<template>
  <section v-if="data" class="sim-card ro sd-equip">
    <div class="rda-ui">
      <h3>{{ tab === 'fixed' ? t('sim.equip.tabFixed', { p: pct(inp.share_fixed) }) : t('sim.equip.tabMobile', { p: pct(inp.share_mobile) }) }}</h3>
      <p class="muted small">{{ t('sim.equip.sub', { rain: rainLabel }) }}</p>
      <p class="warn small">{{ t('sim.equip.caveat') }}</p>

      <div class="kpis">
        <div v-for="[k, v, p] in budget" :key="k" :class="{ cur: k === (tab === 'fixed' ? 'fixed' : 'mobile') }">
          <b>{{ wan(v) }}</b>
          <span>{{ t(`sim.equip.budget.${k}`) }}{{ p ? ` · ${p}` : '' }}（{{ t('sim.equip.wan') }}）</span>
        </div>
      </div>

      <template v-if="tab === 'fixed'">
        <p class="muted small">{{ t('sim.equip.fixedNote', { n: asFixed.fixed_pump.pumps_per_station, q: asFixed.fixed_pump.unit_flow_m3s }) }}</p>
        <div class="eq-list">
          <div v-for="s in fixedRows" :key="s.id" class="eq-item">
            <div class="eq-h"><b>{{ t('sim.equip.headFixed', { h: s.drain_time_h, e: pct(s.external_share) }) }}</b><em>{{ t('sim.equip.flow', { q: n1(s.total_flow_required_m3s) }) }}</em></div>
            <div>{{ t('sim.equip.stations', { n: s.pump_stations.count, p: s.pump_stations.pumps_total }) }} · {{ t('sim.equip.pipe', { d: s.pressure_pipe.dn_mm, n: s.pressure_pipe.count, km: n1(s.pressure_pipe.total_length_km) }) }}</div>
            <div>{{ outfallText(s) }}</div>
            <div>{{ pondText(s) }}</div>
          </div>
        </div>
        <p class="muted small">{{ t('sim.equip.fixedAssume', {
          od: asFixed.outfall_pipe.dn_mm, ov: asFixed.outfall_pipe.velocity_ms, pv: asFixed.pressure_pipe_velocity_ms,
          vol: wan(asFixed.pond.volume_m3), d: asFixed.pond.depth_m, f: asFixed.pond.freeboard_silt_factor, fp: asFixed.pond.footprint_factor,
          pl: asFixed.pressure_pipe_length_each_m, ol: asFixed.outfall_pipe.length_each_m, h: asFixed.pump_head_m, e: asFixed.pump_efficiency }) }}</p>
      </template>

      <template v-else>
        <p class="muted small">{{ t('sim.equip.mobileNote', { n: asMobile.existing_movable_pumps.count, q: n1(asMobile.existing_movable_pumps.total_flow_m3s) }) }}</p>
        <div class="eq-list">
          <div v-for="s in mobileRows" :key="s.id" class="eq-item">
            <div class="eq-h"><b>{{ t('sim.equip.headMobile', { h: s.drain_time_h, e: pct(s.tanker_share) }) }}</b><em>{{ t('sim.equip.flowPump', { q: n1(s.mobile_pump_flow_required_m3s) }) }}</em></div>
            <div>{{ t('sim.equip.volumes', { a: wan(s.volume_by_mobile_pumps_m3), b: wan(s.volume_by_tankers_m3) }) }}</div>
            <div :class="{ warn: s.mobile_pumps.mobile_median.additional_needed > 0 }">{{ pumpText('median', s.mobile_pumps.mobile_median, asMobile.mobile_pump_units_m3s.mobile_median) }}</div>
            <div :class="{ warn: s.mobile_pumps.mobile_large.additional_needed > 0 }">{{ pumpText('large', s.mobile_pumps.mobile_large, asMobile.mobile_pump_units_m3s.mobile_large) }}</div>
            <div>{{ s.tankers.count ? t('sim.equip.tankers', { n: fmtInt(s.tankers.count), t: s.tankers.trips_each }) : t('sim.equip.noTankers') }}</div>
          </div>
        </div>
        <p class="muted small">{{ t('sim.equip.mobileAssume', {
          c: asMobile.tanker.capacity_m3, r: asMobile.tanker.round_trip_h, hl: asMobile.hose_length_each_m, h: asMobile.pump_head_m, e: asMobile.pump_efficiency }) }}</p>
      </template>
    </div>
  </section>
</template>

<style scoped>
/* 详情页右栏：和 LevelPanel 同一列（.sd-grid > .ro 已给 sticky / 上边距），内容多就在栏内滚 */
.sd-equip { padding: 4px 6px 10px; max-height: calc(100vh - 40px); overflow-y: auto; }
.rda-ui .kpis b { font-size: 17px; }
.rda-ui .kpis > .cur { outline: 1px solid var(--blue); }
.eq-list { display: grid; gap: 8px; margin: 8px 0; }
.eq-item { background: var(--card-2); border-radius: 8px; padding: 8px 10px; font-size: 12.5px; line-height: 1.5; }
.eq-h { display: flex; justify-content: space-between; gap: 8px; margin-bottom: 2px; }
.eq-h em { font-style: normal; color: var(--muted); }
</style>
