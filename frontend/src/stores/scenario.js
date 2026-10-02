import { defineStore } from 'pinia'
import { computed, reactive, ref, shallowRef } from 'vue'

import {
  fetchCoverage,
  fetchDistricts,
  fetchHotspots,
  fetchModelPonding,
  fetchNetwork,
  fetchStormPreset,
  runPointCurve,
  runScenario,
} from '../api'
import { COLOR, MECHANISM_COLOR, OVERRIDABLE, QUICK_DISTRICT, RPS, SOURCE_KEYS } from '../constants'
import { t } from '../i18n'
import { UNFILLED, esc, filterFieldLabel, fmt, muniLabel, nowStamp } from '../utils/format'
import { pumpBrief } from '../utils/pumps'
import { useToastStore } from './toast'

const deepCopy = v => JSON.parse(JSON.stringify(v))

export const useScenarioStore = defineStore('scenario', () => {
  const toast = useToastStore()

  /* ---------------- 看哪一套积水点 ----------------
     'ledger'：历史上报的 845 个台账点（默认）
     'model' ：二维水动力演算识别出的 107 个易积水片区（只有 Al Bateen 一个 run）

     两套**不是同一批地物**，故不合并、不匹配、不互相排序：台账点是行政记录，
     片区是演算结论，一个报过不代表另一个识别得出来。但它们现在**走同一条计算链**
     —— 片区的 A / C / tc / Qcap / 调蓄已由 `model_cluster_batch.py` 补齐，
     且五项里四项与台账逐字段同法（只有汇水区边界不同：片区是 D8 实算，
     台账是 Voronoi 代理）。故计算器、筛选、搜索两边共用，只是点集不同。 */
  const source = ref('ledger')

  /* ---------------- 台账与图层 ----------------
     两套积水点各存一份（`/api/hotspots?source=`），`points` / `meta` / `byUid`
     随当前数据源派生 —— 于是计算器、搜索、筛选、KPI 那一整套组件一个字都不用改，
     切个数据源就对着另一套点算。两份各自缓存，来回切不重打接口。 */
  const sets = reactive({
    ledger: { points: [], meta: null },
    model: { points: [], meta: null },
  })
  const points = computed(() => sets[source.value].points)
  const meta = computed(() => sets[source.value].meta)
  const byUid = computed(() => new Map(points.value.map(p => [p.uid, p])))
  // 有管网数据区域的落图面（/api/coverage）。拿不到就是 null，页面照常出图。
  const coverage = shallowRef(null)
  // 官方行政片区轮廓（/api/districts）。拿不到就是 null，片区筛选照常工作。
  const districts = shallowRef(null)
  /* 雨水管网落图线（/api/network/*）。两层分开按需取，取回来就一直留着：
     mains 1.6 MB 在按下按钮时取，laterals 3.2 MB 等地图放大到支管起画的级别才取。
     值为 null = 还没取过；'loading' = 正在取；对象 = 取到了。 */
  const network = reactive({ mains: null, laterals: null })

  /* /api/model-ponding 的整包（features + run + summary + caveats）。
     它是模型片区的**几何与水动力指标**；那 107 个点的计算器输入走的是
     `/api/hotspots?source=model`，两者按 `cluster_rank` ↔ `rank` 对上号。 */
  const model = shallowRef(null)
  const modelLoading = ref(false)
  // 成因筛选：空数组 = 全看
  const modelMech = ref([])

  /* ---------------- 交互模式 ----------------
     'point'：点一个积水点，选一级重现期算一级（默认交互）
     'batch'：全域批算，一场雨扫全部点 */
  const mode = ref('point')

  // curveRp = 面板上选中的那一级（选中 ≠ 算过）；preset = 该级的默认降雨参数
  const curve = shallowRef(null)
  const curveRp = ref(25)
  const curveLoading = ref(false)
  const preset = shallowRef(null)
  const presetLoading = ref(false)

  const result = shallowRef(null)
  const resByUid = shallowRef(new Map())
  const running = ref(false)

  const dataset = ref('auto')
  const rp = ref(25)
  const custom = reactive({ P: 50, D: 120 })
  const useCustom = ref(false)

  /* ---------------- 模型输入（抽屉里的「模型版本」） ---------------- */
  const inputs = reactive({
    v: '1.0',
    ts: null,
    assumptions: {
      sed_factor: 1.05,
      shape_factor: 0.5,
      drawdown_hours: 2,
      // 三道防线的判定口径。⚠ 旧的 'window'（管网按满流 Qcap 恒排 T 小时）
      // 已被后端**删除**，不是改默认值 —— 它被一维与二维水动力成果同时证伪
      // （见 backend/src/stormwater/ponding_curve.py 模块头）。发旧值会 422。
      defence_basis: 'hydrodynamic',
      // —— 车队配置：每个积水点配几台泵 × 每台抽多少 —— 页面上可改。
      // 300 m³/h 是假设值，但落在在册车队加权平均（321）附近，见后端 pumps.py。
      //
      // ⚠ 泵与罐车**串联**：泵把水抽进罐车、罐车运走，外运能力取两侧较小值。
      //   只调泵不加车是白调 —— 后端 summary.chain_bottleneck 会指出卡在哪侧。
      pumps_per_point: 1,
      pump_capacity: 300,
      // 每个积水点配几辆罐车 —— 与 pumps_per_point 并排设，两侧都要配够。
      // 默认 1 辆与 1 台对称，但两侧默认能力差着一个量级（300 vs 15 m³/h）：
      // 喂饱一台泵要 20 辆车（后端 summary.tankers_per_pump）。
      tankers_per_point: 1,
      // 罐车单车储水能力（m³/车次）—— 假设值，应替换为实际车队单车载量
      tanker_capacity: 15,
      // 罐车单车往返周转时间（min/趟：装载 + 运输 + 卸载 + 返回）。它定两件事：
      // ① 车次折辆数（一辆车在 T 内跑 ⌊T×60/周转⌋ 趟）；
      // ② 单车持续外运能力 = 单车载量 / 周转，即这条链罐车侧的通过量。
      // 本项目无数据支撑 60。
      tanker_turnaround_min: 60,
      // 以下两个只在清空 pump_capacity、退回 12″/8″/6″ 分档表时才起作用
      pump_duty_factor: 0.65,
      pump_availability: 0.85,
    },
    profiles: {},
    priority: '',
    zeroQcap: true,
    coverageOnly: true,
  })

  // 场景级覆盖（不写回模型输入）。分档表本身不在这里调 —— 它是结构，不是旋钮。
  const over = reactive({
    drawdown_hours: null,
    pumps_per_point: null,
    pump_capacity: null,
    tankers_per_point: null,
    tanker_capacity: null,
    tanker_turnaround_min: null,
    pump_duty_factor: null,
    pump_availability: null,
  })

  const draft = ref(null)
  const history = ref([])

  /* ---------------- 界面状态 ---------------- */
  const filters = reactive({ municipality: [], criticality: [], root_cause: [], district: [] })
  const sel = ref(null)
  const panel = ref(true)
  const brief = ref(true)
  const drawer = ref(false)
  const tab = ref('profiles')
  const listLimit = ref(12)
  // 逐点明细按防线分组：'all' | 1 | 2 | 3
  const listLine = ref('all')
  const basemap = ref('dark')
  const showCoverage = ref(true)
  // 管网线默认关着 —— 它是参照物不是主角，而且要下 1.6 MB
  const showNetwork = ref(false)

  // 搜索框：q 是输入内容，qHits 是当前命中（全量，不截断），qIdx 是键盘选中的那一条
  const q = ref('')
  const qHits = shallowRef([])
  const qIdx = ref(0)

  /* ---------------- 地图指令通道 ----------------
     store 不碰 Leaflet 实例，只发一条指令，MapView 监听后执行。 */
  const mapQueue = ref([])
  const askMap = (type, payload = null) => {
    // 队列而不是单值：select() 同一 tick 里连发 focus + popup，单值会被后者盖掉
    mapQueue.value = [...mapQueue.value, { type, payload }]
  }
  const drainMapQueue = () => {
    const q = mapQueue.value
    mapQueue.value = []
    return q
  }

  /* ---------------- 派生 ---------------- */

  /** 合成后的假设参数：模型输入打底，场景覆盖优先。 */
  const asm = computed(() => {
    const a = { ...inputs.assumptions }
    for (const k of OVERRIDABLE) if (over[k] != null) a[k] = over[k]
    return a
  })

  /** 「每点 N 台」里那个「台」到底是多大 —— 一个数，两个来源：
   *
   *  * 页面设了「单泵抽排能力」：就是它本身（默认口径）。
   *  * 清空了它、退回 12″/8″/6″ 分档派车：一台就不是某个具体档，而是混合
   *    车队里的平均一台，取后端算的在册构成加权平均（约 321 m³/h）。
   *
   *  ⚠ 后端那个数只有跑过一次才有，故未算时返回 null —— 调用方必须显示成
   *  「—」而不是 0：0 会读成「一台泵抽不动水」。 */
  const pumpUnitCapacity = computed(() => {
    if (asm.value.pump_capacity) return asm.value.pump_capacity
    const s = result.value && result.value.summary
    return s && Number.isFinite(s.pump_unit_capacity_m3hr) ? s.pump_unit_capacity_m3hr : null
  })
  /** 上面那个数是不是从分档表加权来的 —— 是就得在界面上说清楚，别当成设定值。 */
  const pumpUnitFromTiers = computed(() => !asm.value.pump_capacity)

  const overCount = computed(
    () => OVERRIDABLE.filter(k => over[k] != null && over[k] !== inputs.assumptions[k]).length,
  )

  const stormLabel = computed(() =>
    useCustom.value ? `${custom.P} mm / ${custom.D} min` : t('point.rpOnceIn', { n: rp.value }),
  )

  /** 这个点会不会真的参与计算 —— 与后端 `ScenarioRequest.coverage_only` 同一口径。
   *  依据是逐点的 `in_coverage`（后端由到最近雨水管的距离算出），不是看它落没落进
   *  地图上那张面：面简化过，边界上对不上号。也不是看行政区 —— 台账记为阿布扎比市的
   *  点里有 5 个在数据区之外。 */
  const inScope = p => !inputs.coverageOnly || p.in_coverage

  /** 当前筛选条件下显示在地图上的点。区域外的点照样画（画成空心），
   *  只是不参与计算 —— 让人看见被排除了什么，比直接抹掉诚实。 */
  const filtered = computed(() =>
    points.value.filter(
      p =>
        (!filters.district.length || filters.district.includes(p.district_key)) &&
        (!filters.municipality.length || filters.municipality.includes(p.municipality)) &&
        (!filters.criticality.length || filters.criticality.includes(p.criticality || UNFILLED)) &&
        (!filters.root_cause.length || filters.root_cause.includes(p.root_cause || UNFILLED)) &&
        // 成因只对模型片区有意义（台账点的 mechanism_key 恒为 null）
        (!modelMech.value.length || modelMech.value.includes(p.mechanism_key)),
    ),
  )

  /** 当前重现期那一行 —— 单点模式下「结论」指的就是它。
   *  「选一级算一级」：选中的级没算过就是 null，不拿别的级顶替。 */
  const currentRow = computed(() => {
    if (!curve.value) return null
    return curve.value.scenarios.find(r => r.return_period_yr === curveRp.value) || null
  })

  /** 这个点在当前一套参数下已经算过的重现期（升序）。 */
  const computedRps = computed(() => (curve.value ? curve.value.scenarios.map(r => r.return_period_yr) : []))
  const isComputed = rpv => computedRps.value.includes(rpv)

  /** 这个点当前有没有计算结果可着色。
   *  全域批算：每个点都有；单点模式：只有被选中的那个点有（取当前重现期那一行）。 */
  function resFor(p) {
    if (mode.value === 'batch') return resByUid.value.get(p.uid)
    return curve.value && curve.value.point.uid === p.uid ? currentRow.value : null
  }

  /** 一个点在地图上的颜色：跑完按三道防线（两套点同一套色），没跑按各自的分类 ——
   *  台账点按上报的严重度，模型片区按演算判出的成因。片区没有严重度可言，
   *  拿「未评级」的灰色去画 107 个点等于什么都没说。 */
  function colorFor(rec, res) {
    if (!res && rec.mechanism_key) return MECHANISM_COLOR[rec.mechanism_key] || COLOR.none
    if (!res) return COLOR.crit[rec.criticality || UNFILLED] || COLOR.none
    // null = 这个点没跑过二维演算，不出结论。必须先判 —— 落到下面那行会拿
    // `null >= 4` / `null >= 2`（都是 false）把它画成「需 1 台泵」的暖色。
    if (res.line === null) return COLOR.uncalibrated
    if (res.line === 1) return COLOR.line1
    if (res.line === 2) return COLOR.line2
    return res.pumps_required >= 4 ? COLOR.line3c : res.pumps_required >= 2 ? COLOR.line3b : COLOR.line3a
  }

  const summaryTiers = computed(
    () => (result.value && result.value.summary && result.value.summary.pump_tiers) || [],
  )
  /* 12″/8″/6″ 三档参照表 —— 后端恒给，与本次是否按它派车无关。
     页面上要选「单泵抽排能力」该设多少时，对照的就是这张表。
     单点曲线的行也自带一份（后端 /api/point-curve 逐行发回）。 */
  const summaryRefTiers = computed(
    () =>
      (result.value && result.value.summary && result.value.summary.pump_reference_tiers) ||
      (curve.value &&
        curve.value.scenarios.length &&
        curve.value.scenarios[0].pump_reference_tiers) ||
      [],
  )
  const brief_ = row => pumpBrief(row, summaryTiers.value)

  /** 一行结论。`full` 时补上罐车那一侧（几辆、几车次、每辆几趟）。
   *
   *  ⚠ 罐车与泵**串联不是二选一** —— 泵把水抽进罐车、罐车运走，两侧同时都要。
   *  短串里略掉罐车只是版面所限（这个串还给悬停 tooltip 和 toast 用，那两处
   *  只有一行地方，塞进去会挤掉点位名），不表示罐车可有可无；地图气泡有地方，
   *  故它显式传 true。文案用「并配」不用「或」，见 i18n 的 `line.l3Tankers`。 */
  function lineLabel(res, full = false) {
    if (res.line === null) return t('line.none')
    if (res.line === 1) return t('line.l1')
    if (res.line === 2) return t('line.l2')
    const head = t('line.l3', {
      brief: brief_(res),
      h: res.window_hours,
      v: fmt(res.shortfall_m3),
    })
    if (!full || !res.tanker_loads) return head
    return (
      head +
      (res.tankers_required === null
        ? t('line.l3TankersNone')
        : t('line.l3Tankers', {
            n: fmt(res.tankers_required),
            loads: fmt(res.tanker_loads),
            trips: res.tanker_trips_per_vehicle,
          }))
    )
  }

  /* ---------------- 出处计数 ---------------- */

  /** 按 Qcap 出处数点（points 带的是批算原始 basis，不是解算后的）。 */
  const qcapBasisCount = basis => points.value.filter(p => p.qcap_basis === basis).length

  const groupOf = p => (p.root_cause && inputs.profiles[p.root_cause] ? p.root_cause : '_default')

  /** 某个成因分组里，剖面的 Q_cap 输入框真正生效的点数。
   *  实测点用实测值、确认无管的点强制取 0，两类都不看这个框。 */
  function qcapEditableCount(groupKey) {
    return points.value.filter(p => {
      if (groupOf(p) !== groupKey) return false
      if (!inScope(p)) return false // 压根不参与计算的点，改这个框对它没有意义
      if (p.qcap_basis === 'measured' || p.qcap_basis === 'measured_no_network') return false
      if (inputs.zeroQcap && p.qcap_basis === 'no_coverage' && p.network_available === false) return false
      return true
    }).length
  }

  /** 改 A / C / tc 这三个框时，该组里真正生效的点数 —— 实测的点不读它。 */
  function catchmentEditableCount(groupKey) {
    return points.value.filter(p => {
      if (groupOf(p) !== groupKey) return false
      if (!inScope(p)) return false
      return p.catchment_basis !== 'measured' && p.catchment_basis !== 'measured_undeveloped'
    }).length
  }

  const groupCounts = computed(() => {
    const counts = {}
    points.value.forEach(p => {
      const k = groupOf(p)
      counts[k] = (counts[k] || 0) + 1
    })
    return counts
  })

  /* ---------------- 片区（官方行政边界） ---------------- */
  const districtFacet = computed(() => (meta.value && meta.value.facets.district) || [])
  const districtRow = key => districtFacet.value.find(x => x.value === key) || null

  /* ---------------- 片区的二维演算积水量 ----------------
     只有跑过 ANUGA 的片区才有（当前只有 Al Bateen）。页面靠它做三件事：
     默认选哪一级雨、三道防线共用时限 T 取多少、单点那一行显示多少方水。
     口径在后端 `registry.district_ponding()`，这里一个数都不再算。 */

  /** 某个片区的积水演算总账；没跑过就是 null —— 页面据此整块不显示，而不是摆 0。 */
  const districtPondingOf = key => {
    const row = districtRow(key)
    return (row && row.ponding) || null
  }

  /** 当前框定的片区的积水演算。没框片区、或该片没跑过，都是 null。 */
  const ponding = computed(() =>
    filters.district.length ? districtPondingOf(filters.district[0]) : null,
  )

  /** 「15 – 1185 min（19.75 h）」—— 这个 T 是被谁定住的，一眼看得出。 */
  const pondingWindowLabel = computed(() => {
    const p = ponding.value
    if (!p) return ''
    // 分钟数不加千分位：这是一个时刻区间的写法，`1,185 min` 读着像个金额
    return t('ponding.windowRange', {
      lo: Math.round(p.drain_min[0]),
      hi: Math.round(p.drain_min[1]),
      h: p.window_h,
    })
  })

  /** 逐点的积水总量口径 —— 净累计进水量（Σ 正 ΔV），不是瞬时峰值。
   *  只有跑过演算的点有；其余返回 null，单点面板那一行整行不出。 */
  const pondingOf = uid => {
    const p = uid ? byUid.value.get(uid) : null
    if (!p || !p.ponding_run_id) return null
    return {
      run_id: p.ponding_run_id,
      rp: p.ponding_rp_yr,
      total_m3: p.ponding_net_inflow_m3,
      peak_m3: p.ponding_peak_m3,
      settled_m3: p.ponding_settled_m3,
      volume_hours_m3h: p.ponding_volume_hours_m3h,
      drain_min: p.ponding_drain_min,
      drain_h: p.ponding_drain_min == null ? null : Math.round((p.ponding_drain_min / 60) * 100) / 100,
      basis: p.ponding_basis,
    }
  }

  /** 选中那个点的积水演算。 */
  const selPonding = computed(() => pondingOf(sel.value))

  /** 片区的显示名：`AL BATEEN`，重名的才加市政区后缀。 */
  function districtLabel(row) {
    const dup = (meta.value && meta.value.district && meta.value.district.ambiguous_names) || []
    return dup.includes(row.label)
      ? t('common.districtWithMuni', { name: row.label, muni: muniLabel(row.municipality) })
      : row.label
  }

  /** 上一次替操作员套上去的那一级重现期 —— 取消片区时按它原样还回去。
   *  只还「我们改的那一份」：操作员自己又调过的，以他调的为准。 */
  let pondingApplied = null

  /** 框定一个跑过演算的片区时，把这个片区**自己的重现期**套上去 —— 演算成果是一场
   *  100 年一遇的雨算出来的，页面还停在 25 年就会拿两场不同的雨的数字并排摆。
   *
   *  ⚠ **三道防线共用时限 T 不在此列**：T 是服务水平目标（工期），由决策者显式选，
   *  默认锁在 `inputs.assumptions.drawdown_hours`（2 h），任何片区的演算都不替人改它。
   *  该片区退水最慢那个点的积水时长（Al Bateen 是 19.75 h）只作出处参照写在
   *  「输入」T 那一行下面 —— 要按它派车，得操作员自己把 T 改过去。
   *  返回给提示条用的那句话；没有演算数据就返回 ''，一个旋钮都不碰。 */
  function applyDistrictPonding(key) {
    const pond = key ? districtPondingOf(key) : null

    // 先把上一轮套上去的还回去。操作员自己又动过的（值已经不是我们设的那个）不碰。
    if (pondingApplied) {
      const a = pondingApplied
      if (!useCustom.value && rp.value === a.rp && curveRp.value === a.rp) {
        rp.value = a.prevRp
        curveRp.value = a.prevCurveRp
      }
      pondingApplied = null
    }
    if (!pond) return ''

    pondingApplied = {
      rp: pond.return_period_yr,
      prevRp: rp.value,
      prevCurveRp: curveRp.value,
    }
    if (pond.return_period_yr) {
      useCustom.value = false
      rp.value = pond.return_period_yr
      curveRp.value = pond.return_period_yr
    }
    // 雨换了，算过的那一条按的是旧口径 —— 作废，但不替人重算
    curve.value = null
    return t('toast.pondingApplied', {
      rp: pond.return_period_yr,
      window: pondingWindowLabel.value,
      n: pond.wet_points,
    })
  }

  /** 选中某个片区（传 null 清空）。片区是互斥的：同时框两个区没有调度意义。 */
  function setDistrict(key) {
    filters.district = key ? [key] : []
    result.value = null
    resByUid.value = new Map()
    if (sel.value && !filtered.value.some(x => x.uid === sel.value)) {
      sel.value = null
      curve.value = null
      preset.value = null
    }
    const pondNote = applyDistrictPonding(key)
    // 重现期换了，选中那个点的默认降雨参数跟着重取
    if (sel.value) loadPreset()
    if (key) {
      const row = districtRow(key)
      askMap('fit')
      if (row) {
        toast.show(
          t('toast.districtScoped', {
            name: districtLabel(row),
            count: row.count,
            inCov: row.in_coverage,
            tail: t(row.in_coverage ? 'toast.districtScopedOk' : 'toast.districtScopedNone'),
          }) + pondNote,
          row.in_coverage ? 'var(--green)' : 'var(--amber)',
        )
      }
    }
  }

  function toggleQuickDistrict() {
    setDistrict(filters.district[0] === QUICK_DISTRICT ? null : QUICK_DISTRICT)
  }

  /* ---------------- 「撑到第几级」 ----------------
     KPI、侧栏、简报共用，口径只写一次。三种情形各有各的说法：
     * 第三道起于算过的最低一级 → 「不足 5 年」，不是留个破折号；
     * 各级都接得住 → 「≥ 100 年」；
     * 自定义雨只有一行、没有级差 → 改说这一场雨本身的结论。 */
  const holdSummary = computed(() => {
    const rows = curve.value ? curve.value.scenarios : []
    const last = RPS[RPS.length - 1]
    if (!rows.length) {
      const pending = t('hold.pending')
      return { short: '—', cls: 'w', tag: pending, note: pending, text: pending }
    }

    if (useCustom.value) {
      const r = rows[0]
      const brief = brief_(r)
      return r.line === 3
        ? {
            short: brief,
            cls: 'w',
            tag: t('hold.customNeed', { brief }),
            note: t('hold.customNeedNote', { brief }),
            text: t('hold.customNeedText', { p: custom.P, d: custom.D, brief }),
          }
        : {
            short: t('hold.customOkShort'),
            cls: 's',
            tag: t('hold.customOkTag'),
            note: t('hold.customOkNote'),
            text: t('hold.customOkText', { p: custom.P, d: custom.D }),
          }
    }

    // ⚠ 只数**出得了结论**的那几档：无标定的行也在 rows 里（它们有峰值诊断），
    // 但「5 / 10 / 25 年撑得住」这句话不能拿没算过的档来说。当前只有与二维演算
    // 同重现期的那一档有结论，所以这里通常只剩一个数。
    const done = rows
      .filter(r => r.line !== null)
      .map(r => r.return_period_yr)
      .sort((a, b) => a - b)
    const all = RPS.every(x => done.includes(x))
    const l3 = rows.find(r => r.line === 3)

    // 一档都没算出来 —— 不能说「撑得住」，也不能说「撑不住」
    if (!done.length) {
      const none = t('hold.uncalibrated')
      return { short: '—', cls: 'w', tag: none, note: none, text: t('hold.uncalibratedText') }
    }

    if (!l3) {
      if (all)
        return {
          short: t('hold.geShort', { n: last }),
          cls: 's',
          tag: t('hold.allHeldTag'),
          note: t('hold.allHeldNote', { first: RPS[0], last }),
          text: t('hold.allHeldText', { first: RPS[0], last }),
        }
      // 只算了其中几级 —— 结论只能说到算过的那几级为止
      const list = done.join(' / ')
      const missing = RPS.filter(x => !done.includes(x)).join(' / ')
      return {
        short: t('hold.geShort', { n: done[done.length - 1] }),
        cls: 's',
        tag: t('hold.someHeldTag', { n: done.length }),
        note: t('hold.someHeldNote', { list }),
        text: t('hold.someHeldText', { list, missing }),
      }
    }

    const below = RPS.filter(x => x < l3.return_period_yr)
    const allBelowDone = below.every(x => done.includes(x))
    const held = !below.length
      ? t('hold.belowShort', { n: l3.return_period_yr })
      : allBelowDone
        ? t('hold.heldShort', { n: below[below.length - 1] })
        : t('hold.lowerThan', { n: l3.return_period_yr })
    const gapNote =
      below.length && !allBelowDone
        ? t('hold.gapNote', { list: below.filter(x => !done.includes(x)).join(' / ') })
        : ''
    return {
      short: held,
      cls: 'w',
      rp: l3.return_period_yr,
      tag: t('hold.l3Tag', { n: l3.return_period_yr }),
      note: t('hold.l3Note', { n: l3.return_period_yr, gap: gapNote }),
      text: t('hold.l3Text', { held, gap: gapNote, n: l3.return_period_yr }),
    }
  })

  /* ---------------- 搜索 ----------------
     只查已经载入的 845 条台账，纯前端，不打接口 —— 台账一次性载完，
     再发请求只会更慢。匹配四个字段：编号 / 位置 / 片区 / 行政区，
     位置里有阿拉伯语与中文，一律按子串比，不做分词。 */
  const qnorm = v => String(v == null ? '' : v).toLowerCase().replace(/\s+/g, '')

  /** 命中排序：编号精确 > 编号尾号 > 编号前缀 > 位置开头 > 位置包含 > 片区/行政区。
   *  「输 31 找 ADM-031」这一条是给现场用的 —— 报点位时没人念前缀。
   *
   *  ⚠ 这里的「片区」是台账的 `area` 自由文本列，不含官方行政片区：
   *  输「Al Bateen」只会命中艾因那 3 个点，岛上巴廷区的 18 个点 area 写的是 Island，
   *  搜不到。岛上那一片走「只看 AL BATEEN 区」按钮，不走搜索框。 */
  function searchHits(raw) {
    const n = qnorm(raw)
    if (!n) return []
    const tail = /^\d{1,4}$/.test(n) ? n.padStart(3, '0') : null
    const out = []
    for (const p of points.value) {
      const uid = qnorm(p.uid)
      const loc = qnorm(p.location)
      const area = qnorm(p.area)
      const muni = qnorm(p.municipality)
      let score = null
      if (uid === n) score = 0
      else if (tail && uid.endsWith('-' + tail)) score = 1
      else if (uid.startsWith(n)) score = 2
      else if (uid.includes(n)) score = 3
      else if (loc.startsWith(n)) score = 4
      else if (loc.includes(n)) score = 5
      else if (area.includes(n) || muni.includes(n) || qnorm(muniLabel(p.municipality)).includes(n)) score = 6
      if (score !== null) out.push({ p, score })
    }
    out.sort((a, b) => a.score - b.score || a.p.uid.localeCompare(b.p.uid))
    return out.map(x => x.p)
  }

  function setQuery(v) {
    q.value = v
    qHits.value = searchHits(v)
    qIdx.value = 0
  }

  /** 这个点是不是被当前筛选条件挡住了 —— 搜索能搜到全部 845 个点，
   *  但地图上只画筛选后的，挡住了要明说，不能搜到了却跳不过去。 */
  function blockedBy(p) {
    const out = []
    if (filters.district.length && !filters.district.includes(p.district_key)) out.push('district')
    if (filters.municipality.length && !filters.municipality.includes(p.municipality)) out.push('municipality')
    if (filters.criticality.length && !filters.criticality.includes(p.criticality || UNFILLED))
      out.push('criticality')
    if (filters.root_cause.length && !filters.root_cause.includes(p.root_cause || UNFILLED))
      out.push('root_cause')
    return out
  }

  /** 选中搜索结果：被筛选挡住时只撤掉挡住它的那几项，不清空全部筛选。 */
  function chooseHit(uid) {
    const p = byUid.value.get(uid)
    if (!p) return
    const blocked = blockedBy(p)
    if (blocked.length) {
      blocked.forEach(f => {
        filters[f] = []
      })
      result.value = null
      resByUid.value = new Map()
      toast.show(t('toast.filterDropped', { uid, fields: blocked.map(filterFieldLabel).join(' / ') }))
    }
    if (sel.value === uid) sel.value = null // 让 select() 的开关落在「选中」这一边
    select(uid)
  }

  /* ---------------- 模型识别的易积水片区 ----------------
     这一路是**只读展示**：没有 A/C/tc/Qcap，故没有计算、没有场景、没有覆盖判定。
     它与台账那一路共用地图与底图工具，其余各管各的状态。 */

  /** 片区几何按 rank 索引 —— 地图画面、明细块都按 `cluster_rank` 来取。 */
  const featureByRank = computed(() => {
    const m = new Map()
    for (const f of (model.value && model.value.features) || []) m.set(f.properties.rank, f)
    return m
  })

  /** 当前筛选下要画的片区面。与地图上的点**同一个 `filtered`**，
   *  故筛掉的点连它的面一起消失，不会出现「点没了面还在」。 */
  const modelFeatures = computed(() => {
    if (source.value !== 'model' || !model.value) return []
    return filtered.value
      .map(p => featureByRank.value.get(p.cluster_rank))
      .filter(Boolean)
  })

  /** 后端给的成因排序 × 实际出现的数量。图例与筛选按钮共用这一份。 */
  const modelMechRows = computed(() => {
    if (!model.value) return []
    const tally = model.value.summary.by_mechanism || {}
    // 成因的展示名只在 feature 上有（后端逐个 tr 过），这里按 key 取第一条的
    const labelOf = {}
    for (const f of model.value.features) labelOf[f.properties.mechanism_key] ??= f.properties.mechanism
    return (model.value.mechanism_order || [])
      .filter(k => tally[k])
      .map(k => ({ key: k, label: labelOf[k] || k, n: tally[k] }))
  })

  /** 选中点对应的片区几何与水动力指标。台账点没有，恒为 null。 */
  const modelSelFeature = computed(() => {
    const p = sel.value ? byUid.value.get(sel.value) : null
    if (!p || p.cluster_rank == null) return null
    return featureByRank.value.get(p.cluster_rank) || null
  })

  /** 取一次模型成果，幂等。取不到只提示一次，开关照常留着让人重试。 */
  async function loadModel() {
    if (model.value || modelLoading.value) return
    modelLoading.value = true
    try {
      const d = await fetchModelPonding()
      if (!d.available) {
        toast.show(t('toast.modelMissing'), 'var(--amber)')
        return
      }
      model.value = d
      toast.show(
        t('toast.modelLoaded', {
          n: d.summary.count,
          district: d.run.district,
          rp: d.run.return_period_yr,
        }),
      )
    } catch (e) {
      toast.show(t('toast.modelFailed', { msg: esc(e.message) }), 'var(--red)')
    } finally {
      modelLoading.value = false
    }
  }

  /** 模型识别那一套片区是**一场 100 年一遇的雨**演算出来的
   *  （`model_ponding.RUN_META.return_period_yr`）。切过去还停在 25 年，
   *  就会拿「100 年一遇识别出来的点」配「25 年一遇的雨」算，两场雨并排摆。
   *  故切到片区时把重现期顶到该 run 的那一级；切回台账时，只要操作员自己
   *  没再动过（值还是我们设的那个），就原样还回去。 */
  const MODEL_RP = 100
  let modelRpApplied = null

  function applySourceRp(v) {
    if (v === 'model') {
      if (!useCustom.value && rp.value === MODEL_RP && curveRp.value === MODEL_RP) return false
      modelRpApplied = { prevRp: rp.value, prevCurveRp: curveRp.value, prevCustom: useCustom.value }
      useCustom.value = false
      rp.value = MODEL_RP
      curveRp.value = MODEL_RP
      return true
    }
    // 切回台账：只还「我们改的那一份」
    if (modelRpApplied) {
      const a = modelRpApplied
      if (!useCustom.value && rp.value === MODEL_RP && curveRp.value === MODEL_RP) {
        rp.value = a.prevRp
        curveRp.value = a.prevCurveRp
        useCustom.value = a.prevCustom
      }
      modelRpApplied = null
    }
    return false
  }

  /** 切数据源。两套点不是同一批地物，故**算过的结论一律作废** ——
   *  把台账的防线颜色留在片区上，或者反过来，都是在骗人。
   *  筛选条件同样清空：两边的取值域不一样（片区没有严重度、没有成因）。 */
  async function setSource(v) {
    if (source.value === v || !SOURCE_KEYS.includes(v)) return
    sel.value = null
    curve.value = null
    preset.value = null
    result.value = null
    resByUid.value = new Map()
    // 片区筛选连同它套上去的那组演算口径一起撤掉，免得两套「套过的默认值」打架
    applyDistrictPonding(null)
    clearFilters(false)
    setQuery('')
    source.value = v
    const rpChanged = applySourceRp(v)
    try {
      await loadPoints(v)
    } catch (e) {
      toast.show(t('toast.sourceFailed', { msg: esc(e.message) }), 'var(--red)')
      return
    }
    // 片区那一路还要把几何与水动力指标取回来（落图 + 逐片区明细）
    if (v === 'model') await loadModel()
    askMap('fit')
    const m = sets[v].meta
    if (m) {
      toast.show(
        t(v === 'model' ? 'toast.sourceModel' : 'toast.sourceLedger', { n: m.count }) +
          (rpChanged ? t('toast.sourceModelRp', { rp: MODEL_RP }) : ''),
      )
    }
  }

  function toggleMech(key) {
    const list = modelMech.value
    const i = list.indexOf(key)
    modelMech.value = i >= 0 ? list.filter(k => k !== key) : [...list, key]
    // 选中的片区被筛掉了就撤选 —— 面板上留着一条地图上看不见的记录只会让人找不着
    if (sel.value && !filtered.value.some(p => p.uid === sel.value)) select(sel.value)
  }

  /* ---------------- 选点 ---------------- */
  function select(uid, pan = true) {
    sel.value = sel.value === uid ? null : uid
    if (sel.value) {
      if (pan) askMap('focus', sel.value)
      askMap('popup', sel.value)
      panel.value = true
    }
    if (mode.value === 'point') {
      // 单点模式：选点只是第一步 —— 先把这一级的默认降雨参数取来摆着，
      // 算不算、算哪一级，由人在面板上选完再按「计算」
      curve.value = null
      preset.value = null
      if (sel.value) loadPreset()
    }
  }

  function setMode(v) {
    if (mode.value === v) return
    mode.value = v
    // 两种模式的结果互不通用：切过去时把另一边的着色撤掉，别拿旧口径的颜色骗人
    curve.value = null
    preset.value = null
    if (mode.value === 'point' && sel.value) loadPreset()
    toast.show(t(mode.value === 'point' ? 'mode.pointHint' : 'mode.batchHint'))
  }

  /** 参数一变，已算过的结论就作废 —— 旧口径的数字不许留在屏幕上冒充新结果。 */
  function invalidatePoint(why) {
    const had = curve.value && curve.value.scenarios.length
    curve.value = null
    if (had && why) toast.show(t('toast.invalidated', { why }), 'var(--amber)')
  }

  function toggleFilter(field, value) {
    const list = filters[field]
    const i = list.indexOf(value)
    if (i >= 0) list.splice(i, 1)
    else list.push(value)
    result.value = null
    resByUid.value = new Map()
    // 单点模式下筛选只管地图；选中的点要是被筛掉了，一并撤选
    if (mode.value !== 'point' || (sel.value && !filtered.value.some(x => x.uid === sel.value))) {
      sel.value = null
      curve.value = null
      preset.value = null
    }
  }

  function clearFilters(dropResult = true) {
    filters.municipality = []
    filters.criticality = []
    filters.root_cause = []
    filters.district = []
    modelMech.value = []
    if (dropResult) {
      result.value = null
      resByUid.value = new Map()
    }
  }

  function setDataset(key) {
    if (key === 'custom_storm') useCustom.value = true
    else {
      useCustom.value = false
      dataset.value = key
    }
    // 换了 IDF 口径：历时与强度都变了，已算的作废，重取这一级的默认降雨参数
    if (mode.value === 'point') {
      invalidatePoint(t('toast.idfChanged'))
      loadPreset()
    }
  }

  /** 选一场雨。单点模式下只是「选」—— 算不算由「计算」按钮决定。 */
  function setStorm(v) {
    const wasCustom = useCustom.value
    if (v === 'custom') useCustom.value = true
    else {
      useCustom.value = false
      rp.value = Number(v)
    }
    if (mode.value === 'point') {
      curveRp.value = useCustom.value ? 0 : rp.value
      if (wasCustom !== useCustom.value) {
        // 自定义雨与标准重现期是两套口径，算过的结果互不通用，进出即清
        preset.value = null
        curve.value = null
      }
      if (sel.value) loadPreset() // 自定义档也取：设计历时会被 tc × M 抬高
    }
  }

  /** 切到哪一级只是换看哪一行 —— 算没算过由「计算」按钮决定，这里绝不偷偷开算。 */
  function setCurveRp(v) {
    curveRp.value = Number(v)
    if (!useCustom.value) rp.value = Number(v) || rp.value
    loadPreset()
  }

  /* ---------------- 请求 ---------------- */

  /** 两个计算接口共用的逐点输入部分。 */
  const pointInputsBody = () => ({
    dataset: useCustom.value ? 'custom_storm' : dataset.value,
    custom_depth_mm: custom.P,
    custom_duration_min: custom.D,
    profiles: inputs.profiles,
    priority: inputs.priority === '' ? null : Number(inputs.priority),
    zero_qcap_without_network: inputs.zeroQcap,
  })

  async function run() {
    if (running.value) return
    running.value = true
    try {
      const d = await runScenario({
        ...pointInputsBody(),
        // 算哪一套点由后端按 source 取，筛选条件两边同名同义
        source: source.value,
        return_period_yr: rp.value,
        assumptions: asm.value,
        coverage_only: inputs.coverageOnly,
        municipality: filters.municipality,
        criticality: filters.criticality,
        root_cause: filters.root_cause,
        district: filters.district,
      })
      d.ranAt = nowStamp()
      result.value = d
      resByUid.value = new Map(d.points.map(p => [p.uid, p]))
      listLimit.value = 12
      listLine.value = 'all'
      toast.show(
        t('toast.batchDone', {
          storm: stormLabel.value,
          n: d.points.length,
          pumps: d.summary.pumps_required,
          v: fmt(d.summary.shortfall_m3),
          skipped: d.skipped.length ? t('toast.batchSkipped', { n: d.skipped.length }) : '',
        }),
      )
    } catch (e) {
      toast.show(t('toast.batchFailed', { msg: esc(e.message) }), 'var(--red)')
    } finally {
      running.value = false
    }
  }

  /** 取「这个点 × 选中的这一级」的默认降雨参数（`/api/storm-preset`）。
   *  它不跑防线计算，只把 `rational.evaluate()` 第 1–2 步要用的历时与强度、
   *  以及该点解算后的逐点输入摆出来 —— 让人在按「计算」之前先看清算的是什么。 */
  let presetToken = 0
  async function loadPreset() {
    if (!sel.value) {
      preset.value = null
      presetLoading.value = false
      return
    }
    const token = ++presetToken
    presetLoading.value = true
    preset.value = null
    try {
      const d = await fetchStormPreset({
        ...pointInputsBody(),
        uid: sel.value,
        return_period_yr: curveRp.value,
      })
      if (presetToken === token) preset.value = d
    } catch (e) {
      if (presetToken === token) {
        preset.value = null
        toast.show(t('toast.presetFailed', { msg: esc(e.message) }), 'var(--red)')
      }
    } finally {
      if (presetToken === token) presetLoading.value = false
    }
  }

  /** 单点计算：只算当前选中的那一级（`/api/point-curve`，逐行走的是全域批算
   *  同一条计算链，故同一行数字与批算逐字段相等）。算过的级按级累积，
   *  想比较就把几级各算一遍；换点或改参数即整份作废。 */
  async function runPoint(uid = sel.value) {
    if (!uid || curveLoading.value) return
    const target = useCustom.value ? 0 : curveRp.value
    curveLoading.value = true
    try {
      const d = await runPointCurve({
        ...pointInputsBody(),
        uid,
        return_periods: [target],
        assumptions: asm.value,
      })
      d.ranAt = nowStamp()
      // 同一个点、同一套参数下算过的其它级留着（自定义雨自成一档，不与重现期混）
      const keep = curve.value && curve.value.point.uid === uid && !useCustom.value ? curve.value.scenarios : []
      curve.value = {
        ...d,
        scenarios: keep
          .filter(x => !d.scenarios.some(y => y.return_period_yr === x.return_period_yr))
          .concat(d.scenarios)
          .sort((x, y) => x.return_period_yr - y.return_period_yr),
      }
      curveRp.value = target
      const row = currentRow.value
      toast.show(
        row
          ? t('toast.pointDone', {
              uid: d.point.uid,
              location: esc(d.point.location),
              rp: row.return_period_yr
                ? t('toast.pointRpStd', { n: row.return_period_yr })
                : t('toast.pointRpCustom', { p: custom.P, d: custom.D }),
              verdict: lineLabel(row),
            })
          : t('toast.pointNoResult', {
              uid: d.point.uid,
              reasons: d.skipped.map(x => esc(x.reason)).join('; '),
            }),
        // line 为 null（没跑过演算）给中性色 —— 绿色是「没事」的意思
        row && row.line === null
          ? 'rgba(255,255,255,.45)'
          : row && row.line === 3
            ? 'var(--amber)'
            : 'var(--green)',
      )
    } catch (e) {
      toast.show(t('toast.pointFailed', { msg: esc(e.message) }), 'var(--red)')
    } finally {
      curveLoading.value = false
      askMap('popup', uid)
    }
  }

  /* ---------------- 模型输入抽屉 ---------------- */
  const nextV = () => {
    const [a, b] = inputs.v.split('.').map(Number)
    return `${a}.${b + 1}`
  }

  function openDrawer() {
    draft.value = deepCopy({
      assumptions: inputs.assumptions,
      profiles: inputs.profiles,
      priority: inputs.priority,
      zeroQcap: inputs.zeroQcap,
      coverageOnly: inputs.coverageOnly,
    })
    drawer.value = true
    tab.value = 'profiles'
  }

  function cancelDrawer() {
    draft.value = null
    drawer.value = false
    toast.show(t('toast.draftDropped', { v: inputs.v }))
  }

  function saveDrawer() {
    const D = draft.value
    const changed = []
    for (const k of Object.keys(D.assumptions))
      if (D.assumptions[k] !== inputs.assumptions[k])
        changed.push(`${k} ${inputs.assumptions[k]} → ${D.assumptions[k]}`)
    for (const g of Object.keys(D.profiles))
      for (const f of Object.keys(D.profiles[g]))
        if (D.profiles[g][f] !== inputs.profiles[g][f])
          changed.push(
            `${g === '_default' ? t('toast.changedOther') : g} ${f} ${inputs.profiles[g][f]} → ${D.profiles[g][f]}`,
          )
    const onOff = v => t(v ? 'toast.on' : 'toast.off')
    if (String(D.priority) !== String(inputs.priority))
      changed.push(t('toast.changedPriority', { v: D.priority }))
    if (D.zeroQcap !== inputs.zeroQcap)
      changed.push(t('toast.changedZeroQcap', { v: onOff(D.zeroQcap) }))
    if (D.coverageOnly !== inputs.coverageOnly)
      changed.push(t('toast.changedCoverageOnly', { v: onOff(D.coverageOnly) }))

    const v = nextV()
    const ts = nowStamp()
    Object.assign(inputs, {
      v,
      ts,
      assumptions: D.assumptions,
      profiles: D.profiles,
      priority: D.priority,
      zeroQcap: D.zeroQcap,
      coverageOnly: D.coverageOnly,
    })
    history.value.push({ v, ts, what: changed.length ? changed.join(' · ') : t('toast.noChange') })
    draft.value = null
    drawer.value = false

    if (mode.value === 'point') {
      const had = !!(curve.value && curve.value.scenarios.length)
      curve.value = null
      if (sel.value) loadPreset()
      toast.show(
        t('toast.saved', {
          v,
          n: changed.length,
          tail: had ? t('toast.savedInvalidated') : '',
        }),
      )
      return
    }
    toast.show(
      t('toast.saved', {
        v,
        n: changed.length,
        tail: result.value ? t('toast.savedRerun') : '',
      }),
    )
    if (result.value) run()
  }

  /* ---------------- 语言切换 ----------------
     后端产出的那批展示文案（IDF 口径说明、limitations、caveats、出处标签、
     泵分档的 basis/reference）是随结果一起发回来的，换语言后得重新取一遍 ——
     否则一屏中文里躺着一段旧英文。

     输入一个字节都不改，故重算出来的数字与原来逐字段相等；
     这里全程不弹提示，语言切换本身已经有一条了。 */
  async function refetchLocalised() {
    // 两套点集：meta 里的 caveats / profile_field_basis / 各种 source 都是后端文案
    for (const src of SOURCE_KEYS) {
      if (!sets[src].points.length) continue
      try {
        const d = await fetchHotspots(src)
        sets[src] = { points: d.points, meta: d }
      } catch {
        // 拿不到就留着旧的一份，界面照常 —— 语言切换不该把点集弄丢
      }
    }

    // 模型片区：成因名、run 自述、使用边界全是后端文案，换了语言得重取一份
    if (model.value) {
      try {
        const d = await fetchModelPonding()
        if (d.available) model.value = d
      } catch {
        // 同样留着旧的一份 —— 语言切换不该把已经看着的那批片区弄丢
      }
      if (sel.value) askMap('popup', sel.value)
    }

    if (sel.value) loadPreset()

    if (result.value) {
      try {
        const d = await runScenario({
          ...pointInputsBody(),
          source: source.value,
          return_period_yr: rp.value,
          assumptions: asm.value,
          coverage_only: inputs.coverageOnly,
          municipality: filters.municipality,
          criticality: filters.criticality,
          root_cause: filters.root_cause,
          district: filters.district,
        })
        d.ranAt = result.value.ranAt // 还是那一次计算，不改时间戳
        result.value = d
        resByUid.value = new Map(d.points.map(p => [p.uid, p]))
      } catch {
        // 同上：算过的结论留在屏幕上，只是那几行后端文案仍是上一种语言
      }
    }

    const c = curve.value
    if (c && c.scenarios.length) {
      try {
        const d = await runPointCurve({
          ...pointInputsBody(),
          uid: c.point.uid,
          return_periods: useCustom.value ? [0] : c.scenarios.map(r => r.return_period_yr),
          assumptions: asm.value,
        })
        d.ranAt = c.ranAt
        curve.value = d
      } catch {
        // 同上
      }
      askMap('popup', c.point.uid)
    }
  }

  /* ---------------- 管网图层 ---------------- */

  /** 按需取一层管网线，幂等 —— 地图每次缩放都会问一次「支管该取了吗」。
   *  取失败记成 'failed' 而不是清回 null，否则缩放一次重试一次，
   *  后端不通时会把失败提示刷满屏。要重试就关掉按钮再打开。 */
  async function loadNetwork(layer) {
    if (network[layer]) return
    network[layer] = 'loading'
    toast.show(t(`toast.network${layer === 'mains' ? 'Mains' : 'Laterals'}Loading`))
    try {
      const fc = await fetchNetwork(layer)
      if (!fc.available) {
        network[layer] = 'failed'
        toast.show(t('toast.networkMissing'), 'var(--amber)')
        return
      }
      network[layer] = fc
      const km = (fc.features || []).reduce((a, f) => a + (f.properties.length_km || 0), 0)
      toast.show(t('toast.networkLoaded', { km: fmt(km, 0) }))
    } catch (e) {
      network[layer] = 'failed'
      toast.show(t('toast.networkFailed', { msg: esc(e.message) }), 'var(--red)')
    }
  }

  /** 开关管网线。打开时顺手把干管取回来；支管等地图放大到它起画的级别再说。 */
  function toggleNetwork() {
    showNetwork.value = !showNetwork.value
    if (showNetwork.value) loadNetwork('mains')
    else toast.show(t('toast.networkOff'))
  }

  /* ---------------- 启动 ---------------- */

  /** 取一套点集。幂等 —— 两边各缓存一份，来回切不重打接口。 */
  async function loadPoints(src) {
    if (sets[src].points.length) return true
    const d = await fetchHotspots(src)
    sets[src] = { points: d.points, meta: d }
    return true
  }

  async function boot() {
    try {
      await loadPoints('ledger')
      const d = sets.ledger.meta
      inputs.profiles = deepCopy(d.profiles)
      inputs.ts = nowStamp()
      askMap('fit')
      const c = d.coverage
      toast.show(
        t('toast.booted', {
          n: d.count,
          inside: c.inside,
          outside: c.outside,
          byMuni: Object.entries(c.outside_by_municipality)
            .map(([k, v]) => `${esc(muniLabel(k))} ${v}`)
            .join(' · '),
        }),
      )
    } catch (e) {
      toast.show(t('toast.bootFailed', { msg: esc(e.message) }), 'var(--red)')
    }
    // 覆盖面是锦上添花：拿不到只是不画面，不影响算哪些点。
    try {
      const cov = await fetchCoverage()
      if (cov.available) coverage.value = cov
    } catch (e) {
      console.warn(t('toast.coverageFailed'), e.message)
    }
    // 片区轮廓同理：拿不到只是不画框，片区筛选靠逐点的 district_key 照常工作。
    try {
      const dis = await fetchDistricts()
      if (dis.available) districts.value = dis
    } catch (e) {
      console.warn(t('toast.districtsFailed'), e.message)
    }
  }

  return {
    // state
    points, byUid, meta, sets, coverage, districts, network,
    source, model, modelLoading, modelMech,
    mode, curve, curveRp, curveLoading, preset, presetLoading,
    result, resByUid, running,
    dataset, rp, custom, useCustom,
    inputs, over, draft, history,
    filters, sel, panel, brief, drawer, tab, listLimit, listLine, basemap, showCoverage, showNetwork,
    q, qHits, qIdx, mapQueue,
    // derived
    asm, overCount, stormLabel, filtered, currentRow, computedRps, holdSummary,
    summaryTiers, summaryRefTiers, pumpUnitCapacity, pumpUnitFromTiers, districtFacet, groupCounts, ponding, pondingWindowLabel, selPonding,
    modelFeatures, modelMechRows, modelSelFeature, featureByRank,
    // helpers
    inScope, isComputed, resFor, colorFor, lineLabel, pumpBrief: brief_,
    qcapBasisCount, qcapEditableCount, catchmentEditableCount,
    districtRow, districtLabel, districtPondingOf, pondingOf, blockedBy, searchHits, nextV,
    // actions
    askMap, drainMapQueue, setDistrict, toggleQuickDistrict, setQuery, chooseHit, select, setMode,
    invalidatePoint, toggleFilter, clearFilters, setDataset, setStorm, setCurveRp,
    loadNetwork, toggleNetwork,
    setSource, loadModel, loadPoints, toggleMech,
    run, runPoint, loadPreset, openDrawer, cancelDrawer, saveDrawer, boot, refetchLocalised,
  }
})
