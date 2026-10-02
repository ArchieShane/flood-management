<script setup>
/* 全域批算：选一场雨，一次扫过筛选范围内的全部点。 */
import { computed } from 'vue'

import AppIcon from '../AppIcon.vue'
import DetailBlock from './DetailBlock.vue'
import FilterChips from './FilterChips.vue'
import InputsBlock from './InputsBlock.vue'
import ModePills from './ModePills.vue'
import PondingCheck from '../model/PondingCheck.vue'
import ModelRunBlock from '../model/ModelRunBlock.vue'
import StormPills from './StormPills.vue'
import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'
import { useToastStore } from '../../stores/toast'
import { fmt } from '../../utils/format'
import { exportBatchCsv } from '../../utils/csv'

const S = useScenarioStore()
const toast = useToastStore()

const s = computed(() => (S.result ? S.result.summary : null))
const gap = computed(() => (S.result ? S.result.fleet_gap : null))
const hours = computed(() => S.asm.drawdown_hours)
/* 时限与周转都是全局的，故「一辆车跑几趟」全网同一个数：为 0 就是整场
   都折不出辆数。此时印「0 辆」会被读成「不需要罐车」，必须换一句话说。 */
const tankerFeasible = computed(() => !!(s.value && s.value.tanker_trips_per_vehicle > 0))

const tot = computed(() => (s.value ? s.value.line1_m3 + s.value.line2_m3 + s.value.line3_m3 || 1 : 1))
const pc = v => Math.round((100 * v) / tot.value)

const ready = computed(() => {
  if (!s.value) return null
  if (s.value.pumps_required === 0) return [t('batch.readyOk'), 's']
  return s.value.pumps_required <= gap.value.pumps_on_ledger
    ? [t('batch.readyCovered'), 'w']
    : [t('batch.readyShort'), 'd']
})

const ranked = computed(() =>
  S.result
    ? [...S.result.points].sort((x, y) => y.pumps_required - x.pumps_required || y.shortfall_m3 - x.shortfall_m3)
    : [],
)

/* 逐点明细按防线分组：先给每组算个数，再只列选中的那一组。 */
const groups = computed(() => {
  // `null` 是第四个档位，不是缺失值 —— 不给它一格，483 个没结论的点只能在
  // 「全部」里混着看，等于把「没算」藏进了列表。
  const n = { 1: 0, 2: 0, 3: 0, none: 0 }
  for (const x of ranked.value) {
    const k = x.line === null ? 'none' : x.line
    n[k] = (n[k] || 0) + 1
  }
  return [
    ['all', t('batch.groupAll', { n: ranked.value.length }), t('batch.groupAllTitle')],
    [1, t('batch.groupL1', { n: n[1] }), t('batch.groupL1Title')],
    [2, t('batch.groupL2', { n: n[2] }), t('batch.groupL2Title')],
    [3, t('batch.groupL3', { n: n[3] }), t('batch.groupL3Title')],
    ['none', t('batch.groupNone', { n: n.none }), t('batch.groupNoneTitle')],
  ]
})

const sorted = computed(() =>
  S.listLine === 'all'
    ? ranked.value
    : S.listLine === 'none'
      ? ranked.value.filter(x => x.line === null)
      : ranked.value.filter(x => x.line === S.listLine),
)
const list = computed(() => sorted.value.slice(0, S.listLimit))

function pickGroup(g) {
  S.listLine = g
  S.listLimit = 12
}

function onExport() {
  const done = exportBatchCsv(S)
  if (done)
    toast.show(
      t('batch.exported', {
        n: done.count,
        lang: t('csv.lang'),
        v: S.inputs.v,
        over: S.overCount ? t('batch.exportedOver', { n: S.overCount }) : '',
      }),
    )
}
</script>

