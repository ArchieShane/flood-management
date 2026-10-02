<script setup>
/* 一个点在某一场雨下的完整计算链。`res` 来自批算或单点曲线，两者字段同构。 */
import { computed } from 'vue'

import { CATCHMENT_BASIS, QCAP_BASIS, STORAGE_BASIS, basisTagHtml } from '../../utils/basis'
import { datasetLabel } from '../../constants'
import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'
import { causeLabel, critLabel, esc, fmt, muniLabel } from '../../utils/format'

const props = defineProps({ res: { type: Object, default: null } })

const S = useScenarioStore()
const p = computed(() => (S.sel ? S.byUid.get(S.sel) : null))
const r = computed(() => props.res)
const hours = computed(() => S.asm.drawdown_hours)

/** 演算跑的是别的重现期 —— 与「压根没跑过」是两种无标定，说法不一样。 */
const stormMismatch = computed(
  () => !!r.value && r.value.line === null && !!r.value.ponding_run_id,
)

const verdict = computed(() => {
  const x = r.value
  if (x.line === null) return [t('detail.verdictNone'), 'l']
  if (x.line === 1) return [t('detail.verdict1', { h: hours.value }), 'b']
  if (x.line === 2) return [t('detail.verdict2'), 's']
  return [
    t('detail.verdict3', { brief: S.pumpBrief(x), h: hours.value, v: fmt(x.shortfall_m3) }),
    'd',
  ]
})

/** 现场处置建议。三道防线各有各的说法，共用模板会把结论说糊。 */
const plan = computed(() => {
  const x = r.value
  const h = hours.value
  if (x.line === null)
    return stormMismatch.value
      ? t('detail.planNoneStorm', {
          runRp: x.ponding_run_rp_yr ?? '—',
          // 批算的逐点行没有 return_period_yr（只有单点曲线有），退回当前选的级别
          selRp: x.return_period_yr ?? S.rp,
        })
      : t('detail.planNone')
  if (x.line === 1)
    return (
      t('detail.plan1', {
        runoff: fmt(x.runoff_volume_m3),
        h,
        // 峰后口径 —— 与时限 T 同起点，这样它和「一道排走多少」才可比。
        // 用 drain_hours（自演算 t=0 起算）会把涨水期也算进去，两个数对不上，
        // 2026-09-21 用户就是在 ADM-379 上从这处对不上发现一道算错了的。
        drainH: fmt(x.recession_hours ?? x.drain_hours, 1),
      }) +
      (x.peak_exceeds_capacity
        ? t('detail.plan1Warn', { q: fmt(x.peak_flow_m3s, 2), qcap: fmt(x.qcap_m3s, 2), h })
        : '')
    )
  if (x.line === 2)
    return t('detail.plan2', {
      h,
      drained: fmt(x.network_drained_m3),
      residual: fmt(x.residual_after_network_m3),
      need: fmt(x.required_storage_m3),
    })
  return (
    t('detail.plan3a', {
      runoff: fmt(x.runoff_volume_m3),
      h,
      drained: fmt(x.network_drained_m3),
      pond: fmt(x.pond_available_m3),
      need: fmt(x.required_storage_m3),
    }) +
    t('detail.plan3b', {
      location: esc(p.value.location),
      muni: esc(muniLabel(p.value.municipality)),
      area: esc(p.value.area),
      brief: S.pumpBrief(x),
      // 调度指令里给的是**辆数**（要派几辆车），车次跟在后面当依据。
      // 周转长于时限时辆数不出数，那一句改成说清为什么派不了。
      tankers:
        x.tankers_required === null
          ? t('detail.plan3bTankersNone')
          : t('detail.plan3bTankers', {
              n: fmt(x.tankers_required),
              loads: fmt(x.tanker_loads),
              trips: x.tanker_trips_per_vehicle,
            }),
    }) +
    t('detail.plan3c', { n: fmt(p.value.pumps_qty) }) +
    // 配置侧读的是**整条链**（泵侧与罐车侧取小），不是单看泵 —— 车不够时
    // 泵在等车，只印泵侧会把「够用」说反。卡在哪一侧也一并说，那决定该加什么。
    (x.configured_fleet_suffice
      ? t('detail.plan3dOk', {
          n: fmt(x.pumps_configured),
          cars: fmt(x.tankers_configured),
          rate: fmt(x.chain_configured_m3hr),
          h,
          hours: fmt(x.chain_hours_required, 1),
        })
      : t('detail.plan3dShort', {
          n: fmt(x.pumps_configured),
          cars: fmt(x.tankers_configured),
          rate: fmt(x.chain_configured_m3hr),
          side: t(`inputs.bottleneck_${x.chain_bottleneck}`),
          h,
          left: fmt(x.chain_residual_m3),
          hours: fmt(x.chain_hours_required, 1),
          need: fmt(x.pumps_required),
          needCars: fmt(Math.max(x.tankers_required || 0, x.tankers_to_feed_pumps || 0)),
        }))
  )
})

