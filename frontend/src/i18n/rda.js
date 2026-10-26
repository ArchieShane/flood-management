/* RD-A 全套成果页（views/RdaView.vue）的英文词典。

   和 zh.js / en.js 的「逐键对照」不同，这一页展示的有一半是**成果文件里的中文字段**（设施类型、
   审批事项、合规检查名、L3 结论……），它们不是代码里的键，所以沿用后端 `i18n.EN` 的做法：
   `tr('…')` 精确匹配；带数字的动态串用 `{x}` 占位；匹配不上再试正则，再试短语替换；
   都不中就原样显示中文 —— 宁可漏一句中文，也不吞掉成果里的口径说明。

   ⚠ 协议值不在这里翻：后果等级（关键 / 高 / 中 / 无暴露）、L3 结论等在页面里仍是颜色表的键，
   只在**显示**时过 tr()。改了页面里的中文原串，这里的键要跟着改（`scripts/check-rda-i18n.mjs` 会查）。 */
import { locale } from './index'

const EN = {
  // —— 页面骨架 ——
  'RD-A 全套成果': 'RD-A full result set',
  'RD-A 61 mm / 1 h 全套成果': 'RD-A 61 mm / 1 h full result set',
  'SWMM 5.2 一维管网 + ANUGA 二维地表双向耦合（15 m 网格，65,210 个单元），模拟 11.0 h（雨后再算 10 h）':
    'SWMM 5.2 1D network + ANUGA 2D surface, two-way coupled (15 m grid, 65,210 cells), 11.0 h simulated (10 h after the rain)',
  '。降雨': '. Rainfall',
  '，5 分钟峰值': ', 5-minute peak',
  '暴雨': 'Storm',
  '本次交付只有这一场雨': 'This delivery has only this storm',
  '热点四项全过（{n} 个）：': 'Hotspots passing all four tests ({n}): ',
  '热点达标': 'Hotspots passed',
  '热点达标（A–C 全过）': 'Hotspots passed (A–C all met)',
  '读取中…': 'Loading…',
  'RDA 成果读取失败：': 'Failed to load the RDA results: ',
  '没有找到 RDA 成果：': 'RDA results not found: ',
  '积水点重算失败：': 'Ponding recompute failed: ',
  '连片面积和持续时间要填非负数': 'Contiguous area and duration must be non-negative numbers',

  // —— 状态与防线 ——
  'L1 现状': 'L1 Existing',
  'L2 雨前预置泵': 'L2 Pre-placed pumps',
  'L2+planned 客户计划': 'L2+planned Client plan',
  'L2+suggested 我们的方案': 'L2+suggested Our scheme',
  'L2+suggested 新增': 'L2+suggested additions',
  'L2 雨前预置': 'L2 pre-placed',
  'L1': 'L1',
  '第一道防线 · 现状永久管网': '1st line · existing permanent network',
  '第二道防线 · 雨前预置移动泵': '2nd line · mobile pumps placed before the rain',
  '第二道防线 · 客户已有计划（视同建成）': '2nd line · client\'s existing plan (treated as built)',
  '第二道防线 · 我们的建议方案': '2nd line · our proposed scheme',
  'L2+suggested 我们的方案 · ': 'L2+suggested Our scheme · ',

  // —— 地图 / 图层 / 播放 ——
  '最大水深': 'Max depth',
  '积水范围': 'Ponding extent',
  '积水点': 'Ponding points',
  '设施': 'Facilities',
  '客户热点': 'Client hotspots',
  '自定义': 'Custom',
  '积水点（后果等级）': 'Ponding points (consequence level)',
  '播放': 'Play',
  '暂停': 'Pause',
  '此刻 ≥0.10 m': 'now ≥0.10 m',
  '最深': 'deepest',
  '逐帧': 'Frame by frame',
  '全程最大水深': 'Max depth overall',
  '和对比基准的差': 'Difference vs baseline',
  '排口': 'Outfall',
  '{id} · 最深 {d} m · 峰值 {v} m³': '{id} · deepest {d} m · peak {v} m³',
  '客户热点 {id} · {c} · {r}': 'Client hotspot {id} · {c} · {r}',

  // —— 标签页 ——
  '概览': 'Overview',
  '打开': 'Open',
  'RD-A 完整页（逐帧播放 · 概览）': 'RD-A full page (frame playback · overview)',
  '四个状态（L1 / L2 / L2+planned / L2+suggested）的二维结果、积水点、L3 派单、设施与 {n} 项建议措施。':
    '2D results, ponding points, L3 dispatch, facilities and {n} proposed measures for the four states (L1 / L2 / L2+planned / L2+suggested).',
  'L3 派单': 'L3 dispatch',
  '判据': 'Criteria',
  'Suggested 措施': 'Suggested measures',

  // —— 概览 ——
  '对比基准': 'Baseline',
  '上一个态': 'Previous state',
  '当前对比：': 'Comparing with: ',
  '（这个态没有可比的基准）': '(no baseline to compare with)',
  '对比': 'vs',
  '全域 · ≥0.30 m 积水面积': 'Whole domain · area ≥0.30 m',
  '{n} 个热点 200 m 内 · ≥0.30 m': 'Within 200 m of {n} hotspots · ≥0.30 m',
  '全域 · 最大积水量': 'Whole domain · peak ponded volume',
  '{n} 个热点 200 m 内最大水深': 'Max depth within 200 m of {n} hotspots',
  '过': 'Pass',
  '不过': 'Fail',
  'D：不比 planned 加深': 'D: no deeper than planned',
  '积水点 ≥0.15 / ≥0.30 m': 'Ponding points ≥0.15 / ≥0.30 m',
  '模拟结束仍积水 m³': 'Still ponded at end of run (m³)',
  '水深逐帧 · 全域积水 ≥0.10 m 面积（ha）': 'Depth by frame · domain area ≥0.10 m (ha)',
  '本态': 'This state',
  '无基准': 'no baseline',
  '拖地图下方的滑条或点 ▶ 看逐帧。面积含塘占地。': 'Drag the slider under the map or press ▶ to step through frames. Area includes pond footprints.',
  '降雨（雨型）': 'Rainfall (hyetograph)',
  '最大 5 分钟雨强': 'Max 5-min intensity',
  '前后': 'around',
  '净雨': 'net rain',
  '造价（占位，当前方案）': 'Cost (placeholder rates, current scheme)',
  '合计造价': 'Total cost',
  '措施数': 'Measures',
  '项': 'items',
  '新建排海口': 'New sea outfalls',
  '设施类型': 'Facility type',
  '数量': 'Count',
  '各热点': 'Hotspots',
  '热点': 'Hotspot',
  '200 m 内 ≥0.30 m（ha）': '≥0.30 m within 200 m (ha)',
  '200 m 内最深（m）': 'Deepest within 200 m (m)',
  '50 m 内 ≥0.30 m 时长（h）': 'Hours ≥0.30 m within 50 m',
  '彩色数是和对比基准之差（绿 = 改善）。积水面积不含塘占地。ADM-80 在汇水区南边界外，客户 PDF 也写了「无管网」。':
    'Coloured numbers are the difference from the baseline (green = better). Ponded area excludes pond footprints. ADM-80 lies outside the southern edge of the catchment; the client PDF also says "no network".',
  '{n} 个热点：水深过程': '{n} hotspots: depth over time',
  '模拟末': 'at end',
  '曲线 = 热点 50 m 内最深的水深，每 5 分钟一个值；蓝线是当前态，灰线是对比基准，红虚线 0.30 m。':
    'Curve = deepest water within 50 m of the hotspot, one value per 5 minutes; blue is the current state, grey the baseline, red dashed line 0.30 m.',
  '这个态包含的设施': 'Facilities in this state',
  '形状、颜色分设施类型；虚线 = 排水去向，黑点 = 排到的位置；点设施看设计参数和当前态的实际表现。':
    'Shape and colour show the facility type; dashed line = where the water goes, black dot = discharge point; click a facility for its design parameters and how it performed in this state.',
  '四个状态对比': 'The four states compared',
  '状态': 'State',
  '积水点 0.15/0.30': 'Ponding points 0.15/0.30',
  '积水点是怎么定的': 'How ponding points are defined',
  '最大水深 ≥ 阈值的单元按三角网共边连成片，去掉本状态地表塘占地，再去掉面积 < 100 m²、持续 < 0.5 h 的片；峰值积水量取逐帧 Σ(水深×单元面积) 的最大值。阈值为试算值，尚未与客户对齐。':
    'Cells whose max depth is at or above the threshold are joined into patches along shared triangle edges; this state\'s surface pond footprints are removed, then patches under 100 m² or lasting under 0.5 h are dropped. Peak volume is the maximum over frames of Σ(depth × cell area). Thresholds are trial values, not yet agreed with the client.',
  '造价是占位单价，用于方案比较，不是工程概算；设施位置落地前仍需现场核实和主管部门许可。':
    'Costs use placeholder unit rates for comparing schemes; they are not an engineering estimate. Facility locations still need site verification and authority approval before construction.',

  // —— 积水点页 ——
  '积水点阈值': 'Ponding thresholds',
  '水深 ≥': 'Depth ≥',
  '连片 ≥': 'Contiguous ≥',
  '持续 ≥': 'Lasting ≥',
  '重算': 'Recompute',
  '已按所给阈值从二维结果重算：三角网共边连片，不扣地表塘占地，没有 L3 承接与评估剔除标记。':
    'Recomputed from the 2D results with the thresholds above: patches joined along shared triangle edges, surface pond footprints not removed, no L3 hand-over or exclusion-zone flags.',
  '现在是成果自带的清单（0.15 / 0.30 m，100 m²，0.5 h；含 L3 承接与剔除标记）。改任一阈值再点「重算」会从二维结果现算。':
    'This is the list shipped with the results (0.15 / 0.30 m, 100 m², 0.5 h; with L3 hand-over and exclusion flags). Change any threshold and press "Recompute" to compute from the 2D results.',
  '回到成果自带': 'Back to the delivered list',
  '全部': 'All',
  '未退': 'Not receded',
  '已退': 'Receded',
  '要 L3': 'Needs L3',
  '剔除区': 'Excluded',
  '剔': 'Ex',
  '{n} 片 · 峰值合计 {v} m³ · 未退 {k}': '{n} patches · peak total {v} m³ · {k} not receded',
  '只看客户热点 200 m 内': 'Only within 200 m of a client hotspot',
  '编号 SIM-态-序号是模型算出的积水点，不是客户热点；按峰值积水量降序，只在同一状态、同一阈值内有效。':
    'SIM-state-number IDs are ponding points found by the model, not client hotspots; sorted by peak volume, valid only within the same state and thresholds.',
  '评估剔除区': 'Assessment exclusion zone',
  '地面高程': 'ground level',
  '面积': 'Area',
  '其中': 'of which',
  '峰值积水量': 'Peak volume',
  '出现在': 'at',
  '持续': 'Duration',
  '退水': 'Recession',
  '峰值后': 'after peak',
  '到 {t} h 仍有 {v} m³': 'still {v} m³ at {t} h',
  '最近客户热点': 'Nearest client hotspot',
  '200 m 内热点': 'Hotspots within 200 m',
  '覆盖的客户热点': 'Client hotspots covered',
  '覆盖是怎么算的（口径）': 'How coverage is computed',
  '热点覆盖率（被覆盖热点数 / {n}）': 'Hotspot coverage rate (covered hotspots / {n})',
  '积水量覆盖率（热点 200 m 内的积水量占比）': 'Volume coverage rate (share of ponded volume within 200 m of a hotspot)',
  '覆盖热点': 'Hotspots covered',
  '热点覆盖率': 'Hotspot coverage',
  '积水量覆盖率': 'Volume coverage',
  '覆盖率': 'Coverage rate',
  '热点覆盖率 = 被覆盖的热点数 ÷ 热点总数（11）；积水量覆盖率 = 热点 200 m 内的积水量 ÷ 全部积水量，两个都不含被剔除的片。上面的小表是四个状态在同一套阈值下的并排对比，当前状态高亮。':
    'Hotspot coverage = covered hotspots ÷ total hotspots (11); volume coverage = ponded volume within 200 m of a hotspot ÷ all ponded volume; neither counts dropped patches. The small table above compares the four states under the same thresholds, with the current state highlighted.',
  '不计入的片': 'Patches not counted',
  '占比': 'Share',
  '不是什么': 'What it is not',
  '当前状态的二维结果里，全程最大水深 ≥ 阈值的单元按三角网共边连成片，去掉面积不足连片下限、持续不足时长下限的片；阈值就是上面「积水点阈值」那一栏（成果自带 0.15 / 0.30 m、100 m²、0.5 h）。':
    'In the current state\'s 2D result, cells whose whole-run maximum depth reaches the threshold are joined into patches along shared triangle edges; patches below the minimum area or minimum duration are dropped. The thresholds are those in the "Ponding thresholds" box above (delivered: 0.15 / 0.30 m, 100 m², 0.5 h).',
  '客户热点（RD-A 交付的 11 个，只有坐标）到某个积水点的距离 ≤ 200 m，就算这个积水点覆盖了该热点；距离取热点到片内最近单元形心。同一热点可被几个点覆盖，表里按距离由近到远列出。':
    'A client hotspot (the 11 delivered with RD-A, coordinates only) is covered by a ponding point when the distance from the hotspot to the nearest cell centroid of that patch is ≤ 200 m. One hotspot can be covered by several points; the table lists them nearest first.',
  '这一状态下热点 200 m 内已经没有达标的积水点，意思是该处不再积水或积得不够深、不够久，不是「没有算到」。':
    'In this state no qualifying ponding point is left within 200 m of the hotspot: the spot no longer ponds, or not deep or long enough. It does not mean "not computed".',
  '一半以上面积落在评估剔除区内的积水片不计入覆盖，也不进下面的占比（与客户重合分析文档同口径）。剔除区有两处：ADM-80 岸边约 9.7 ha 的 DTM 高程恰为 0.00 m（判为缺测填零），ADM-161 东侧私人地块的深坑。':
    'Patches with more than half of their area inside an assessment exclusion zone are not counted for coverage or for the share below (same rule as the client overlap analysis). There are two zones: about 9.7 ha of DTM at exactly 0.00 m on the ADM-80 shore (treated as missing data filled with zero) and a deep pit in a private plot east of ADM-161.',
  '「热点 200 m 内」的积水量 = 这些积水点的峰值积水量之和，除以全部（不含被剔除的）积水点的峰值积水量之和；每个点只算一次。各点峰值时刻不同，所以这是量级参考，不是某一时刻的水量。按整片算：只要一片有一部分在热点 200 m 内，整片的水量都计入分子，不是只算 200 m 圈内的那部分水，所以这个比例偏乐观，圈内的实际水量比它小。':
    '"Within 200 m of a hotspot" volume = the sum of peak ponded volumes of those points, divided by the sum over all points (excluding dropped patches); each point counts once. Peaks occur at different times, so this is an order-of-magnitude reference, not the volume at one instant. Whole patches are counted: if any part of a patch lies within 200 m of a hotspot, its entire volume goes into the numerator, not just the water inside the 200 m circle, so the share is optimistic and the actual volume inside the circles is smaller.',
  '这只是空间位置的比对，不是模型验证：热点没有水深、范围和发生日期，模型也没有率定。「覆盖 x / 11」与「判据」页的 A / B / C 达标不是一回事，也不等于积水面积的削减比例。':
    'This only compares locations and is not model validation: the hotspots have no depth, extent or date, and the model is not calibrated. "Covered x / 11" is not the same as the A / B / C pass marks on the Criteria tab, nor the reduction in ponded area.',
  '热点 200 m 内 {a} 片 / {n} 片，积水量 {v} m³，占 {p}%；其余 {q}% 在热点范围之外。':
    '{a} of {n} patches lie within 200 m of a hotspot, {v} m³, {p}% of the ponded volume; the other {q}% is outside hotspot range.',
  '已不计入 {n} 片：一半以上面积落在评估剔除区内（列表里标「剔」），与客户重合分析文档同口径。':
    '{n} patch(es) not counted: more than half of their area lies in an assessment exclusion zone (marked "Ex" in the list), same rule as the client overlap analysis.',
  '一半以上面积落在评估剔除区内，不计入热点覆盖': 'More than half of the area is in an exclusion zone; not counted for hotspot coverage',
  '多半在剔除区': 'Mostly in exclusion zone',
  '按当前状态、当前阈值算出的积水点，200 m 内有积水点即算覆盖该热点；未覆盖 = 这一态下热点周边已没有达标的积水点。点编号可定位。':
    'Computed for the current state and thresholds: a hotspot is covered when a ponding point lies within 200 m of it; not covered = no qualifying ponding point is left around it in this state. Click a point ID to locate it.',
  '覆盖': 'Covered',
  '未覆盖': 'Not covered',
  '覆盖它的积水点（距离）': 'Ponding points covering it (distance)',
  '无': 'None',
  '剔除说明': 'Exclusion note',
  '扣除后': 'after deduction',
  '连片方式': 'Joining method',
  '三角网共边': 'shared triangle edges',
  '单元近邻近似': 'nearest-cell approximation',
  'L3 承接': 'L3 hand-over',
  '结论': 'Verdict',
  '定级依据': 'Grading basis',
  'L3 手段': 'L3 measure',
  '退干期限': 'Drain deadline',
  '自然退干': 'Natural drainage',
  '300 m 内单位': 'Sites within 300 m',
  'ADM 全驻地': 'All ADM depots',
  '台/辆': 'units',
  '到位': 'on site',
  '完成': 'done',
  '备注': 'Note',
  '编号': 'ID',
  '最大水深 m（时刻）': 'Max depth m (time)',
  '最大面积 m²（时刻）': 'Max area m² (time)',
  '最大积水量 m³（时刻）': 'Max volume m³ (time)',
  '最大积水面积': 'Max ponded area',
  '最深 m': 'Deepest m',
  '面积 m²': 'Area m²',
  '峰值 m³': 'Peak m³',
  '等级': 'Level',

  // —— L3 ——
  'L3 承接与派单': 'L3 hand-over and dispatch',
  '进入 L3 的残余积水点': 'Residual ponding points passed to L3',
  '自然退干达标': 'Drain naturally in time',
  '需 L3 处置': 'Need L3 action',
  '超出 L3 单点能力（应由 L2 解决）': 'Beyond L3 single-point capacity (L2 must solve)',
  '无暴露，只监测': 'No exposure, monitor only',
  '超出能力的峰值积水量 m³': 'Peak volume beyond capacity (m³)',
  '后果等级': 'Consequence level',
  '调度结果': 'Dispatch result',
  '调度范围': 'Dispatch scope',
  '结果': 'Result',
  '泵/车': 'Pumps / tankers',
  '成本 AED': 'Cost (AED)',
  '{p} 泵 / {t} 罐车': '{p} pumps / {t} tankers',
  '派单口径：': 'Dispatch basis: ',
  '未进入 L3 清单的积水点': 'Ponding points not in the L3 list',
  '这个状态没有 L3 承接汇总。': 'This state has no L3 hand-over summary.',
  '关键': 'Critical',
  '高': 'High',
  '中': 'Medium',
  '无暴露': 'No exposure',
  'L3 已派、超时': 'L3 dispatched, late',
  'L3 按时退干': 'L3 drained on time',
  'L3 未派': 'L3 not dispatched',
  '只监测': 'Monitor only',
  '12 英寸泵': '12-inch pump',
  '无需': 'None needed',
  '罐车': 'Tanker',
  '超出 L3 单点能力': 'Beyond L3 single-point capacity',
  'L3 可承接': 'L3 can handle',
  'L3 可承接（关键点，建议 L2 兜住）': 'L3 can handle (critical point; L2 should back it up)',
  '无暴露，只监测（不派 L3）': 'No exposure, monitor only (no L3)',
  '自然退干达标，不需 L3': 'Drains naturally in time, no L3 needed',
  '超出 L3 → 应由 L2 解决': 'Beyond L3 → L2 must solve',
  '仅 Island 片区（A13，现状）': 'Island zone only (A13, as-is)',
  'ADM 全部驻地集中调度（上限）': 'All ADM depots, centrally dispatched (upper bound)',
  '二维残余积水片（≥0.15 m、≥100 m²、≥0.5 h），剔除塘占地和 DTM 填 0 / 私人地块坑':
    '2D residual ponding patches (≥0.15 m, ≥100 m², ≥0.5 h), excluding pond footprints and DTM zero-fill / private-plot pits',
  'swbrain.dispatch2 滚动 MILP（平衡目标），路网 Dijkstra 行程，退水重演；预案 A 车队':
    'swbrain.dispatch2 rolling MILP (balanced objective), road-network Dijkstra travel, recession replayed; Plan A fleet',
  '第一个积水点成形（>50 m³）时开始派单，此后每 60 min 滚动一次':
    'Dispatch starts when the first ponding point forms (>50 m³), then rolls every 60 min',
  '落在评估剔除区（DTM 填 0 / 私人地块坑），扣除后不足 100 m²，判据评估和 L3 都不算':
    'Falls in the assessment exclusion zone (DTM zero-fill / private-plot pit); under 100 m² after deduction, so neither the criteria nor L3 count it',

  // —— 设施页 ——
  '设施图层': 'Facility layer',
  '逐级累加：每个状态包含前面各状态的全部设施。': 'Cumulative: each state includes all facilities of the states before it.',
  '类型': 'Type',
  '流量': 'Flow',
  '池容': 'Tank volume',
  '有效水深 / 池底': 'Effective depth / invert',
  '泵台数': 'Pumps',
  '管长': 'Pipe length',
  '泵规格': 'Pump size',
  '开 / 停泵水位': 'Pump on / off level',
  '服务热点': 'Hotspot served',
  '说明': 'Description',
  '本场模拟里的实际表现': 'Performance in this simulation',
  '累计处理水量': 'Total volume handled',
  '利用率': 'Utilisation',
  '池内最大蓄水': 'Max stored in tank',
  '满': 'full',
  '设施清单': 'Facility list',
  '层级': 'Level',
  '流量 L/s': 'Flow L/s',
  '流量 m³/s': 'Flow m³/s',
  '池容 m³': 'Tank m³',
  '现状泵站': 'Existing pumping station',
  '雨前预置移动泵': 'Pre-placed mobile pump',
  '客户计划泵站': 'Client-planned pumping station',
  '地下调蓄池': 'Underground storage tank',
  '重力管（截流井→调蓄池）': 'Gravity pipe (intercept well → tank)',
  '压力输水（泵→排口）': 'Pressure main (pump → outfall)',
  '地面取水口 / 洼坑': 'Surface intake / sump',
  '地面取水泵站': 'Surface intake pumping station',

  // —— 判据 ——
  '四项判据': 'Four criteria',
  '热点 200 m 内，四项全过才算达标。': 'Within 200 m of a hotspot, all four must be met.',
  '热点 200 m 内无 ≥0.30 m 积水': 'No ponding ≥0.30 m within 200 m of the hotspot',
  '≥0.15 m 面积×时间 ≤ L2+planned 的 10 %': '≥0.15 m area × time ≤ 10 % of L2+planned',
  '雨停后 6 h 内退到 0.10 m 以下': 'Back below 0.10 m within 6 h after the rain stops',
  '比 L2+planned 加深的面积 ≤ 0.05 ha（域级）': 'Area deeper than L2+planned ≤ 0.05 ha (domain level)',
  '最大 m': 'Max m',
  '退到 0.10 m': 'Back to 0.10 m',
  '≥0.15 ha·h 一列斜杠后是 L2+planned 基准。': 'In the ≥0.15 ha·h column the number after the slash is the L2+planned baseline.',
  'D 域级': 'D (domain)',
  '比 planned 加深 ha': 'Deeper than planned (ha)',
  '比 planned 变浅 ha': 'Shallower than planned (ha)',
  '全域峰值积水量 m³': 'Domain peak ponded volume (m³)',

  // —— Suggested 措施 ——
  '全部措施': 'All measures',
  '占位造价': 'Placeholder cost',
  '百万美元': 'M USD',
  '怎么排水': 'How it drains',
  '设计参数': 'Design parameters',
  '截流井': 'Intercept well',
  '截流井溢流量': 'Intercept-well overflow',
  '96 mm 两场取大': 'larger of the two 96 mm storms',
  '开挖深度': 'Excavation depth',
  '泵': 'Pumps',
  '台': '',
  '设计流量': 'Design flow',
  '泵站场地': 'Pumping-station site',
  '压力管': 'Pressure main',
  '重力管': 'Gravity pipe',
  '根': 'pipes',
  '造价依据': 'Cost basis',
  '累计处理': 'Total handled',
  '成果里没有这项措施的逐场表现。': 'The results have no per-storm performance for this measure.',
  '需审批 / 许可': 'Approvals / permits needed',
  '缺数据判不了': 'Cannot judge: data missing',
  'WA-726 与空间约束检查': 'WA-726 and spatial-constraint checks',
  '共 {n} 项：': '{n} checks: ',
  '通过': 'passed',
  '需复核': 'to review',
  '缺数据': 'no data',
  '显示全部（默认只列需复核 / 缺数据）': 'Show all (by default only those to review / lacking data)',
  '{n} 项措施': '{n} measures',
  '新增措施（项）': 'New measures',
  '占位造价 百万美元': 'Placeholder cost, M USD',
  '全寿命 NPV 5% 百万美元': 'Whole-life NPV at 5 %, M USD',
  '按类型': 'By type',
  '占比': 'Share',
  '全寿命成本（NPV）': 'Whole-life cost (NPV)',
  '方案': 'Scheme',
  '建设': 'Build',
  '运维/年': 'O&M / yr',
  '单位：百万美元。造价分项：': 'Unit: M USD. Cost breakdown: ',
  '逐项措施（点一行定位并看设计参数 / 怎么排水 / 合规）': 'Measures (click a row to locate it and see design parameters / drainage / compliance)',
  '地面取水口（{n}）': 'Surface intakes ({n})',
  '取水口': 'Intake',
  '泵站': 'Pumping station',
  '类别': 'Category',
  '坑底 m': 'Pit floor m',
  '取水 m³/s': 'Intake m³/s',
  '到泵站 m': 'To pump station m',
  '地面洼坑': 'Surface depression',
  '隧道引道': 'Tunnel approach',
  '截流井 {w} 的溢流重力进入地下池': 'Overflow from intercept well {w} flows by gravity into the underground tank',
  '池容 {v} m³、有效水深 {d} m、池底 {f} m、开挖 {e} m': 'Volume {v} m³, effective depth {d} m, invert {f} m, excavation {e} m',
  '雨后由排空泵自动排回管网': 'After the rain a drain-down pump empties it back to the network automatically',
  '{n} 台泵 × {q} m³/s（设计流量 {d} m³/s）': '{n} pumps × {q} m³/s (design flow {d} m³/s)',
  '压力管 {l} m、DN{d}×{p}、峰值流速 {v} m/s': 'Pressure main {l} m, DN{d}×{p}, peak velocity {v} m/s',
  '重力管（截流井→池）{l} m、DN{d}': 'Gravity pipe (intercept well → tank) {l} m, DN{d}',
  '排到新建排海口 {o}': 'Discharges to new sea outfall {o}',
  '造价是占位单价，用于方案比较，不是工程概算；位置已按 WA-726 规则、用地和地下管线约束筛过，落地前仍需现场核实和主管部门许可。':
    'Costs use placeholder unit rates for comparing schemes; they are not an engineering estimate. Locations were screened against WA-726 rules, land use and underground-utility constraints, but still need site verification and authority approval before construction.',

  // —— 成果里的有限集合 ——
  '重力进水地下调蓄池': 'Gravity-fed underground storage tank',
  '井边泵站 + 地下调蓄池': 'Well-side pumping station + underground tank',
  '泵站 → 新建排海口': 'Pumping station → new sea outfall',
  '地面泵站 → 新建排海口': 'Surface pumping station → new sea outfall',
  '有条件可建': 'Buildable with conditions',
  '压力管、排海口按 WA-726 第三卷 p349 单价；泵站、湿井、取水井：占位':
    'Pressure main and outfall at WA-726 Vol. 3 p349 unit rates; pumping station, wet well, intake well: placeholder',
  '压力管、排海口按 WA-726 第三卷 p349 单价；泵站、湿井、重力连接管：占位':
    'Pressure main and outfall at WA-726 Vol. 3 p349 unit rates; pumping station, wet well, gravity link: placeholder',
  '压力管按 WA-726 第三卷 p349 单价；池体、泵站、湿井：占位':
    'Pressure main at WA-726 Vol. 3 p349 unit rates; tank, pumping station, wet well: placeholder',
  '池体 350 USD/m³、重力管、排空泵：占位单价': 'Tank 350 USD/m³, gravity pipe, drain-down pump: placeholder rates',
  'L2+suggested（v3 + 7 座地面泵站）': 'L2+suggested (v3 + 7 surface pumping stations)',
  'v3（无地面泵站）': 'v3 (no surface pumping stations)',
  '地下池池体': 'Underground tank body',
  '泵站土建（站房、湿井、取水井）': 'Pumping-station civil works (building, wet well, intake well)',
  '机电（水泵、排空泵）': 'Mechanical & electrical (pumps, drain-down pumps)',
  '压力管（含排气阀）': 'Pressure main (incl. air valves)',
  '排海口': 'Sea outfall',
  '重力连接管': 'Gravity link pipe',
  '无排水管网': 'No drainage network',
  '管网能力不足/需升级': 'Network capacity short / needs upgrading',

  // 审批 / 缺数据（按「；」拆开后逐条匹配）
  '下穿通道是否已有现状泵站': 'Whether the underpass already has an existing pumping station',
  '场地平面须经 DPM 与城市规划批准': 'Site layout needs DPM and urban-planning approval',
  '开发商用地外：需主管部门和业主许可': 'Outside developer land: needs authority and owner permission',
  '新建排海口：EAD 写明位置的专项批准 + TCA-AD 考古报告': 'New sea outfall: EAD location-specific approval + TCA-AD archaeology report',
  '池底低于 0 m NADD 须地下水资料': 'Tank floor below 0 m NADD needs groundwater data',
  '池底低于 0 m NADD 须地下水资料（抗浮 / 降水）': 'Tank floor below 0 m NADD needs groundwater data (uplift / dewatering)',
  '用地许可': 'Land-use permission',
  '管位预留（Service Reservation）须经城市规划批准': 'Service Reservation needs urban-planning approval',
  '与建筑基础净宽 ≥ B（图 4-1）': 'Clear width to building foundations ≥ B (Fig. 4-1)',
  '与现状管线平面净距 ≥ 500 mm': 'Horizontal clearance to existing utilities ≥ 500 mm',
  '重力优先：只有重力接不上才可设泵站，并做 NPV 比选': 'Gravity first: a pumping station only where gravity cannot connect, with an NPV comparison',

  // WA-726 / 空间约束检查项名
  '上游止回阀井，盖板高于 HAT（+1.3 m）': 'Upstream non-return valve chamber, cover above HAT (+1.3 m)',
  '单泵 >180 L/s 用矩形湿井': 'Rectangular wet well for pumps >180 L/s',
  '地面独立电气房 + 重型车辆可进出的场地': 'Separate above-ground electrical room + site reachable by heavy vehicles',
  '容积比所需大 5 %（积砂）': 'Volume 5 % above requirement (sediment)',
  '峰值流速 ≤ 2.0 m/s': 'Peak velocity ≤ 2.0 m/s',
  '已开发区内或附近不建开敞塘': 'No open pond in or near developed areas',
  '总能力 ≥ 设计流量 × 1.1；坏一台时 ≥ 66 %': 'Total capacity ≥ 1.1 × design flow; ≥ 66 % with one pump out',
  '排口离滨水保护线 ≥ 50 m': 'Outfall ≥ 50 m from the waterfront protection line',
  '排口设拍门 / 鸭嘴阀 / 锥形止回阀': 'Outfall fitted with flap / duckbill / cone non-return valve',
  '排海管管顶低于 MLLW（−0.7 m NADD）': 'Sea-outfall pipe soffit below MLLW (−0.7 m NADD)',
  '排空泵供电 ≤ 1 km': 'Drain-down pump power supply ≤ 1 km',
  '材质：球墨铸铁 / GRP / HDPE': 'Material: ductile iron / GRP / HDPE',
  '池边离建筑 ≥ B + 作业带': 'Tank edge to buildings ≥ B + working strip',
  '泵站供电 ≤ 1 km': 'Pumping-station power supply ≤ 1 km',
  '泵站场地不积水': 'Pumping-station site does not flood',
  '泵站场地临路（≤ 20 m）': 'Pumping-station site next to a road (≤ 20 m)',
  '泵站场地临路（≤ 20 m，重型车辆进出）': 'Pumping-station site next to a road (≤ 20 m, heavy-vehicle access)',
  '湿井有效容积 ≥ 0.25·Q·T': 'Wet-well effective volume ≥ 0.25·Q·T',
  '湿井深 ≤ 10 m': 'Wet-well depth ≤ 10 m',
  '至少 2 台同型号泵': 'At least 2 pumps of the same model',
  '重力能进水、开挖 ≤ 8 m': 'Gravity inflow possible, excavation ≤ 8 m',
  '雨后立即自动排空（重力回流或泵回管网）': 'Empties automatically right after the rain (gravity return or pumped back to the network)',

  // 取水口说明 / 合规 detail 里的整句
  '初步设计阶段就要': 'Needed at preliminary design',
  '圆形可': 'Circular is acceptable',
  '矩形': 'Rectangular',
  '缺 clearance_to_building_m / depth_m / diameter_mm': 'Missing clearance_to_building_m / depth_m / diameter_mm',
}

