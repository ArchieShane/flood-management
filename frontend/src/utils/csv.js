/* 导出跟着界面语言走。
   ⚠ 中文表头与 `stormwater/report.py` 的 CSV_COLUMNS 逐列对齐，两边导出的表可直接对比；
   切英文后列**顺序与含义不变**，只是列名换成了 snake_case 英文，与 report.py 不再同名。
   中文列名改动仍须同步改那边。 */
import { CATCHMENT_BASIS, QCAP_BASIS, STORAGE_BASIS, csvBasis } from './basis'
import { causeLabel, critLabel, muniLabel } from './format'
import { t, tm } from '../i18n'

const datasetCell = key =>
  ({
    adqcc_zone_a: t('csv.datasetZoneA'),
    adqcc_zone_b: t('csv.datasetZoneB'),
    dubai_dm: t('csv.datasetDubai'),
    custom_storm: t('csv.datasetCustom'),
  }[key] || key)

// line 为 null = 该点没跑过二维演算，三道防线不出结论。**不可退化成空白或 0** ——
// 导出的表要让人一眼看出这行是「没算」而不是「没事」。
const lineCell = line =>
  line === null || line === undefined
    ? t('csv.lineNone')
    : { 1: t('csv.line1'), 2: t('csv.line2'), 3: t('csv.line3') }[line] || line

// 无标定点的各量是 null —— 导出成空白而不是 0，口径同 report.py 的 _blank()。
const yesNoBlank = v => (v === null || v === undefined ? '' : v ? t('csv.yes') : t('csv.no'))
const l1BasisCell = b =>
  ({
    hydrodynamic: t('csv.l1Hydro'),
    peak: t('csv.l1Peak'),
    uncalibrated: t('csv.l1None'),
  })[b] || b || ''

const csvYesNo = v => (v === null || v === undefined ? '' : v ? t('csv.has') : t('csv.hasNot'))
const yesNo = v => (v ? t('csv.yes') : t('csv.no'))

const cell = v => {
  const s = v === null || v === undefined ? '' : String(v)
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
}

/**
 * 表头与数据列数必须一一对应。
 *
 * 这两者分处两个文件（表头在 `i18n/*.js`，取值在本文件），改一边忘另一边不会
 * 报错，只会让某一列之后的**全部数据静默右移一格** —— 导出的表看上去正常，
 * 数字却全挂错了列。加过一列忘了加取值，正是这么出的问题，故在这里挡住。
 */
function assertColumns(head, row, which) {
  if (head.length !== row.length) {
    throw new Error(
      `CSV 列数对不上（${which}）：表头 ${head.length} 列，数据 ${row.length} 列 —— ` +
        `改了 i18n 的 ${which}Head 就要同步改 utils/csv.js 的取值，反之亦然`,
    )
  }
}

/** BOM 开头，Excel 直接双击打开不乱码。 */
function download(lines, filename) {
  const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}

/** 单点多情景导出：一行一个重现期，列与全域批算的同名列同义。 */
export function exportPointCsv(S) {
  const c = S.curve
  if (!c) return null
  const p = S.byUid.get(c.point.uid)
  const head = tm('csv.pointHead')
  const lines = [head.join(',')]
  c.scenarios.forEach(r => {
    const row = [
        p.uid, muniLabel(p.municipality), p.area, p.location, p.lat, p.lon,
        critLabel(p.criticality),
        p.root_cause ? causeLabel(p.root_cause) : t('csv.unfilled'),
        yesNo(p.in_coverage),
        datasetCell(r.dataset_key),
        r.return_period_yr || t('csv.customStorm', { p: S.custom.P, d: S.custom.D }),
        r.duration_min, r.intensity_mm_hr, r.c_adjusted, r.area_ha, r.tc_min,
        csvBasis(CATCHMENT_BASIS, r.catchment_basis), p.impervious_share,
        r.qcap_m3s, csvBasis(QCAP_BASIS, r.qcap_basis),
        r.peak_flow_m3s, yesNo(r.peak_exceeds_capacity),
        r.window_hours, l1BasisCell(r.l1_basis), r.runoff_volume_m3,
        r.network_drained_m3, r.residual_after_network_m3,
        r.pond_available_m3, csvBasis(STORAGE_BASIS, r.storage_basis), r.storage_used_m3,
        r.shortfall_m3, r.pumping_rate_m3hr, r.pumps_required, r.tanker_loads,
        // 辆数留空 = 周转长于时限，一辆车跑不满一趟 —— 与「0 辆」不是一回事
        r.tanker_trips_per_vehicle, r.tankers_required, r.tankers_to_feed_pumps,
        // —— 页面配置的车队：配了几台泵几辆车、够不够、卡在哪一侧。
        //    与上面的「所需」并列，不可混用。⚠ 泵与罐车串联，「链外运能力」
        //    才是这个点每小时真走得掉的量 —— 单看泵侧会把够用说反。 ——
        r.pumps_configured, r.tankers_configured,
        r.pump_configured_m3hr, r.tanker_configured_m3hr, r.chain_configured_m3hr,
        r.chain_bottleneck || '',
        yesNoBlank(r.configured_fleet_suffice), r.chain_residual_m3, r.chain_hours_required,
        p.pumps_qty, p.tankers_qty, lineCell(r.line), 'v' + S.inputs.v,
    ]
    assertColumns(head, row, 'point')
    lines.push(row.map(cell).join(','))
  })
  download(lines, t('csv.pointFile', { uid: p.uid, n: c.scenarios.length }))
  return { uid: p.uid, count: c.scenarios.length }
}

