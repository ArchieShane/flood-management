<script setup>
import { computed } from 'vue'

import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'
import { fmt } from '../../utils/format'

const S = useScenarioStore()
const D = computed(() => S.draft)

const ROWS = computed(() => [
  ['sed_factor', t('drawer.sedFactor'), t('drawer.sedFactorSrc'), 0.01, false],
  ['shape_factor', t('drawer.shapeFactor'), t('drawer.shapeFactorSrc'), 0.05, true],
  ['drawdown_hours', t('drawer.drawdownHours'), t('drawer.drawdownHoursSrc'), 0.5, true],
])

/* 车队配置单独成组 —— 这几个是「派什么车」，上面那三个是「怎么算水」。
   混在一张表里，改泵的人要在淤积裕量和形状系数之间找自己那一行。

   ⚠ 泵侧（前两行）与罐车侧（后三行）**串联**：泵把水抽进罐车、罐车运走，
     外运能力取两侧较小值。只调一侧调不动结果，下面的派生行会当场说卡在哪。 */
const FLEET_ROWS = computed(() => [
  ['pumps_per_point', t('drawer.pumpsPerPoint'), t('drawer.pumpsPerPointSrc'), 1, true],
  ['pump_capacity', t('drawer.pumpCapacity'), t('drawer.pumpCapacitySrc'), 50, true],
  ['tankers_per_point', t('drawer.tankersPerPoint'), t('drawer.tankersPerPointSrc'), 1, true],
  ['tanker_capacity', t('drawer.tankerCapacity'), t('drawer.tankerCapacitySrc'), 1, true],
  ['tanker_turnaround_min', t('drawer.tankerTurnaround'), t('drawer.tankerTurnaroundSrc'), 5, true],
  ['pump_duty_factor', t('drawer.pumpDuty'), t('drawer.pumpDutySrc'), 0.05, true],
  ['pump_availability', t('drawer.pumpAvail'), t('drawer.pumpAvailSrc'), 0.05, true],
])

/* 「每点 N 台 × 每台 X m³/h」的合计 —— 改完旋钮立刻看得见结果。
   清空了单泵能力就没有这个数（那时按分档表派车，一台不是固定排量），印「—」。 */
/* 一辆罐车在时限内跑得完几趟 = ⌊T×60 / 周转⌋。0 = 周转比时限还长，辆数不出数。 */
const tankerTrips = computed(() => {
  const a = D.value.assumptions
  return a.tanker_turnaround_min > 0
    ? Math.floor((a.drawdown_hours * 60) / a.tanker_turnaround_min)
    : 0
})

const configuredRate = computed(() =>
  D.value.assumptions.pump_capacity
    ? (D.value.assumptions.pumps_per_point || 0) * D.value.assumptions.pump_capacity
    : null,
)

/* —— 罐车侧与链的实际外运能力 ——
   单车持续外运 = 单车载量 / 往返周转；罐车侧 = 辆数 × 它。链取两侧较小值。
   这三行是派生量，不能设 —— 摆出来是为了让人改完旋钮当场看见卡在哪一侧。 */
const tankerVehicleRate = computed(() => {
  const a = D.value.assumptions
  return a.tanker_turnaround_min > 0 ? a.tanker_capacity / (a.tanker_turnaround_min / 60) : 0
})
const tankerRate = computed(
  () => (D.value.assumptions.tankers_per_point || 0) * tankerVehicleRate.value,
)
const chainRate = computed(() =>
  configuredRate.value === null ? null : Math.min(configuredRate.value, tankerRate.value),
)
/** 喂饱一台泵要几辆车 = ⌈单泵排量 / 单车外运能力⌉，默认 ⌈300/15⌉ = 20。 */
const tankersPerPump = computed(() => {
  const cap = D.value.assumptions.pump_capacity
  return cap && tankerVehicleRate.value > 0 ? Math.ceil(cap / tankerVehicleRate.value) : null
})

/* 分档表现在是**参照**：单泵抽排能力该设多少，对着在册车队的实际构成挑。
   只有清空了「单泵抽排能力」才会退回按它派车 —— 那时 summaryTiers 就是这三档
   本身，参照与在用合一，标题也跟着换回「在用」的说法。 */
const inUse = computed(() => S.summaryTiers)
const tiersAreReference = computed(
  () => inUse.value.length === 1 && inUse.value[0].key === 'uniform',
)
const PENDING = computed(() => [
  {
    label: '—',
    nameplate_m3hr: null,
    rated_m3hr: null,
    fleet_qty: null,
    basis: t('drawer.tierPending'),
    reference: t('drawer.tierPendingRef'),
  },
])
const tiers = computed(() => {
  const rows = tiersAreReference.value ? S.summaryRefTiers : inUse.value
  return rows.length ? rows : PENDING.value
})

/* 清空成 null **只有 `pump_capacity` 允许** —— 它的 null 有明确含义：
   退回 12″/8″/6″ 分档派车。其余几项后端都是必填正数，发 null 会 422，
   故清空时退回该项的当前值，而不是把一个非法值悄悄带进请求里。 */
