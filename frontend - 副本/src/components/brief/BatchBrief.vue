<script setup>
import { computed } from 'vue'

import AppIcon from '../AppIcon.vue'
import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'
import { fmt, muniLabel } from '../../utils/format'

const S = useScenarioStore()

const s = computed(() => S.result.summary)
const gap = computed(() => S.result.fleet_gap)
const hours = computed(() => S.asm.drawdown_hours)

const pts = computed(() =>
  [...S.result.points].sort((a, b) => b.pumps_required - a.pumps_required || b.shortfall_m3 - a.shortfall_m3),
)
const worst = computed(() => pts.value.filter(x => x.line === 3).slice(0, 8))

// 第一道的占比按「时限内排走的水量 / 径流总量」算，与三道防线条同一口径
const pctL1 = computed(() => Math.round((100 * s.value.line1_m3) / (s.value.runoff_volume_m3 || 1)))
const absorbed = computed(() => s.value.line2_m3)
const storagePct = computed(() =>
  s.value.required_storage_m3 > 0 ? Math.min(100, (absorbed.value / s.value.required_storage_m3) * 100) : 100,
)

const muni = computed(() =>
  Object.entries(S.result.by_municipality).sort((a, b) => b[1].pumps_required - a[1].pumps_required),
)

/** 简报顶部的范围条：这份结论覆盖的是哪一片、多少个点。
 *  只在筛过片区时出现 —— 全网批算时它是废话，筛过之后不写清楚则是误导：
 *  同一张简报，18 个点和 501 个点的版式一模一样。 */
const scope = computed(() => {
  const key = S.filters.district[0]
  if (!key) return null
  const row = S.districtRow(key)
  const extra = []
  if (S.filters.municipality.length) extra.push(t('filters.municipality'))
  if (S.filters.criticality.length) extra.push(t('filters.criticality'))
  if (S.filters.root_cause.length) extra.push(t('filters.rootCause'))
  return {
    name: row ? S.districtLabel(row) : key,
    computed: s.value.points_computed,
    extra,
    dropped: row && row.in_coverage < row.count ? { count: row.count, out: row.count - row.in_coverage } : null,
  }
})

const storage = computed(() => (S.meta ? S.meta.storage : null))
</script>