export function exportBatchCsv(S) {
  if (!S.result) return null
  // 「台账片区」是各市政区自填的自由文本，「官方片区」按社区面几何判 —— 两者不可互换
  const head = tm('csv.batchHead')
  const lines = [head.join(',')]
  const storm = S.stormLabel
  S.result.points.forEach(r => {
    const p = S.byUid.get(r.uid)
    const row = [
        p.uid, p.source, muniLabel(p.municipality), p.area,
        p.district
          ? t('common.districtWithMuni', { name: p.district, muni: muniLabel(p.district_municipality) })
          : t('csv.undecided'),
        p.location, p.lat, p.lon,
        critLabel(p.criticality),
        p.root_cause ? causeLabel(p.root_cause) : t('csv.unfilled'),
        csvYesNo(p.network_available), yesNo(p.in_coverage), p.elevation_m,
        datasetCell(r.dataset_key), storm,
        r.duration_min, r.intensity_mm_hr, r.c_adjusted, r.area_ha, r.tc_min,
        csvBasis(CATCHMENT_BASIS, r.catchment_basis), p.impervious_share,
        r.qcap_m3s, csvBasis(QCAP_BASIS, r.qcap_basis), p.nearest_pipe_m,
        r.peak_flow_m3s, r.excess_flow_m3s, yesNo(r.peak_exceeds_capacity),
        r.window_hours, l1BasisCell(r.l1_basis), r.runoff_volume_m3,
        r.network_drained_m3, yesNoBlank(r.cleared_by_network),
        // 空白 = 无标定，或演算到结束仍未退干（与 report.py 同一写法）
        // 两列口径不同：前者自演算 t=0 起算，后者自峰值起算、与时限 T 同起点。
        r.drain_hours === null ? '' : r.drain_hours,
        r.recession_hours == null ? '' : r.recession_hours,
        r.residual_after_network_m3,
        r.ponding_peak_m3, r.ponding_peak_time_min, r.ponding_attribution || '',
        r.required_storage_m3, r.pond_available_m3,
        csvBasis(STORAGE_BASIS, r.storage_basis), r.storage_used_m3,
        r.cleared_by_storage === null || r.cleared_by_storage === undefined
          ? ''
          : r.cleared_by_network
            ? t('csv.notNeeded')
            : yesNo(r.cleared_by_storage),
        r.shortfall_m3, r.pumping_rate_m3hr,
        // 无标定时 pumps_by_tier 是 null —— 留空，不补 0。
        // 单档（页面自定义单泵能力）口径下这三列恒为 0：台数全落在「所需移动泵」那列，
        // 清空「单泵抽排能力」退回分档派车时它们才有值。
        r.pumps_by_tier ? r.pumps_by_tier['12in'] || 0 : '',
        r.pumps_by_tier ? r.pumps_by_tier['8in'] || 0 : '',
        r.pumps_by_tier ? r.pumps_by_tier['6in'] || 0 : '',
        r.pump_deployed_m3hr,
        r.pumps_required, r.tanker_loads,
        // 辆数留空 = 周转长于时限，一辆车跑不满一趟 —— 与「0 辆」不是一回事
        r.tanker_trips_per_vehicle, r.tankers_required, r.tankers_to_feed_pumps,
        // —— 页面配置的车队：配了几台泵几辆车、够不够、卡在哪一侧。
        //    与上面的「所需」并列，不可混用。⚠ 泵与罐车串联，「链外运能力」
        //    才是这个点每小时真走得掉的量 —— 单看泵侧会把够用说反。 ——
        r.pumps_configured, r.tankers_configured,
        r.pump_configured_m3hr, r.tanker_configured_m3hr, r.chain_configured_m3hr,
        r.chain_bottleneck || '',
        yesNoBlank(r.configured_fleet_suffice), r.chain_residual_m3, r.chain_hours_required,
        p.pumps_qty, p.tankers_qty, lineCell(r.line), 'v' + S.inputs.v,
    ]
    assertColumns(head, row, 'batch')
    lines.push(row.map(cell).join(','))
  })
  download(
    lines,
    t('csv.batchFile', {
      storm: S.useCustom
        ? t('csv.batchFileCustom', { p: S.custom.P, d: S.custom.D })
        : t('csv.batchFileRp', { n: S.rp }),
      n: S.result.points.length,
    }),
  )
  return { count: S.result.points.length }
}
