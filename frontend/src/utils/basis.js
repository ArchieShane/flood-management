/* 出处标签 —— 实测的点不能再被标成「假设」。
   标签色写在这里（不随语言变），短名与悬停解释走 i18n 的 `basis.*`。 */
import { t, tm } from '../i18n'
import { esc } from './format'

/** basis key → 标签色。`s` 绿 / `b` 蓝 / `w` 黄。 */
const QCAP_TONE = {
  measured: 's',
  measured_no_network: 'b',
  ledger_no_network: 'w',
  assumed_no_coverage: 'w',
  assumed_uncomputable: 'w',
  assumed: 'w',
}

const CATCHMENT_TONE = {
  measured: 's',
  measured_undeveloped: 'b',
  assumed_no_landuse: 'w',
  assumed: 'w',
}

const STORAGE_TONE = {
  measured: 's',
  measured_none: 'b',
  measured_no_asset: 'b',
  assumed_dimensions: 'w',
  assumed_no_coverage: 'w',
  assumed: 'w',
}

/** 积水量的归属口径（ponding_batch.py）。这一组没有「假设」档 ——
 *  要么演算过，要么整块没有，故兜底键是 `unknown` 而不是 `assumed`。 */
const PONDING_TONE = {
  in_depression: 's',
  routed: 'b',
  overland: 'w',
  unknown: 'w',
}

/** 四张表的形状一致：`kind` 只是选哪一组色与哪一段文案，`fallback` 是认不出时落哪一档。 */
export const QCAP_BASIS = { kind: 'qcap', tone: QCAP_TONE }
export const CATCHMENT_BASIS = { kind: 'catchment', tone: CATCHMENT_TONE }
export const STORAGE_BASIS = { kind: 'storage', tone: STORAGE_TONE }
export const PONDING_BASIS = { kind: 'ponding', tone: PONDING_TONE, fallback: 'unknown' }

/** 返回 `[标签色, 短名, 悬停解释]` —— 与原来的三元组同形，调用方不用改。 */
const pick = (map, key) => {
  const fb = map.fallback || 'assumed'
  const k = map.tone[key] ? key : fb
  const text = tm(`basis.${map.kind}.${k}`) || tm(`basis.${map.kind}.${fb}`)
  return [map.tone[k], text[0], text[1]]
}

export const qcapBasis = k => pick(QCAP_BASIS, k)
export const catchmentBasis = k => pick(CATCHMENT_BASIS, k)
export const storageBasis = k => pick(STORAGE_BASIS, k)
export const pondingBasis = k => pick(PONDING_BASIS, k)

/** 导出用：写成「短标签 —— 含义」，脱离页面也看得懂。
 *  未知的 basis 原样写回去，不硬套「假设」。 */
export const csvBasis = (map, k) => {
  if (!k) return ''
  if (!map.tone[k]) return k
  const b = pick(map, k)
  return t('csv.basisJoin', { label: b[1], hint: b[2] })
}

/** 出处标签的 HTML 串版本 —— 给那些整行拼 HTML 的地方（计算链、导出）用；
 *  在模板里能放组件的地方一律用 <BasisTag>。 */
export const basisTagHtml = (map, k) => {
  const b = pick(map, k)
  return `<span class="tag ${b[0]}" title="${esc(b[2])}">${esc(b[1])}</span>`
}