<template>
  <aside class="panel">
    <div style="display: flex; align-items: center; gap: 10px">
      <AppIcon name="orb" :size="20" /><b style="font-size: 20px">{{ t('brief.batchTitle') }}</b>
    </div>

    <div class="content">
      <div style="display: flex; justify-content: space-between; align-items: center">
        <b style="font-size: 14px">{{ t('brief.stressTest', { storm: S.stormLabel }) }}</b>
        <span class="src">v{{ S.inputs.v }}</span>
      </div>

      <div
        v-if="scope"
        style="
          background: rgba(71, 134, 201, 0.12);
          border-left: 3px solid var(--blue);
          padding: 9px 12px;
          border-radius: 6px;
          margin-bottom: 2px;
        "
      >
        <div style="display: flex; justify-content: space-between; gap: 10px">
          <b>{{ t('brief.scopeName', { name: scope.name }) }}</b
          ><span class="l">{{ t('brief.scopeComputed', { n: scope.computed }) }}</span>
        </div>
        <div class="l" style="margin-top: 3px">
          {{ t('brief.scopeNote')
          }}<template v-if="scope.extra.length">{{
            t('brief.scopeExtra', { list: scope.extra.join(' / ') })
          }}</template
          >{{ t('brief.scopeNoteTail')
          }}<template v-if="scope.dropped">{{
            t('brief.scopeDropped', { count: scope.dropped.count, out: scope.dropped.out })
          }}</template>
        </div>
      </div>

      <div class="stat">
        <div style="border-left: 3px solid var(--blue)">
          <div style="display: flex; justify-content: space-between">
            <span v-html="t('brief.l1Title')" /><b>{{ fmt(s.line1_m3) }} m³</b>
          </div>
          <div class="bar" style="background: rgba(71, 134, 201, 0.15)">
            <i :style="{ width: pctL1 + '%', background: 'var(--blue)' }" />
          </div>
          <div class="l">
            <span
              v-html="
                t('brief.l1Body', {
                  h: hours,
                  runoff: fmt(s.runoff_volume_m3),
                  pc: pctL1,
                  n: s.line_counts['1'],
                })
              "
            /><br />
            <span v-html="t('brief.l1Warn', { n: fmt(s.peak_exceeds_capacity), h: hours })" />
          </div>
        </div>

        <div style="border-left: 3px solid var(--green)">
          <div style="display: flex; justify-content: space-between">
            <span v-html="t('brief.l2Title')" /><b>{{ fmt(absorbed) }} / {{ fmt(s.required_storage_m3) }} m³</b>
          </div>
          <div class="bar" style="background: rgba(102, 197, 107, 0.15)">
            <i :style="{ width: storagePct + '%', background: 'var(--green)' }" />
          </div>
          <div class="l">
            <template v-if="!storage">{{ t('brief.l2Loading') }}</template>
            <template v-else>
              <span
                v-html="
                  t('brief.l2Body', {
                    count: S.meta.count,
                    found: fmt(storage.assets_found),
                    measured: storage.measured,
                    assumed: storage.assumed_dimensions,
                  })
                "
              /><br />
              <span
                v-html="
                  t('brief.l2Body2', {
                    noAsset: fmt(storage.no_asset),
                    noCoverage: fmt(storage.no_coverage),
                  })
                "
              />
            </template>
          </div>
        </div>

        <div style="border-left: 3px solid var(--amber)">
          <div style="display: flex; justify-content: space-between">
            <span v-html="t('brief.l3Title')" /><b>{{
              t('brief.l3Value', { pumps: fmt(s.pumps_required), loads: fmt(s.tanker_loads) })
            }}</b>
          </div>
          <div class="l">
            {{
              t('brief.l3Body', {
                pumps: fmt(gap.pumps_on_ledger),
                tankers: fmt(gap.tankers_on_ledger),
              })
            }}<template v-if="gap.pumps_gap > 0"
              ><span style="color: var(--red)">{{ t('brief.l3Gap', { n: fmt(gap.pumps_gap) }) }}</span></template
            ><template v-else>{{ t('brief.l3Ok') }}</template>
          </div>
        </div>
      </div>

      <div>
        <b style="font-size: 14px">{{ t('brief.byMuni') }}</b>
        <div class="rows" style="margin-top: 8px">
          <div v-for="[k, v] in muni" :key="k" class="row">
            <span class="l">{{ t('brief.byMuniRow', { name: muniLabel(k), n: v.hotspots }) }}</span>
            <b>{{ S.pumpBrief(v) }} · {{ fmt(v.shortfall_m3) }} m³</b>
          </div>
        </div>
      </div>

      <div v-if="worst.length">
        <b style="font-size: 14px">{{ t('brief.worstHeading') }}</b>
        <div class="note" style="margin: 6px 0 8px">
          {{
            t('brief.worstNote', {
              n: s.line_counts['3'],
              h: hours,
              v: fmt(s.shortfall_m3),
              shown: worst.length,
            })
          }}
        </div>
        <div
          v-for="x in worst"
          :key="x.uid"
          style="
            margin-bottom: 8px;
            background: rgba(224, 87, 78, 0.1);
            border: 1px solid rgba(224, 87, 78, 0.2);
            padding: 10px 12px;
            border-radius: 6px;
            border-left: 3px solid var(--red);
            cursor: pointer;
          "
          @click="S.select(x.uid)"
        >
          <div style="display: flex; justify-content: space-between; gap: 10px; margin-bottom: 8px">
            <b
              >{{ x.uid }}
              <span class="l" style="font-weight: 400">· {{ S.byUid.get(x.uid).location }}</span></b
            >
            <span class="tag d">{{ t('brief.worstTag', { v: fmt(x.shortfall_m3) }) }}</span>
          </div>
          <div style="display: flex; gap: 8px; margin-bottom: 8px">
            <div style="flex: 1; background: rgba(255, 255, 255, 0.05); padding: 6px; border-radius: 4px; text-align: center">
              <div class="l">{{ t('brief.worstPeak') }}</div>
              <b>{{ fmt(x.peak_flow_m3s, 2) }} m³/s</b>
            </div>
            <div style="flex: 1; background: rgba(255, 255, 255, 0.05); padding: 6px; border-radius: 4px; text-align: center">
              <div class="l">{{ t('brief.worstStorage') }}</div>
              <b>{{ fmt(x.required_storage_m3) }} m³</b>
            </div>
            <div style="flex: 1; background: rgba(255, 255, 255, 0.05); padding: 6px; border-radius: 4px; text-align: center">
              <div class="l">{{ t('brief.worstLedger') }}</div>
              <b>{{ fmt(S.byUid.get(x.uid).pumps_qty) }}</b>
            </div>
          </div>
          <div style="line-height: 1.5">
            <span style="color: var(--amber)" v-html="t('brief.orderLabel')" />
            <span
              v-html="
                t('brief.worstOrder', { brief: S.pumpBrief(x), loads: x.tanker_loads, h: hours })
              "
            />
          </div>
        </div>
      </div>
      <div v-else class="note" style="color: var(--green)">{{ t('brief.noLine3') }}</div>

      <div>
        <b style="font-size: 14px">{{ t('brief.caveatsHeading') }}</b>
        <div class="note" style="margin-top: 6px">
          <template v-for="(x, i) in (S.result.limitations || [])" :key="'l' + i">· {{ x }}<br /></template>
        </div>
        <div class="note" style="margin-top: 6px">
          <template v-for="(x, i) in (S.meta.caveats || [])" :key="'c' + i">· {{ x }}<br /></template>
        </div>
      </div>
    </div>

    <div class="note" style="text-align: center">{{ t('brief.footerComputed') }}</div>
  </aside>
</template>