<template>
  <aside class="panel">
    <div style="display: flex; justify-content: space-between; align-items: center">
      <h2>{{ t('batch.title') }}</h2>
      <span style="cursor: pointer" @click="S.panel = false"
        ><AppIcon name="close" :size="16" :opacity="0.55"
      /></span>
    </div>
    <ModePills />
    <div><h3>{{ t('storm.heading') }}</h3><StormPills /></div>

    <div class="content">
      <FilterChips />
      <ModelRunBlock />
      <InputsBlock />
      <button class="cta" :disabled="S.running" @click="S.run()">
        <AppIcon name="play" :size="16" />
        {{ S.running ? t('batch.running') : s ? t('batch.rerun') : t('batch.run') }}
      </button>

      <div v-if="S.running">
        <h3>{{ t('batch.totalsHeading') }}</h3>
        <div class="skel" /><div class="skel" /><div class="skel" /><div class="skel" style="width: 70%" />
        <div class="note" style="margin-top: 8px">
          {{ t('batch.runningNote', { n: S.filtered.length, v: S.inputs.v }) }}
        </div>
      </div>

      <div v-else-if="!s" class="empty">
        <AppIcon name="calc" :size="24" :opacity="0.55" />
        <b>{{ t('batch.emptyTitle') }}</b>
        <div class="note">{{ t('batch.emptyNote') }}</div>
      </div>

      <template v-else>
        <div>
          <h3>{{ t('batch.totalsWith', { storm: S.stormLabel }) }}</h3>
          <div class="rows">
            <div class="row">
              <span class="l">{{ t('batch.rowScoped') }}</span
              ><b>{{ t('batch.rowScopedUnit', { n: fmt(s.hotspots) }) }}</b>
            </div>
            <div class="row">
              <span class="l">{{ t('batch.rowPeak') }}</span><b>{{ fmt(s.peak_flow_m3s, 1) }} m³/s</b>
            </div>
            <div class="row">
              <span class="l">{{ t('batch.rowExcess') }} <span class="l">{{ t('batch.peakBasis') }}</span></span>
              <b :style="{ color: s.excess_flow_m3s ? 'var(--red)' : 'var(--green)' }"
                >{{ fmt(s.excess_flow_m3s, 1) }} m³/s</b
              >
            </div>
            <div class="row">
              <span class="l">{{ t('batch.rowRunoff') }}</span><b>{{ fmt(s.runoff_volume_m3) }} m³</b>
            </div>
            <div class="row">
              <span class="l">{{ t('batch.rowDrained', { h: hours }) }}</span>
              <b style="color: var(--blue)">{{ fmt(s.line1_m3) }} m³</b>
            </div>
            <div class="row">
              <span class="l">{{ t('batch.rowRequiredStorage') }}</span
              ><b>{{ fmt(s.required_storage_m3) }} m³</b>
            </div>
            <div class="row">
              <span class="l">{{ t('batch.rowAvailStorage') }}</span>
              <b
                >{{ fmt(s.available_pond_m3) }} m³ <span class="l">{{ t('batch.noLedgerField') }}</span></b
              >
            </div>
            <div class="row">
              <span class="l">{{ t('batch.rowShortfall', { h: hours }) }}</span>
              <b :style="{ color: s.shortfall_m3 ? 'var(--red)' : 'var(--green)' }">{{ fmt(s.shortfall_m3) }} m³</b>
            </div>
            <div class="row">
              <span class="l">{{ t('batch.rowPumps') }}</span
              ><b style="font-size: 14px">{{ t('batch.pumpsUnit', { n: fmt(s.pumps_required) }) }}</b>
            </div>

            <div v-for="tier in (gap.by_tier || [])" :key="tier.label" class="row">
              <span class="l" style="padding-left: 12px">· {{ tier.label }}</span>
              <b
                :style="{
                  color:
                    (tier.on_fleet_in_scope === null || tier.on_fleet_in_scope === undefined
                      ? tier.gap
                      : tier.gap_in_scope) > 0
                      ? 'var(--red)'
                      : 'var(--green)',
                }"
                >{{ t('batch.pumpsUnit', { n: fmt(tier.required) }) }}
                <span class="l" :title="t('batch.tierTitle')"
                  >{{ t('batch.tierOnFleet', { n: fmt(tier.on_fleet_in_scope) })
                  }}<template v-if="S.inputs.coverageOnly">{{
                    t('batch.tierWhole', { n: fmt(tier.on_fleet) })
                  }}</template></span
                ></b
              >
            </div>

            <!-- 页面上配的车队，够不够。⚠ 与上面的「所需」并列，不是它的替代。
                 读的是**整条链**（泵侧与罐车侧取小）—— 只看泵会把「够用」说反。 -->
            <div class="row">
              <span class="l">{{ t('batch.rowConfigured') }}</span>
              <b
                >{{
                  t(S.pumpUnitFromTiers ? 'batch.configuredUnitTiered' : 'batch.configuredUnit', {
                    n: fmt(gap.pumps_configured),
                    per: fmt(S.asm.pumps_per_point),
                    rate: fmt(S.pumpUnitCapacity),
                    cars: fmt(gap.tankers_configured),
                    perCar: fmt(S.asm.tankers_per_point),
                  })
                }}</b
              >
            </div>
            <div class="row">
              <span class="l" style="padding-left: 12px">· {{ t('batch.rowUnderPumped', { h: hours }) }}</span>
              <b :style="{ color: s.points_under_served ? 'var(--red)' : 'var(--green)' }">{{
                s.points_under_served
                  ? t('batch.underPumpedValue', {
                      n: fmt(s.points_under_served),
                      v: fmt(s.chain_residual_m3),
                      short: fmt(gap.pumps_configured_gap),
                    })
                  : t('batch.underPumpedNone')
              }}</b>
            </div>
            <!-- 其中卡在罐车侧的 —— 这些点再加泵一滴水也多排不出去，要加的是车。
                 这一行是本页最容易被误读的地方的解药，不能省。 -->
            <div v-if="s.points_tanker_bound" class="row">
              <span class="l" style="padding-left: 12px">· {{ t('batch.rowTankerBound') }}</span>
              <b style="color: var(--amber)">{{
                t('batch.tankerBoundValue', {
                  n: fmt(s.points_tanker_bound),
                  per: fmt(s.tankers_per_pump),
                })
              }}</b>
            </div>

            <div class="row">
              <span class="l">{{ t('batch.rowTankerVehicles', { h: hours }) }}</span>
              <!-- 每辆跑 0 趟时**不能印「0 辆」** —— 那会读成「不需要罐车」，
                   而实际含义是「这个时限下罐车根本来不及」。与后端同一口径。 -->
              <b :style="{ color: tankerFeasible ? '' : 'var(--red)' }"
                >{{
                  tankerFeasible
                    ? t('batch.tankerVehicleUnit', { n: fmt(gap.tankers_required) })
                    : t('batch.tankerVehicleNone')
                }}
                <span class="l">{{
                  t('batch.tankerVehicleBasis', {
                    loads: fmt(s.tanker_loads),
                    trips: s.tanker_trips_per_vehicle,
                    fleet: fmt(gap.tankers_on_ledger),
                  })
                }}</span></b
              >
            </div>
            <!-- 按水量算的车数喂不饱按水量算的泵数时，真正要配的是大的那个 -->
            <div v-if="gap.tankers_to_feed_pumps > gap.tankers_required" class="row">
              <span class="l" style="padding-left: 12px">· {{ t('batch.rowTankerFeed') }}</span>
              <b style="color: var(--amber)">{{
                t('batch.tankerFeedValue', {
                  n: fmt(gap.tankers_to_feed_pumps),
                  pumps: fmt(gap.pumps_required),
                  per: fmt(s.tankers_per_pump),
                })
              }}</b>
            </div>
            <!-- 周转比时限还长的点不出辆数 —— 上面那个合计是下限，必须说出来 -->
            <div v-if="s.points_tanker_infeasible" class="row">
              <span class="l" style="padding-left: 12px">· {{ t('batch.rowTankerBlocked') }}</span>
              <b style="color: var(--red)">{{
                t('batch.tankerBlockedValue', { n: fmt(s.points_tanker_infeasible) })
              }}</b>
            </div>
            <div class="row">
              <span class="l">{{ t('batch.rowVerdict') }}</span
              ><span class="tag" :class="ready[1]">{{ ready[0] }}</span>
            </div>
          </div>
          <div class="note" style="margin-top: 8px">
            {{
              t('batch.totalsNote', {
                ts: S.result.ranAt,
                v: S.inputs.v,
                over: S.overCount ? t('batch.overSuffix') : '',
              })
            }}
            <span class="src">{{ t('batch.screeningBasis') }}</span>
          </div>
          <div v-if="s.oversized_catchments" class="note warn" style="margin-top: 6px">
            {{ t('batch.oversized', { n: s.oversized_catchments }) }}
          </div>
        </div>

        <!-- 跑过 ANUGA 的那一片：拿实测积水量校核推理公式法 -->
        <PondingCheck />

        <div>
          <h3>{{ t('batch.linesHeading') }}</h3>
          <!-- 这条必须在图上面：下面的水量条只画有结论的点，不说清就会被读成全网 -->
          <div
            class="note"
            style="margin: 0 0 10px; padding: 8px 10px; border-radius: 6px; background: rgba(255,255,255,.05); line-height: 1.5"
            v-html="
              t('batch.calibNote', {
                done: fmt(s.calibrated_hotspots),
                blank: fmt(s.line_counts.uncalibrated),
              })
            "
          />
          <div class="bar" style="margin: 0 0 12px">
            <i :style="{ left: 0, width: pc(s.line1_m3) + '%', background: 'var(--blue)' }" />
            <i :style="{ left: pc(s.line1_m3) + '%', width: pc(s.line2_m3) + '%', background: 'var(--green)' }" />
            <i
              :style="{
                left: pc(s.line1_m3) + pc(s.line2_m3) + '%',
                width: pc(s.line3_m3) + '%',
                background: 'var(--amber)',
              }"
            />
          </div>
          <div class="stat">
            <div style="border-left: 3px solid var(--blue)">
              <div class="l">
                {{
                  t('batch.line1Stat', { pc: pc(s.line1_m3), n: s.line_counts['1'], h: hours })
                }}
              </div>
              <div class="v">
                {{ fmt(s.line1_m3) }} <span class="l" style="font-size: 14px">{{ t('batch.line1Unit') }}</span>
              </div>
            </div>
            <div style="border-left: 3px solid var(--green)">
              <div class="l">
                {{
                  t('batch.line2Stat', {
                    need: fmt(s.required_storage_m3),
                    have: fmt(s.available_pond_m3),
                    pc: pc(s.line2_m3),
                  })
                }}
              </div>
              <div class="v">
                {{ fmt(s.line2_m3) }} <span class="l" style="font-size: 14px">{{ t('batch.line2Unit') }}</span>
              </div>
            </div>
            <div style="border-left: 3px solid var(--amber)">
              <div class="l">
                {{ t('batch.line3Stat', { h: hours, v: fmt(s.shortfall_m3), pc: pc(s.line3_m3) }) }}
              </div>
              <div class="v">
                {{ fmt(s.pumps_required) }}
                <span class="l" style="font-size: 14px">{{
                  t('batch.line3Unit', { n: fmt(s.tanker_loads) })
                }}</span>
              </div>
            </div>
          </div>
        </div>

        <div>
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px">
            <h3 style="margin: 0">{{ t('batch.listHeading') }}</h3>
            <span class="note">{{ t('batch.listNote', { n: sorted.length }) }}</span>
          </div>
          <div class="pills" style="margin-bottom: 10px">
            <span
              v-for="[g, label, title] in groups"
              :key="g"
              :class="{ on: S.listLine === g }"
              :title="title"
              @click="pickGroup(g)"
              >{{ label }}</span
            >
          </div>
          <div v-if="!sorted.length" class="note">{{ t('batch.groupEmpty') }}</div>
          <div v-else class="rows">
            <div
              v-for="(x, i) in list"
              :key="x.uid"
              class="row pick"
              :class="{ sel: S.sel === x.uid }"
              @click="S.select(x.uid)"
            >
              <span class="tag n">{{ i + 1 }}</span>
              <span
                style="flex: 1; margin: 0 8px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap"
              >
                <b>{{ x.uid }}</b> <span class="l">· {{ S.byUid.get(x.uid).location }}</span>
              </span>
              <!-- null 要先判：落到 v-else 会把「没算」显示成「需出动车队」 -->
              <span v-if="x.line === null" class="tag l">{{ t('batch.tagNone') }}</span>
              <span v-else-if="x.line === 1" class="tag b">{{ t('batch.tagLine1') }}</span>
              <span v-else-if="x.line === 2" class="tag s">{{ t('batch.tagLine2') }}</span>
              <span v-else class="tag d">{{ S.pumpBrief(x) }}</span>
            </div>
          </div>
          <div
            v-if="sorted.length > S.listLimit"
            class="note"
            style="margin-top: 8px; cursor: pointer"
            @click="S.listLimit += 20"
          >
            {{ t('batch.showMore', { shown: S.listLimit, total: sorted.length }) }}
          </div>
          <DetailBlock v-if="S.sel" :res="S.resByUid.get(S.sel)" />
          <div v-else class="note" style="margin-top: 8px">{{ t('batch.pickHint') }}</div>
        </div>
      </template>
    </div>

    <div class="bottom">
      <button class="ghost" :disabled="!S.result" @click="onExport">
        <AppIcon name="exp" :size="16" /> {{ t('batch.exportCsv') }}
      </button>
      <button class="ghost" @click="S.openDrawer()">
        <AppIcon name="lock" :size="16" /> {{ t('batch.modelInputs', { v: S.inputs.v }) }}
      </button>
    </div>
  </aside>
</template>
