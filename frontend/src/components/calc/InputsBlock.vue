<script setup>
/* 「输入」一节 —— 两种模式共用同一套模型输入，换算口径不会因模式而漂移。 */
import { computed } from 'vue'

import AppIcon from '../AppIcon.vue'
import OverrideRow from './OverrideRow.vue'
import { priorityList } from '../../constants'
import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'
import { fmt } from '../../utils/format'

const S = useScenarioStore()

/* 框定了一个跑过二维演算的片区时，把该片实测积水时长的区间和出处写在 T 那一行
   下面 —— 只作参照。T 本身是运营设定（服务水平目标），默认锁在 2 h，不随片区改：
   要按 19.75 h 派车，得操作员自己把这个值改过去。 */
const windowNote = computed(() =>
  S.ponding
    ? t('inputs.drawdownFromPonding', {
        range: S.pondingWindowLabel,
        rp: S.ponding.return_period_yr,
        name: (S.districtRow(S.filters.district[0]) || { label: '' }).label,
      })
    : '',
)

const OVERRIDES = computed(() => [
  {
    label: t('inputs.drawdownHours'),
    field: 'drawdown_hours',
    unit: t('inputs.drawdownUnit'),
    step: 0.5,
    note: windowNote.value,
  },
  {
    label: t('inputs.pumpsPerPoint'),
    field: 'pumps_per_point',
    unit: t('inputs.pumpsPerPointUnit'),
    step: 1,
    note: t('inputs.pumpsPerPointNote'),
  },
  {
    label: t('inputs.pumpCapacity'),
    field: 'pump_capacity',
    unit: t('inputs.pumpCapacityUnit'),
    step: 50,
    note: t('inputs.pumpCapacityNote'),
  },
  {
    label: t('inputs.tankersPerPoint'),
    field: 'tankers_per_point',
    unit: t('inputs.tankersPerPointUnit'),
    step: 1,
    note: t('inputs.tankersPerPointNote'),
  },
  {
    label: t('inputs.tankerCapacity'),
    field: 'tanker_capacity',
    unit: t('inputs.tankerCapacityUnit'),
    step: 1,
  },
  {
    label: t('inputs.tankerTurnaround'),
    field: 'tanker_turnaround_min',
    unit: t('inputs.tankerTurnaroundUnit'),
    step: 5,
    note: t('inputs.tankerTurnaroundNote'),
  },
])

const priorityLabel = computed(() => {
  const list = priorityList()
  return (list.find(p => String(p.v) === String(S.inputs.priority)) || list[0]).label
})

/* 「每点 N 台 × 每台 X m³/h」算出来的那一个数 —— 两个旋钮一改就动。
   摆在旋钮下面，是因为调度真正关心的是合计运力，不是两个因子各自是多少。

   清空了单泵能力（退回分档表）时那个「台」取在册加权平均，且要跑过一次才知道
   —— 拿不到就印「—」，**不能落成 0**：0 会读成「这些泵抽不动水」。 */
const configuredRate = computed(() =>
  S.pumpUnitCapacity === null ? null : (S.asm.pumps_per_point || 0) * S.pumpUnitCapacity,
)
const configuredLabel = computed(() =>
  configuredRate.value === null
    ? t('inputs.fleetConfiguredPending')
    : t(S.pumpUnitFromTiers ? 'inputs.fleetConfiguredTiered' : 'inputs.fleetConfiguredValue', {
        rate: fmt(configuredRate.value),
      }),
)

/* —— 罐车侧与这条链的实际外运能力 ——
   ⚠ 泵和罐车**串联**：泵把水抽进罐车、罐车运走。所以这个点每小时真正走得掉
   多少水 = min(泵侧, 罐车侧)，两个旋钮哪个小就由哪个说了算。把三个数并排摆出
   来，是因为只印泵侧会让人以为加泵就能多排 —— 那正是这次改动要纠的误读。

   单车持续外运能力 = 单车载量 / 往返周转，默认 15 m³ / 1 h = 15 m³/h，
   与单泵 300 m³/h 差着一个量级。 */
const tankerVehicleRate = computed(() => {
  const turn = S.asm.tanker_turnaround_min
  return turn > 0 ? S.asm.tanker_capacity / (turn / 60) : 0
})
const tankerRate = computed(() => (S.asm.tankers_per_point || 0) * tankerVehicleRate.value)
const chainRate = computed(() =>
  configuredRate.value === null ? null : Math.min(configuredRate.value, tankerRate.value),
)
/** 卡在哪一侧 —— 决定该加泵还是该加车。 */
const bottleneck = computed(() =>
  configuredRate.value === null
    ? null
    : tankerRate.value < configuredRate.value
      ? 'tanker'
      : configuredRate.value < tankerRate.value
        ? 'pump'
        : 'balanced',
)
const chainLabel = computed(() =>
  chainRate.value === null
    ? t('inputs.fleetConfiguredPending')
    : t('inputs.chainRateValue', {
        rate: fmt(chainRate.value),
        side: t(`inputs.bottleneck_${bottleneck.value}`),
      }),
)
/** 喂饱当前配置的那几台泵要几辆车 —— 罐车侧该加到多少的靶子。 */
const tankersToFeed = computed(() =>
  configuredRate.value === null || tankerVehicleRate.value <= 0
    ? null
    : Math.ceil(configuredRate.value / tankerVehicleRate.value),
)