const chain = computed(() => {
  const x = r.value
  const pt = p.value
  const h = hours.value
  const catchTag = basisTagHtml(CATCHMENT_BASIS, x.catchment_basis)
  return [
    [
      t('detail.chainIdf'),
      x.dataset_key === 'custom_storm' ? t('dataset.custom') : datasetLabel(x.dataset_key),
    ],
    [t('detail.chainDuration'), `${fmt(x.duration_min, 1)} min`],
    [t('detail.chainIntensity'), `${fmt(x.intensity_mm_hr, 1)} mm/h`],
    [t('detail.chainC'), fmt(x.c_adjusted, 2)],
    [
      t('detail.chainArea') + catchTag,
      `${fmt(x.area_ha, 1)} ha` +
        (pt.impervious_share === null || pt.impervious_share === undefined
          ? ''
          : t('detail.chainImpervious', { pc: fmt(pt.impervious_share * 100, 0) })),
    ],
    [t('detail.chainTc') + catchTag, `${fmt(x.tc_min, 1)} min`],
    [t('detail.chainPeak'), `${fmt(x.peak_flow_m3s, 2)} m³/s`],
    [
      t('detail.chainQcap') + basisTagHtml(QCAP_BASIS, x.qcap_basis),
      `${fmt(x.qcap_m3s, 2)} m³/s` +
        (x.qcap_basis === 'measured' && pt.nearest_pipe_m !== null
          ? t('detail.chainNearestPipe', {
              d: fmt(pt.nearest_pipe_m, 1),
              far: pt.nearest_pipe_m > 100 ? t('detail.chainFar') : '',
            })
          : ''),
    ],
    [t('detail.chainExcess'), `${fmt(x.excess_flow_m3s, 2)} m³/s`],
    // 第一道的数据来源单独一行 —— 无标定时整条防线链到此为止，
    // 下面那些量在这个点上根本不存在，画成 0 会读成「算出来是零」。
    [
      t('detail.chainL1Basis'),
      x.line === null ? t('detail.chainL1BasisNone') : t('detail.chainL1BasisHydro'),
    ],
    ...(x.line === null
      ? []
      : [
          [t('detail.chainRunoff'), `${fmt(x.runoff_volume_m3)} m³`],
          [
            t('detail.chainPondPeak', { t: fmt(x.ponding_peak_time_min, 0) }),
            `${fmt(x.ponding_peak_m3)} m³`,
          ],
          ...(x.ponding_attribution
            ? [[t('detail.chainPondAttr'), x.ponding_attribution]]
            : []),
          [t('detail.chainL1Drained', { h }), `${fmt(x.network_drained_m3)} m³`],
          [
            t('detail.chainL1Hours'),
            x.recession_hours == null
              ? t('detail.chainL1Never')
              : `${fmt(x.recession_hours, 1)} h`,
          ],
          [t('detail.chainL1Residual'), `${fmt(x.residual_after_network_m3)} m³`],
          [t('detail.chainL2Need'), `${fmt(x.required_storage_m3)} m³`],
          [
            t('detail.chainL2Avail') + basisTagHtml(STORAGE_BASIS, x.storage_basis),
            `${fmt(x.pond_available_m3)} m³`,
          ],
          [t('detail.chainL2Used'), `${fmt(x.storage_used_m3)} m³`],
          [t('detail.chainL3Short', { h }), `${fmt(x.shortfall_m3)} m³`],
          [t('detail.chainL3Rate'), `${fmt(x.pumping_rate_m3hr)} m³/h`],
          [t('detail.chainL3Fleet'), `${x.pumps_required} · ${x.tanker_loads}`],
          // —— 页面上配的那套「N 台泵 + M 辆车」，够不够。与上一行的「所需」
          //    **并列**，不是替代。三行一起读：两侧各自多少、取小是多少。
          [
            t('detail.chainL3Configured'),
            t('detail.chainL3ConfiguredValue', {
              n: fmt(x.pumps_configured),
              rate: fmt(x.pump_configured_m3hr),
              cars: fmt(x.tankers_configured),
              carRate: fmt(x.tanker_configured_m3hr, 1),
            }),
          ],
          [
            t('detail.chainL3Throughput'),
            t('detail.chainL3ThroughputValue', {
              rate: fmt(x.chain_configured_m3hr, 1),
              side: t(`inputs.bottleneck_${x.chain_bottleneck}`),
            }),
          ],
          [
            t('detail.chainL3Suffice', { h }),
            x.configured_fleet_suffice
              ? `<span class="tag s">${t('detail.chainL3SufficeYes')}</span>`
              : `<span class="tag d">${t('detail.chainL3SufficeNo', {
                  v: fmt(x.chain_residual_m3),
                })}</span>`,
          ],
          [t('detail.chainL3Hours'), `${fmt(x.chain_hours_required, 1)} h`],
          // 罐车侧：车次是体积换算（与时限无关），辆数才是调度结论。
          // 两行分开摆 —— 合成一行会让人把车次当辆数用。
          [t('detail.chainL3Loads'), `${fmt(x.tanker_loads)} ${t('detail.loadsUnit')}`],
          [
            t('detail.chainL3Tankers', { h }),
            x.tankers_required === null
              ? `<span class="tag d">${t('detail.chainL3TankersNone')}</span>`
              : t('detail.chainL3TankersValue', {
                  n: fmt(x.tankers_required),
                  trips: x.tanker_trips_per_vehicle,
                }),
          ],
          // 按水量算的车数不一定喂得饱按水量算的泵数 —— 两个约束取大的那个
          // 才是真正要配的车数。单印前者会低报，那正是「或」的老毛病。
          [
            t('detail.chainL3FeedPumps'),
            t('detail.chainL3FeedPumpsValue', {
              n: fmt(x.tankers_to_feed_pumps),
              pumps: fmt(x.pumps_required),
            }),
          ],
        ]),
  ]
})

