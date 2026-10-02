/* 地图 tooltip / popup 仍然是 HTML 串 —— Leaflet 收的就是串，
   不值得为两个气泡挂两个 Vue 应用实例。外部文本一律走 esc()。

   ⚠ 这两个串在语言切换后不会自己重绘：Leaflet 的 marker 不是 Vue 组件。
   MapView 监听 locale 重建 marker，见那边的 watch。 */
import { t } from '../i18n'
import { causeLabel, critLabel, esc, fmt, muniLabel } from './format'

/** 「有无管网」一行：只答管网库。台账的 `network_available` 不参与显示 ——
 *  在可核对的 ADM 已查出 135 处与管网几何不符，没有参考性。
 *  管网库没覆盖到的片区（艾因 AAM、西部区 DRM）如实说「无数据」，不拿台账凑。 */
export function networkRowHtml(p) {
  switch (p.qcap_basis) {
    case 'measured': // 250 m 内有管，且反算出了能力
    case 'uncomputable': // 250 m 内有管，只是缺高程/管径算不出能力
      return t('map.hasNetwork')
    case 'measured_no_network':
      return t('map.noNetwork')
    default: // no_coverage / unknown：这一片管网尚未导出，无从判断
      return t('map.noNetworkData')
  }
}

export function tooltipHtml(p, res, { inScope, lineLabel }) {
  const verdict = !inScope(p)
    ? t('map.outOfScope')
    : res
      ? lineLabel(res)
      : p.criticality
        ? t('map.critOf', { v: critLabel(p.criticality) })
        : t('map.unrated')
  return `<b>${p.uid}</b> · ${esc(p.location)}<br><span style="color:rgba(255,255,255,.55)">${esc(
    p.area,
  )} · ${verdict}</span>`
}

/** 罐车那一行：几辆 · 几车次 · 每辆几趟。
 *
 *  ⚠ 每辆跑不满一趟时 `tankers_required` 是 null，**不能印成 0 辆** ——
 *  0 会读成「不需要罐车」，实际含义是「这个时限下罐车根本来不及」。 */
function tankerCell(r) {
  if (!r.tanker_loads) return '—'
  if (r.tankers_required === null)
    return `<span style="color:var(--red)">${t('map.tankersNone')}</span>`
  return `<span style="color:var(--amber)">${t('map.tankersFmt', {
    n: fmt(r.tankers_required),
    loads: fmt(r.tanker_loads),
    trips: r.tanker_trips_per_vehicle,
  })}</span>`
}

export function popupHtml(p, r, { lineLabel, pumpBrief }) {
  const rows = [
    [t('map.rowBelongsTo'), `${esc(muniLabel(p.municipality))} · ${esc(p.area)}`],
    [
      t('map.rowDistrict'),
      p.district ? `${esc(p.district)} ${t('map.officialBoundary')}` : t('map.undecided'),
    ],
    [t('map.rowCrit'), critLabel(p.criticality)],
    [t('map.rowCause'), p.root_cause ? esc(causeLabel(p.root_cause)) : t('map.unfilled')],
    [t('map.rowNetwork'), networkRowHtml(p)],
    [
      t('map.rowNearestPipe'),
      p.nearest_pipe_m === null
        ? t('map.noNetworkDataShort')
        : p.nearest_pipe_m > 1000
          ? `${fmt(p.nearest_pipe_m / 1000, 1)} km`
          : `${fmt(p.nearest_pipe_m, 1)} m`,
    ],
    [
      t('map.rowElevation'),
      p.elevation_m === null
        ? '—'
        : `${fmt(p.elevation_m, 1)} m · ${p.idf_zone === 'adqcc_zone_a' ? 'Zone A' : 'Zone B'}`,
    ],
    [t('map.rowLedger'), t('map.ledgerFmt', { pumps: fmt(p.pumps_qty), tankers: fmt(p.tankers_qty) })],
  ]
  // 三道防线各自的答案 —— 点开地图上任一点，这几行就是结论本身。
  // 没跑过二维演算的点只给峰值诊断 + 一句「不出结论」：下面那几行在这个点上
  // 根本不存在，填 0 或 — 都会被读成「算过，没事」。
  if (r && r.line === null)
    rows.push(
      [t('map.rowPeak'), `${fmt(r.peak_flow_m3s, 2)} m³/s`],
      [t('map.rowVerdict'), `<span class="l">${lineLabel(r)}</span>`, true],
    )
  else if (r)
    rows.push(
      [t('map.rowPeak'), `${fmt(r.peak_flow_m3s, 2)} m³/s`],
      [t('map.rowRunoff'), `${fmt(r.runoff_volume_m3)} m³`],
      [
        t('map.rowLine1', { h: r.window_hours }),
        `${fmt(r.network_drained_m3)} m³${r.cleared_by_network ? t('map.drained') : ''}`,
      ],
      [
        t('map.rowLine2'),
        `${fmt(r.storage_used_m3)} m³${
          !r.cleared_by_network && r.cleared_by_storage ? t('map.absorbed') : ''
        }`,
      ],
      [
        t('map.rowLine3', { h: r.window_hours }),
        r.shortfall_m3 > 0
          ? `<span style="color:var(--amber)">${fmt(r.shortfall_m3)} m³ · ${pumpBrief(r)}</span>`
          : '—',
      ],
      // 罐车与泵**串联**（泵抽进车、车运走），两者同时都要 —— 单独一行而不是
      // 挤进上面那行，是因为要的是「派几辆、每辆跑几趟」，不是一个车次总数
      // （那只是体积换算）。⚠ 别把这一行读成「泵的替代方案」。
      [t('map.rowTankers'), tankerCell(r)],
      [t('map.rowVerdict'), lineLabel(r, true), true],
    )
  /* 数值行是左右两栏（标签靠左、值靠右，值不换行才对得齐小数点）；
     「结论」是一整句话，长度随泵数/罐车数变，两栏排版下它既撑破气泡宽度、
     又把左边的标签挤成竖排 —— 故整句单独占一块，标签在上、句子在下换行。 */
  return `<b>${p.uid} · ${esc(p.location)}</b><div style="margin-top:6px">${rows
    .map(([a, b, block]) =>
      block
        ? `<div class="pblock"><div class="pk">${a}</div><div class="pv wrap">${b}</div></div>`
        : `<div class="prow"><span class="pk">${a}</span><span class="pv">${b}</span></div>`,
    )
    .join('')}</div>`
}