// —— 带数字的整句（正则）——
const PATTERNS = [
  [/^(-?[\d.,]+) m³，需 ≥ (-?[\d.,]+) m³（T = (-?[\d.,]+) s）$/, (a, b, t) => `${a} m³, need ≥ ${b} m³ (T = ${t} s)`],
  [/^(-?[\d.,]+) m，需 ≥ (-?[\d.,]+) m$/, (a, b) => `${a} m, need ≥ ${b} m`],
  [/^地面取水口 (\d+) 个（见「地面取水口」表）$/, a => `${a} surface intake(s) (see the "Surface intakes" table)`],
  [/^(-?[\d.,]+) 台$/, a => `${a} pumps`],
  [/^有效 (-?[\d.,]+) m³，需 ≥ (-?[\d.,]+) m³$/, (a, b) => `effective ${a} m³, need ≥ ${b} m³`],
  [/^池底 (-?[\d.,]+) m$/, a => `invert ${a} m`],
  [/^开挖 (-?[\d.,]+) m（截流口 (-?[\d.,]+)，池水面 (-?[\d.,]+)）$/, (a, b, c) => `excavation ${a} m (intercept ${b}, tank water level ${c})`],
  [/^总 (-?[\d.,]+)、坏一台 (-?[\d.,]+)，设计 (-?[\d.,]+) m³\/s$/, (a, b, c) => `total ${a}, one pump out ${b}, design ${c} m³/s`],
  [/^地面场地 (-?[\d.,]+) m²（面积下限手册未给，需客户提供或参照已建泵站）$/, a => `surface site ${a} m² (manual gives no minimum area; client to confirm or refer to built stations)`],
  [/^(≥[\d.]+) m 路面 (\d+) m²$/, (a, b) => `${a} m road surface ${b} m²`],
  [/^(≥[\d.]+) m 碰到 (\d+) 栋建筑$/, (a, b) => `${a} m reaches ${b} building(s)`],
  [/^碰到 (\d+) 栋建筑$/, a => `reaches ${a} building(s)`],
  [/^(\w+) (\d+) m 内，路面 \/ 建筑处 (≥[\d.]+) m$/, (k, d, h) => `${k} within ${d} m, road / building ${h} m`],
  [/^客户热点重要度 (\w+(?: \w+)?)$/, a => `client hotspot importance ${a}`],
  [/^只在空地 \/ 未建地块 \/ 公园$/, () => 'only on open land / undeveloped plots / parks'],
  [/^淹到输电变电站$/, () => 'floods a power substation'],
  [/^DTM 填 0：最深点高程 0\.00 m，片内 (\d+)% 的 DTM 格恰为 0\.00 m，判断为缺测填 0$/, a => `DTM zero-fill: deepest point at 0.00 m, ${a}% of the patch's DTM cells are exactly 0.00 m, judged as missing data filled with 0`],
  [/^DTM 填 0 区：DTM 恰为 0\.00 m 的连片区$/, () => 'DTM zero-fill zone: contiguous area where the DTM is exactly 0.00 m'],
  [/^系统 L3 按近似邻接判片，把这片和相邻的 (SIM-\w+-\d+) 算作同一片（L3 编号 (SIM-\w+-\d+)，积水量已合在一起）；本交付按真实三角网邻接分成两片$/,
    (a, b) => `The system L3 joins patches by approximate adjacency and counted this patch together with the neighbouring ${a} (L3 ID ${b}, volumes combined); this delivery splits them using true triangle-mesh adjacency`],
  [/^L3 把 (SIM-\w+-\d+) 也算进这片（近似邻接），积水量含 (SIM-\w+-\d+)$/, (a, b) => `L3 also merged ${a} into this patch (approximate adjacency); the volume includes ${b}`],
  [/^OPTCS (S\d+D\d+) 峰值 ([\d.]+) m，超 0\.30 m 到峰值 ([\d.]+) h，加 ([\d.]+) m³\/s$/,
    (s, p, t, q) => `OPTCS ${s} peak ${p} m, ≥0.30 m until the peak ${t} h, adds ${q} m³/s`],
]