/* 一辆罐车在时限内跑得完几趟 —— 车次折成辆数的换算系数，也是这三个旋钮里
   最容易设出「不成立」的一个：周转比时限还长就是 0 趟，那时辆数不出数。
   把它摆在旋钮下面，是为了让人当场看见自己设出了什么。 */
const tankerTrips = computed(() => {
  const turn = S.asm.tanker_turnaround_min
  return turn > 0 ? Math.floor((S.asm.drawdown_hours * 60) / turn) : 0
})

const measured = computed(() => S.qcapBasisCount('measured'))
const measuredNoNetwork = computed(() => S.qcapBasisCount('measured_no_network'))
const assumedRest = computed(() => S.points.length - measured.value - measuredNoNetwork.value)

/* A / C / tc 的那一行**必须跟着数走**：曾经写死成「没有逐点来源」，而
   `catchment_batch.py` 早已把两套点全部逐点反算出来了（台账 845 / 845，
   片区 107 / 107）。留着那句会让人以为这几个数是拍脑袋的假设。
   真正还成立的保留意见是**边界**：台账是 Voronoi 几何代理，片区是 D8 汇流实算。 */
const cat = computed(() => (S.meta && S.meta.catchment) || null)
const catAssumed = computed(() => (cat.value ? cat.value.assumed_no_landuse || 0 : 0))
const catMeasured = computed(() => S.points.length - catAssumed.value)
const isModel = computed(() => S.source === 'model')
</script>

<template>
  <div>
    <h3>{{ t('inputs.heading') }}</h3>
    <div class="note" style="margin-bottom: 8px">
      <span class="tag b">{{ t('storm.adjustable') }}</span> {{ t('inputs.legendAdjustable') }} &nbsp;
      <span class="tag n" style="padding: 2px 6px"><AppIcon name="lock" :size="12" /></span>
      {{ t('inputs.legendLocked') }}
    </div>

    <div class="rows">
      <div class="row">
        <span class="l">{{ t('inputs.rowStorm') }}</span><span class="tag b">{{ t('storm.adjustable') }}</span>
      </div>
      <OverrideRow v-for="o in OVERRIDES" :key="o.field" v-bind="o" />
      <div class="row">
        <span class="l">{{ t('inputs.rowFleetConfigured') }}</span>
        <b>{{ configuredLabel }}</b>
      </div>
      <div class="row">
        <span class="l">{{ t('inputs.rowTankerSide') }}</span>
        <b>{{ t('inputs.tankerSideValue', {
          rate: fmt(tankerRate),
          each: fmt(tankerVehicleRate, 1),
        }) }}</b>
      </div>
      <!-- 串联链的实际外运能力 = 两侧取小。摆在两侧下面，读起来就是一道减法。 -->
      <div class="row">
        <span class="l">{{ t('inputs.rowChainRate') }}</span>
        <b :style="{ color: bottleneck === 'tanker' ? 'var(--amber)' : '' }">{{ chainLabel }}</b>
      </div>
      <div v-if="bottleneck === 'tanker'" class="note" style="margin: -2px 0 6px; color: var(--amber)">
        {{ t('inputs.chainTankerBound', { n: tankersToFeed }) }}
      </div>
      <div class="row">
        <span class="l">{{ t('inputs.rowTankerTrips', { h: S.asm.drawdown_hours }) }}</span>
        <b :style="{ color: tankerTrips ? '' : 'var(--red)' }">{{
          tankerTrips
            ? t('inputs.tankerTripsValue', { n: tankerTrips })
            : t('inputs.tankerTripsNone')
        }}</b>
      </div>
      <div class="row">
        <span class="l" v-html="t('inputs.rowProfile')" />
        <b
          >{{ t('inputs.byCause', { n: Object.keys(S.inputs.profiles).length }) }}
          <AppIcon name="lock" :size="12" :opacity="0.55"
        /></b>
      </div>
      <div class="row">
        <span class="l">{{ t('inputs.rowSedShape') }}</span>
        <b
          >{{ S.inputs.assumptions.sed_factor }} · {{ S.inputs.assumptions.shape_factor }}
          <AppIcon name="lock" :size="12" :opacity="0.55" /></b
        >
      </div>
      <div class="row">
        <span class="l" v-html="t('inputs.rowPriority')" />
        <b>{{ priorityLabel }} <AppIcon name="lock" :size="12" :opacity="0.55" /></b>
      </div>
    </div>

    <div class="note" style="margin-top: 8px">
      {{ t('inputs.chainNote', { v: S.inputs.v })
      }}<template v-if="S.overCount">
        · <span class="warn">{{ t('inputs.overrideNote', { n: S.overCount }) }}</span></template
      >
    </div>

    <div class="note" style="margin-top: 6px; border-left: 2px solid var(--amber); padding-left: 8px">
      <span
        v-html="
          t(isModel ? 'inputs.warnCatchmentModel' : 'inputs.warnCatchmentLedger', {
            measured: catMeasured,
            assumed: catAssumed,
          })
        "
      /><br />
      <span
        v-html="
          t('inputs.warn2', { measured, noNetwork: measuredNoNetwork, rest: assumedRest })
        "
      /><br />
      <!-- 台账「有无管网」那一列的可信度 —— 片区没有这一列，不摆无关的保留意见 -->
      <span v-if="!isModel" v-html="t('inputs.warn3')" />
    </div>
  </div>
</template>