const rpSuffix = computed(() => {
  const x = r.value
  if (x.return_period_yr === undefined) return ''
  return x.return_period_yr
    ? t('detail.rpSuffixRp', { n: x.return_period_yr })
    : t('detail.rpSuffixCustom', { p: S.custom.P, d: S.custom.D })
})

const borderColor = computed(() =>
  r.value.line === null
    ? 'rgba(255, 255, 255, 0.28)'
    : r.value.line === 1
      ? 'var(--blue)'
      : r.value.line === 2
        ? 'var(--green)'
        : 'var(--red)',
)
</script>

<template>
  <div v-if="!p" />
  <div v-else-if="!r" id="detail" class="note" style="margin-top: 10px">
    {{ t('detail.outOfScope', { uid: p.uid }) }}
  </div>
  <div v-else id="detail" style="margin-top: 14px">
    <h3>{{ p.uid }} · {{ p.location }}{{ rpSuffix }}</h3>
    <span class="tag" :class="verdict[1]">{{ verdict[0] }}</span>

    <div
      style="margin-top: 10px; background: rgba(255, 255, 255, 0.06); padding: 10px 12px; border-radius: 6px"
      :style="{ borderLeft: '3px solid ' + borderColor }"
    >
      <div class="note" style="margin-bottom: 6px">{{ t('detail.planHeading') }}</div>
      <div style="color: rgba(255, 255, 255, 0.9); line-height: 1.55" v-html="plan" />
    </div>

    <div class="rows" style="margin-top: 10px">
      <div v-for="([k, v], i) in chain" :key="i" class="row">
        <span class="l" v-html="k" /><b v-html="v" />
      </div>
    </div>

    <div class="note" style="margin-top: 6px">
      {{
        t('detail.ledgerLine', {
          crit: critLabel(p.criticality),
          cause: causeLabel(p.root_cause),
          lat: fmt(p.lat, 5),
          lon: fmt(p.lon, 5),
        })
      }}<template v-if="p.qc_flags.length">{{
        t('detail.qcFlags', { list: p.qc_flags.join(' / ') })
      }}</template>
    </div>
  </div>
</template>