// —— 自由文本里的固定短语（成果说明字段：一条里夹着数字与编号，整句列不全）——
const PHRASES = [
  ['雨前预置移动泵', 'pre-placed mobile pump'], ['重力进水地下调蓄池', 'gravity-fed underground storage tank'],
  ['井边泵站 + 地下调蓄池', 'well-side pumping station + underground tank'], ['地面取水口（地面洼坑）', 'surface intake (surface depression)'],
  ['地面取水口（隧道引道）', 'surface intake (tunnel approach)'], ['地面泵站（按小泵站过可建性检查，', 'surface pumping station (small-station buildability check, '],
  ['泵站 → 新建排海口', 'pumping station → new sea outfall'], ['→ 地面泵站', '→ surface pumping station'], ['→ 地下池', '→ underground tank'],
  ['现有 RD-A 泵站', 'Existing RD-A pumping station'], ['全市管网', 'citywide network'], ['注记', 'annotation'], ['湿井', 'wet well'], ['出水口', 'outlet'],
  ['泵曲线最大流量取客户 Pump3 曲线', "max flow taken from the client's Pump3 curve"],
  ['热点表 Plan A 预置移动泵：吸水井 = 热点最近的井，排到沿管往下游第一口在 L1 一维结果里不溢流的井',
    'Plan A pre-placed mobile pump from the hotspot table: suction well = the well nearest the hotspot; discharges to the first downstream well along the pipe that does not overflow in the L1 1D results'],
  ['客户 SewerGEMS 情景', 'Client SewerGEMS scenario'], ['里的泵：吸水井', 'pump: suction well'], ['设施台账状态「设计中」、挂', 'facility-register status "in design", linked to hotspots such as'],
  ['等热点（可信度弱）', '(low confidence)'], ['同情景的泵', 'the same scenario\'s pump'], ['判「只是方案」，未纳入', 'judged "scheme only" and not included'],
  ['截流井', 'intercept well'], ['热点', 'hotspot'], ['开挖', 'excavation'], ['用地', 'land use'], ['公园', 'park'], ['公共用地', 'public land'],
  ['未建地块', 'undeveloped plot'], ['无地块记录', 'no plot record'], ['占位造价', 'placeholder cost'], ['占位单价', 'placeholder rates'], ['占位', 'placeholder'],
  ['调蓄池', 'storage tank'], ['重力管', 'gravity pipe'], ['排空泵', 'drain-down pump'], ['压力管', 'pressure main'], ['外推', 'extrapolated'], ['按面积外推', 'extrapolated by area'],
  ['第三卷', 'Vol. 3'], ['有条件可建', 'buildable with conditions'], ['待办：', 'to do: '], ['长 ', 'length '], ['管径', 'diameter'], ['井 ', 'well '], ['场地', 'site'],
  ['流速', 'velocity'], ['个取水口', ' intakes'], ['台 ×', 'pumps ×'], ['台 →', 'pumps →'], ['泵站 ', 'pumping station '], ['离道路隧道', 'distance to road tunnel'],
  ['用户', 'user'], ['选 (b)，作为新建泵站计入方案，待客户确认是否有现状泵站', 'chose (b): counted in the scheme as a new pumping station, pending client confirmation of whether an existing one exists'],
  ['峰值', 'peak'], ['超 0.30 m 到峰值', '≥0.30 m until the peak'], ['加 ', 'adds '],
  ['；', '; '], ['，', ', '], ['（', ' ('], ['）', ')'], ['：', ': '], ['、', ', '],
]
const LAND = { 公园: 'park', 公共用地: 'public land', 未建地块: 'undeveloped plot', 无地块记录: 'no plot record' }
const CJK = /[一-鿿]/