const CLEARABLE = new Set(['pump_capacity'])

const setValue = (k, e) => {
  if (e.target.value === '') {
    if (CLEARABLE.has(k)) D.value.assumptions[k] = null
    else e.target.value = D.value.assumptions[k]
    return
  }
  D.value.assumptions[k] = Number(e.target.value)
}
</script>

<template>
  <div>
    <table>
      <thead>
        <tr>
          <th>{{ t('drawer.asmParam') }}</th>
          <th class="r">{{ t('drawer.asmValue') }}</th>
          <th>{{ t('drawer.asmSource') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="[k, label, src, step, assumed] in ROWS" :key="k">
          <td>{{ label }}</td>
          <td class="r">
            <input
              type="number"
              :step="step"
              min="0"
              :class="{ key: assumed }"
              :value="D.assumptions[k]"
              @change="setValue(k, $event)"
            />
          </td>
          <td class="note">{{ src }}</td>
        </tr>
      </tbody>
    </table>

    <h3 style="margin: 18px 0 8px">{{ t('drawer.fleetHeading') }}</h3>
    <table>
      <thead>
        <tr>
          <th>{{ t('drawer.asmParam') }}</th>
          <th class="r">{{ t('drawer.asmValue') }}</th>
          <th>{{ t('drawer.asmSource') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="[k, label, src, step, assumed] in FLEET_ROWS" :key="k">
          <td>{{ label }}</td>
          <td class="r">
            <input
              type="number"
              :step="step"
              min="0"
              :class="{ key: assumed }"
              :value="D.assumptions[k]"
              @change="setValue(k, $event)"
            />
          </td>
          <td class="note">{{ src }}</td>
        </tr>
        <tr>
          <td>{{ t('drawer.tankerTrips') }}</td>
          <td class="r"><b>{{ tankerTrips }}</b></td>
          <td class="note">{{ t('drawer.tankerTripsSrc') }}</td>
        </tr>
        <tr>
          <td>{{ t('drawer.tankerVehicleRate') }}</td>
          <td class="r"><b>{{ fmt(tankerVehicleRate, 1) }}</b></td>
          <td class="note">{{ t('drawer.tankerVehicleRateSrc') }}</td>
        </tr>
        <tr>
          <td>{{ t('drawer.tankersPerPump') }}</td>
          <td class="r"><b>{{ tankersPerPump === null ? '—' : tankersPerPump }}</b></td>
          <td class="note">{{ t('drawer.tankersPerPumpSrc') }}</td>
        </tr>
        <tr>
          <td>{{ t('drawer.fleetConfiguredRate') }}</td>
          <td class="r"><b>{{ fmt(configuredRate) }}</b></td>
          <td class="note">
            {{ configuredRate === null
              ? t('drawer.fleetConfiguredRateTiered')
              : t('drawer.fleetConfiguredRateSrc') }}
          </td>
        </tr>
        <tr>
          <td>{{ t('drawer.tankerSideRate') }}</td>
          <td class="r"><b>{{ fmt(tankerRate, 1) }}</b></td>
          <td class="note">{{ t('drawer.tankerSideRateSrc') }}</td>
        </tr>
        <!-- 串联链的实际外运能力 = 两侧取小。这一行是整组的落点。 -->
        <tr>
          <td>{{ t('drawer.chainRate') }}</td>
          <td class="r"><b>{{ chainRate === null ? '—' : fmt(chainRate, 1) }}</b></td>
          <td class="note">{{ t('drawer.chainRateSrc') }}</td>
        </tr>
      </tbody>
    </table>

    <h3 style="margin: 18px 0 8px">
      {{ tiersAreReference ? t('drawer.tiersHeadingRef') : t('drawer.tiersHeading') }}
    </h3>
    <div v-if="tiersAreReference" class="note" style="margin-bottom: 8px">
      {{ t('drawer.tiersRefLead') }}
    </div>
    <table>
      <thead>
        <tr>
          <th>{{ t('drawer.tierLabel') }}</th>
          <th class="r">{{ t('drawer.tierNameplate') }}</th>
          <th class="r">{{ t('drawer.tierRated') }}</th>
          <th class="r">{{ t('drawer.tierFleetQty') }}</th>
          <th>{{ t('drawer.tierBasis') }}</th>
          <th>{{ t('drawer.tierRef') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="tier in tiers" :key="tier.label">
          <td>{{ tier.label }}</td>
          <td class="r">{{ fmt(tier.nameplate_m3hr) }}</td>
          <td class="r"><b>{{ fmt(tier.rated_m3hr) }}</b></td>
          <td class="r">{{ fmt(tier.fleet_qty) }}</td>
          <td class="key">{{ tier.basis }}</td>
          <td class="note">{{ tier.reference }}</td>
        </tr>
      </tbody>
    </table>

    <div class="note" style="margin-top: 8px" v-html="t('drawer.tiersNote')" />
    <div class="note" style="margin-top: 12px">{{ t('drawer.cfNote') }}</div>
  </div>
</template>
