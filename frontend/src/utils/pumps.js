/* 泵车口径 —— 「台」不是同一种泵：12″ 折减后 751 m³/h，6″ 只有 221。
   派车按「总排量 + 台数罚项」取最优（见 pumps.py），故总台数不随水量单调：
   50 年一遇 369 m³/h 派 2 台小型泵（442），100 年一遇 572 m³/h 反而是 1 台大型泵（751）——
   运力 442 → 751 是单调的，掉下去的只有台数。所以凡印单点结论处一律印口径，不印总数。

   ⚠ 印的是**通俗分级 + 口径 + 合计排量**（「2 台小型泵(6吋) · 442 m³/h」），不是裸口径：
   客户看「1 台 8 + 2 台 6」既不知道 8 指管径，也不知道两档差多少运力。分级词让他知道
   该调什么车，排量让他知道这些车抽得动多少 —— 台数本身反而是三者里最没信息量的一个。

   档位展示名（大型泵(12吋) 等）优先用后端随结果发回来的 `label` —— 后端已按 `?lang=`
   本地化过，这里的回落表只在还没算、拿不到 summary 时用。 */
import { t, tm } from '../i18n'

import { fmt } from './format'

/** 档位展示名：单点曲线的行自带 pump_tiers，批算的点回落到 summary。 */
export function tierLabelOf(key, row, summaryTiers = []) {
  const tiers = (row && row.pump_tiers) || summaryTiers || []
  const hit = tiers.find(t_ => t_.key === key)
  if (hit) return hit.label
  return (tm('pumps.fallbackTier') || {})[key] || key
}

/** 去掉口径括注的短名（`大型泵(12吋)` → `大型泵`），给地方紧的后缀用。 */
const shortTier = label => String(label).replace(/\s*[(（][^)）]*[)）]\s*$/, '') || String(label)

/** 拿不到额定排量时的回落次序 —— 大档在前，和后端 `dispatch()` 的 counts 一致。 */
const TIER_ORDER = ['12in', '8in', '6in', 'uniform']

/** 派了车的档，**一律大档在前**。单点的 counts 后端已排好，片区 / 全域这类
 *  聚合行是逐点累加进 dict 的，顺序随先遇到哪一档而定，必须在这里重排。 */
const activeTiers = (row, summaryTiers = []) => {
  const by = (row && row.pumps_by_tier) || null
  if (!by) return []
  const tiers = (row && row.pump_tiers) || summaryTiers || []
  const rate = key => {
    const hit = tiers.find(t_ => t_.key === key)
    return hit && Number.isFinite(hit.rated_m3hr) ? hit.rated_m3hr : null
  }
  const fallback = key => (TIER_ORDER.indexOf(key) < 0 ? TIER_ORDER.length : TIER_ORDER.indexOf(key))
  return Object.entries(by)
    .filter(([, n]) => n > 0)
    .sort(([a], [b]) => {
      const ra = rate(a)
      const rb = rate(b)
      return ra !== null && rb !== null ? rb - ra : fallback(a) - fallback(b)
    })
}

/** 派出去的合计排量。单点结果后端直接给 `pump_deployed_m3hr`；
 *  片区 / 全域这类聚合行没有该字段，按各档台数 × 额定排量累加。
 *  有一档查不到额定排量就返回 null —— 宁可不印，也不要印一个偏小的总数。 */
function deployedRate(row, summaryTiers = []) {
  if (row && Number.isFinite(row.pump_deployed_m3hr)) return row.pump_deployed_m3hr
  const tiers = (row && row.pump_tiers) || summaryTiers || []
  let sum = 0
  for (const [key, n] of activeTiers(row, summaryTiers)) {
    const hit = tiers.find(t_ => t_.key === key)
    if (!hit || !Number.isFinite(hit.rated_m3hr)) return null
    sum += n * hit.rated_m3hr
  }
  return sum || null
}

/** 「2 台小型泵(6吋) · 442 m³/h」「1 台大型泵(12吋) + 1 台中型泵(8吋) · 1,039 m³/h」
 *  —— 没有分档数据时才退回总台数，拿不到额定排量时才省掉排量。 */
export function pumpBrief(row, summaryTiers = []) {
  // `pumps_required` 为 null = 这个点没跑过二维演算，三道防线不出结论。
  // 不能落到下面的 `|| 0` —— 那会把「没算」印成「0 台泵」，即「不需要派车」。
  if (row && row.pumps_required === null) return t('pumps.uncalibrated')
  const e = activeTiers(row, summaryTiers)
  const brief = e.length
    ? e
        .map(([k, n]) => t('pumps.nOfTier', { n, tier: tierLabelOf(k, row, summaryTiers) }))
        .join(' + ')
    : t('pumps.nPumps', { n: (row && row.pumps_required) || 0 })
  const rate = deployedRate(row, summaryTiers)
  return rate ? t('pumps.withRate', { brief, rate: fmt(rate) }) : brief
}

/** 给「N 台泵」这类数字槽补一个口径后缀，不夺走原来的大数字。
 *  这里用短名：后缀跟在数字下方的单位行里，塞不下括注。
 *
 *  单档（页面自定义单泵能力）时返回空串 —— 那时后缀只会写成「3×移动泵」，
 *  和它跟着的那个「3 台泵」一字不差，纯属占地方。 */
export function pumpTierSuffix(row, summaryTiers = []) {
  const e = activeTiers(row, summaryTiers)
  if (!e.length || (e.length === 1 && e[0][0] === 'uniform')) return ''
  return t('pumps.tierSuffix', {
    list: e.map(([k, n]) => `${n}×${shortTier(tierLabelOf(k, row, summaryTiers))}`).join(' + '),
  })
}