function lookup(zh) {
  const hit = EN[zh]
  if (hit !== undefined) return hit
  for (const [re, fn] of PATTERNS) {
    const m = zh.match(re)
    if (m) return fn(...m.slice(1))
  }
  // 用地占比字典 {'公园': 0.0, ...}
  if (zh.includes("'公园'") || zh.includes("'无地块记录'")) {
    return zh.replace(/'([^']+)'/g, (_, k) => `'${LAND[k] || k}'`)
      .replace('（公共 / 未建 / 无记录地均需主管部门或业主许可，', ' (public / undeveloped / no-record land all need authority or owner permission, ')
      .replace('）', ')').replace('泵站 ', 'pumping station ').replace('；池 ', '; tank ')
  }
  if (CJK.test(zh) && zh.length > 8) {
    let s = zh
    for (const [a, b] of PHRASES) s = s.split(a).join(b)
    return s
  }
  return zh
}

/** `tr('…{n}…', { n: 3 })`：英文界面查词典，中文界面原样；`{x}` 占位在两种语言里都会填。 */
export function tr(zh, params) {
  if (zh == null) return ''
  const s = locale.value === 'en' ? lookup(String(zh)) : String(zh)
  return params ? s.replace(/\{(\w+)\}/g, (m, k) => (k in params ? params[k] : m)) : s
}

/** 以「；」分隔的一串事项（审批、缺数据、剔除说明、定级依据）：逐条翻，英文用「; 」连。 */
export function trj(zh) {
  if (!zh) return ''
  if (locale.value !== 'en') return String(zh)
  return String(zh).split('；').map(p => lookup(p.trim())).join('; ')
}

export const RDA_EN = EN
