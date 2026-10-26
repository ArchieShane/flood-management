<script setup>
/* 「积水点」标签：RD-A（`RdaPanels.vue`）与全市一二维任务（`PondingPointsPanel.vue`）共用这一份，内容和布局与 RD-A 原来的完全一致：
   积水点阈值 → 覆盖的客户热点（热点覆盖率 / 积水量覆盖率 / 各状态并排 / 口径 / 热点表）→ 积水点列表与详情卡片。
   两边的数据层名字一致（`useRda()` / `usePondingPoints()`），传进来的 `rda`；全市多出的只有：网格说明、不在计算域内的热点、
   热点和积水点很多时的搜索 / 分页。点行时往外抛 `locate`，由外面的地图去飞；本组件不碰地图。 */
import { computed, ref, unref } from 'vue'

import { DEPTH_CHOICES } from '../../composables/useRda'
import { tr, trj } from '../../i18n/rda'
import '../../styles/rda.css'

const props = defineProps({ rda: { type: Object, required: true } })
const emit = defineEmits(['locate'])
const R = props.rda   // useRda() / usePondingPoints() 返回的是一束 ref，模板里 .value 会自动解包

const f1 = v => (v == null ? '—' : Number(v).toLocaleString('en-US', { maximumFractionDigits: 1 }))
const f2 = v => (v == null ? '—' : Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 }))
const int = v => (v == null ? '—' : Math.round(Number(v)).toLocaleString('en-US'))
const pct = v => (v == null ? '—' : `${Number(v).toFixed(1)}%`)
const at = h => (h == null ? '' : `@ ${Number(h).toFixed(2)} h`)

const LEVEL_COLOR = { 关键: '#d9434b', 高: '#e0702e', 中: '#e0a44e', 无暴露: '#7a838c' }
const outside = computed(() => unref(R.outsideDomain) || [])
const gridNote = computed(() => unref(R.gridNote) || '')
/** 积水点列表：全市有 shownPoints（默认前 100 片），RD-A 没有就是全部 */
const listPoints = computed(() => (R.shownPoints || R.visiblePoints).value)

/** 热点表：RD-A 只有 11 行，全部列出；全市 470 行，加搜索并分批显示 */
const hotQ = ref('')
const hotN = ref(50)
const manyHot = computed(() => (R.hotspotCoverage.value?.rows.length || 0) > 30)
const hotRows = computed(() => {
  const rows = R.hotspotCoverage.value?.rows || []
  if (!manyHot.value) return rows
  const q = hotQ.value.trim().toLowerCase()
  return (q ? rows.filter(r => `${r.id} ${r.area || ''} ${r.location || ''}`.toLowerCase().includes(q)) : rows).slice(0, hotN.value)
})

function pickPoint(id) {
  R.selPoint.value = id
  const p = (R.ponding.value?.points || []).find(x => x.id === id)
  if (p) emit('locate', { lat: p.lat, lon: p.lon, kind: 'point', id })
}
function pickHotspot(h) {
  if (h.lat != null && h.lon != null) emit('locate', { lat: h.lat, lon: h.lon, kind: 'hotspot', id: h.id })
}
defineExpose({ pickPoint })
</script>

<template>
    <div class="pane">
      <p v-if="gridNote" class="muted small">{{ tr(gridNote) }}</p>
      <div class="card thr">
        <h4>{{ tr('积水点阈值') }}</h4>
        <div class="thr-row">
          <label>{{ tr('水深 ≥') }}
            <select v-model.number="rda.pf.value.depth">
              <option v-for="d in DEPTH_CHOICES" :key="d" :value="d">{{ d.toFixed(2) }} m</option>
            </select>
          </label>
          <label>{{ tr('连片 ≥') }} <input v-model.number="rda.pf.value.area" type="number" min="0" step="50" /> m²</label>
          <label>{{ tr('持续 ≥') }} <input v-model.number="rda.pf.value.dur" type="number" min="0" step="0.25" /> h</label>
          <button class="go" :disabled="!rda.formDirty.value" @click="rda.applyThreshold()">{{ tr('重算') }}</button>
        </div>
        <p class="muted small">
          <template v-if="rda.ponding.value?.custom">{{ tr(rda.hasDelivered === false ? (rda.ponding.value.note || '已按所给阈值从二维结果重算。') : '已按所给阈值从二维结果重算：三角网共边连片，不扣地表塘占地，没有 L3 承接与评估剔除标记。') }}</template>
          <template v-else>{{ tr('现在是成果自带的清单（0.15 / 0.30 m，100 m²，0.5 h；含 L3 承接与剔除标记）。改任一阈值再点「重算」会从二维结果现算。') }}</template>
          <a v-if="!rda.isDelivered.value" href="#" @click.prevent="rda.presetDepth(0.15)">{{ rda.hasDelivered === false ? tr('回到默认') : tr('回到成果自带') }}</a>
        </p>
      </div>
      <div v-if="rda.hotspotCoverage.value" class="card">
        <h4>{{ tr('覆盖的客户热点') }} {{ rda.hotspotCoverage.value.covered }} / {{ rda.hotspotCoverage.value.total }}</h4>
        <div class="kpis">
          <div><b>{{ pct(rda.hotspotCoverage.value.rate) }}</b><span>{{ tr('热点覆盖率（被覆盖热点数 / {n}）', { n: rda.hotspotCoverage.value.total }) }}</span></div>
          <div><b>{{ pct(rda.hotspotCoverage.value.insidePct) }}</b><span>{{ tr('积水量覆盖率（热点 200 m 内的积水量占比）') }}</span></div>
        </div>
        <table v-if="rda.coverageAll.value" class="tbl">
          <thead><tr><th>{{ tr('状态') }}</th><th>{{ tr('覆盖热点') }}</th><th>{{ tr('热点覆盖率') }}</th><th>{{ tr('积水量覆盖率') }}</th></tr></thead>
          <tbody>
            <tr v-for="c in rda.coverageAll.value" :key="c.key" :class="{ cur: c.key === rda.stateKey.value }">
              <td>{{ c.key }}</td>
              <td>{{ c.covered == null ? '—' : `${c.covered} / ${c.total}` }}</td>
              <td>{{ pct(c.rate) }}</td>
              <td>{{ pct(c.insidePct) }}</td>
            </tr>
          </tbody>
        </table>
        <p class="muted small">{{ tr('按当前状态、当前阈值算出的积水点，200 m 内有积水点即算覆盖该热点；未覆盖 = 这一态下热点周边已没有达标的积水点。点编号可定位。') }}</p>
        <p v-if="rda.hotspotCoverage.value.insidePct != null" class="small">
          {{ tr('热点 200 m 内 {a} 片 / {n} 片，积水量 {v} m³，占 {p}%；其余 {q}% 在热点范围之外。', {
            a: rda.hotspotCoverage.value.nInside, n: rda.hotspotCoverage.value.nPoints, v: int(rda.hotspotCoverage.value.volInside),
            p: f1(rda.hotspotCoverage.value.insidePct), q: f1(100 - rda.hotspotCoverage.value.insidePct) }) }}
        </p>
        <p v-if="rda.hotspotCoverage.value.nExcluded" class="muted small">
          {{ tr('已不计入 {n} 片：一半以上面积落在评估剔除区内（列表里标「剔」），与客户重合分析文档同口径。', { n: rda.hotspotCoverage.value.nExcluded }) }}
        </p>
        <p v-if="outside.length" class="muted small">
          {{ tr('热点按交付的 {n} 个算（台账 ADM 506 个里落在二维计算域内的）；另 {m} 个不在计算域内，不进分母。', { n: rda.hotspotCoverage.value.total, m: outside.length }) }}
        </p>
        <details class="logic">
          <summary>{{ tr('覆盖是怎么算的（口径）') }}</summary>
          <ol>
            <li v-if="rda.hasDelivered !== false"><b>{{ tr('覆盖率') }}</b>：{{ tr('热点覆盖率 = 被覆盖的热点数 ÷ 热点总数（11）；积水量覆盖率 = 热点 200 m 内的积水量 ÷ 全部积水量，两个都不含被剔除的片。上面的小表是四个状态在同一套阈值下的并排对比，当前状态高亮。') }}</li>
            <li v-else><b>{{ tr('覆盖率') }}</b>：{{ tr('热点覆盖率 = 被覆盖的热点数 ÷ 热点总数；积水量覆盖率 = 热点 200 m 内的积水量 ÷ 全部积水量。上面的小表是各状态在同一套阈值下的并排对比，当前状态高亮。') }}</li>
            <li><b>{{ tr('积水点') }}</b>：{{ tr('当前状态的二维结果里，全程最大水深 ≥ 阈值的单元按三角网共边连成片，去掉面积不足连片下限、持续不足时长下限的片；阈值就是上面「积水点阈值」那一栏（成果自带 0.15 / 0.30 m、100 m²、0.5 h）。') }}</li>
            <li v-if="rda.hasDelivered !== false"><b>{{ tr('覆盖') }}</b>：{{ tr('客户热点（RD-A 交付的 11 个，只有坐标）到某个积水点的距离 ≤ 200 m，就算这个积水点覆盖了该热点；距离取热点到片内最近单元形心。同一热点可被几个点覆盖，表里按距离由近到远列出。') }}</li>
            <li v-else><b>{{ tr('覆盖') }}</b>：{{ tr('客户热点（交付的热点，只有坐标）到某个积水点的距离 ≤ 200 m，就算这个积水点覆盖了该热点；距离按客户文档量：热点到最近积水片边界的平面距离，热点落在积水片里为 0 m。同一热点可被几个点覆盖，表里按距离由近到远列出。') }}</li>
            <li><b>{{ tr('未覆盖') }}</b>：{{ tr('这一状态下热点 200 m 内已经没有达标的积水点，意思是该处不再积水或积得不够深、不够久，不是「没有算到」。') }}</li>
            <li v-if="rda.hasDelivered !== false"><b>{{ tr('不计入的片') }}</b>：{{ tr('一半以上面积落在评估剔除区内的积水片不计入覆盖，也不进下面的占比（与客户重合分析文档同口径）。剔除区有两处：ADM-80 岸边约 9.7 ha 的 DTM 高程恰为 0.00 m（判为缺测填零），ADM-161 东侧私人地块的深坑。') }}</li>
            <li><b>{{ tr('占比') }}</b>：{{ tr('「热点 200 m 内」的积水量 = 这些积水点的峰值积水量之和，除以全部（不含被剔除的）积水点的峰值积水量之和；每个点只算一次。各点峰值时刻不同，所以这是量级参考，不是某一时刻的水量。按整片算：只要一片有一部分在热点 200 m 内，整片的水量都计入分子，不是只算 200 m 圈内的那部分水，所以这个比例偏乐观，圈内的实际水量比它小。') }}</li>
            <li><b>{{ tr('不是什么') }}</b>：{{ tr('这只是空间位置的比对，不是模型验证：热点没有水深、范围和发生日期，模型也没有率定。「覆盖 x / 11」与「判据」页的 A / B / C 达标不是一回事，也不等于积水面积的削减比例。') }}</li>
          </ol>
        </details>
        <input v-if="manyHot" v-model="hotQ" type="search" class="hot-q" :placeholder="tr('搜编号 / 片区 / 位置')" />
        <table class="tbl">
          <thead><tr><th>{{ tr('热点') }}</th><th>{{ tr('覆盖') }}</th><th>{{ tr('覆盖它的积水点（距离）') }}</th></tr></thead>
          <tbody>
            <tr v-for="h in hotRows" :key="h.id" @click="pickHotspot(h)">
              <td :title="h.location">{{ h.id }}<span v-if="h.area" class="muted small"> · {{ h.area }}</span></td>
              <td><b :class="h.covered ? 'bad' : 'ok'">{{ h.covered ? tr('覆盖') : tr('未覆盖') }}</b></td>
              <td>
                <a v-for="x in h.points" :key="x.id" href="#" class="chip" @click.prevent="pickPoint(x.id)">{{ x.id.replace('SIM-', '') }} {{ x.dist_m }} m</a>
                <span v-if="!h.points.length" class="muted">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="row">
        <span class="seg">
          <button :class="{ on: rda.pointFilter.value === 'all' }" @click="rda.pointFilter.value = 'all'">{{ tr('全部') }}</button>
          <button :class="{ on: rda.pointFilter.value === 'notRecede' }" @click="rda.pointFilter.value = 'notRecede'">{{ tr('未退') }}</button>
          <button v-if="!rda.ponding.value?.custom" :class="{ on: rda.pointFilter.value === 'l3' }" @click="rda.pointFilter.value = 'l3'">{{ tr('要 L3') }}</button>
          <button v-if="!rda.ponding.value?.custom" :class="{ on: rda.pointFilter.value === 'excluded' }" @click="rda.pointFilter.value = 'excluded'">{{ tr('剔除区') }}</button>
        </span>
        <span class="muted">
          {{ tr('{n} 片 · 峰值合计 {v} m³ · 未退 {k}', { n: rda.visiblePoints.value.length, v: int(rda.ponding.value?.peak_vol_sum_m3), k: rda.ponding.value?.not_receded }) }}
        </span>
      </div>
      <label class="small"><input v-model="rda.nearOnly.value" type="checkbox" /> {{ tr('只看客户热点 200 m 内') }}</label>
      <p class="muted small">{{ tr('编号 SIM-态-序号是模型算出的积水点，不是客户热点；按峰值积水量降序，只在同一状态、同一阈值内有效。') }}</p>
      <div v-if="rda.selectedPoint.value" class="card">
        <h4>
          {{ rda.selectedPoint.value.id }}
          <span v-if="rda.selectedPoint.value.l3" class="pill" :style="{ background: LEVEL_COLOR[rda.selectedPoint.value.l3.level] }">{{ tr(rda.selectedPoint.value.l3.level) }}</span>
          <span v-if="rda.selectedPoint.value.excluded" class="pill gray">{{ tr('评估剔除区') }}</span>
          <span v-else-if="rda.selectedPoint.value.mostly_excluded" class="pill gray">{{ tr('多半在剔除区') }}</span>
        </h4>
        <dl class="kv">
          <dt>{{ tr('最大水深') }}</dt><dd>{{ f2(rda.selectedPoint.value.hmax_m) }} m（{{ tr('地面高程') }} {{ f2(rda.selectedPoint.value.ground_z_m) }} m）<template v-if="rda.selectedPoint.value.t_hmax_h != null">，{{ tr('出现在') }} {{ f2(rda.selectedPoint.value.t_hmax_h) }} h</template></dd>
          <dt>{{ tr('面积') }}</dt><dd>{{ int(rda.selectedPoint.value.area_m2) }} m²（{{ tr('其中') }} ≥0.30 m：{{ int(rda.selectedPoint.value.area_ge030_m2) }} m²）</dd>
          <template v-if="rda.selectedPoint.value.area_peak_m2 != null">
            <dt>{{ tr('最大积水面积') }}</dt><dd>{{ int(rda.selectedPoint.value.area_peak_m2) }} m²，{{ tr('出现在') }} {{ f2(rda.selectedPoint.value.t_area_peak_h) }} h</dd>
          </template>
          <dt>{{ tr('峰值积水量') }}</dt><dd>{{ int(rda.selectedPoint.value.vol_peak_m3) }} m³，{{ tr('出现在') }} {{ f2(rda.selectedPoint.value.t_peak_h) }} h</dd>
          <dt>{{ tr('持续') }}</dt><dd>{{ f2(rda.selectedPoint.value.duration_h) }} h</dd>
          <dt>{{ tr('退水') }}</dt>
          <dd>
            <b :class="rda.selectedPoint.value.receded ? 'ok' : 'bad'">{{ rda.selectedPoint.value.receded ? tr('已退') : tr('未退') }}</b>
            <template v-if="rda.selectedPoint.value.receded"> · {{ tr('峰值后') }} {{ f2(rda.selectedPoint.value.recede_h) }} h</template>
            <template v-else> · {{ tr('到 {t} h 仍有 {v} m³', { t: rda.selectedPoint.value.t_end_h, v: int(rda.selectedPoint.value.vol_end_m3) }) }}</template>
          </dd>
          <dt>{{ tr('最近客户热点') }}</dt>
          <dd>{{ rda.selectedPoint.value.nearest_client_hotspot }}（{{ int(rda.selectedPoint.value.nearest_client_hotspot_dist_m) }} m）</dd>
          <dt>{{ tr('200 m 内热点') }}</dt>
          <dd>
            <template v-if="rda.selectedPoint.value.near_hotspots.length">
              <span v-for="h in rda.selectedPoint.value.near_hotspots" :key="h.hotspot" class="chip">{{ h.hotspot }} {{ h.dist_m }} m</span>
            </template>
            <template v-else>{{ tr('无') }}</template>
          </dd>
          <template v-if="rda.selectedPoint.value.excluded">
            <dt>{{ tr('剔除说明') }}</dt><dd>{{ trj(rda.selectedPoint.value.exclusion_note) }}（{{ tr('扣除后') }} {{ int(rda.selectedPoint.value.area_after_exclusion_m2) }} m²）</dd>
          </template>
          <dt>{{ tr('连片方式') }}</dt><dd>{{ rda.selectedPoint.value.adjacency === 'mesh' ? tr('三角网共边') : tr('单元近邻近似') }}</dd>
        </dl>
        <template v-if="rda.selectedPoint.value.l3">
          <h5>{{ tr('L3 承接') }}</h5>
          <dl class="kv">
            <dt>{{ tr('结论') }}</dt><dd>{{ tr(rda.selectedPoint.value.l3.verdict) }}</dd>
            <dt>{{ tr('定级依据') }}</dt><dd>{{ trj(rda.selectedPoint.value.l3.basis) }}</dd>
            <dt>{{ tr('L3 手段') }}</dt><dd>{{ tr(rda.selectedPoint.value.l3.measure) }}</dd>
            <dt>{{ tr('退干期限') }}</dt><dd>{{ f1(rda.selectedPoint.value.l3.deadline_h) }} h（{{ tr('自然退干') }} {{ rda.selectedPoint.value.l3.natural_drain_h ?? '—' }} h）</dd>
            <dt>{{ tr('300 m 内单位') }}</dt><dd>{{ rda.selectedPoint.value.l3.units_300m || '—' }}</dd>
            <dt>Island A13</dt>
            <dd>{{ tr(rda.selectedPoint.value.l3.island.result) }} · {{ rda.selectedPoint.value.l3.island.units ?? 0 }} {{ tr('台/辆') }} · {{ tr('到位') }} {{ rda.selectedPoint.value.l3.island.arrive_h ?? '—' }} h · {{ tr('完成') }} {{ rda.selectedPoint.value.l3.island.done_h ?? '—' }} h</dd>
            <dt>{{ tr('ADM 全驻地') }}</dt>
            <dd>{{ tr(rda.selectedPoint.value.l3.adm.result) }} · {{ rda.selectedPoint.value.l3.adm.units ?? 0 }} {{ tr('台/辆') }} · {{ tr('到位') }} {{ rda.selectedPoint.value.l3.adm.arrive_h ?? '—' }} h · {{ tr('完成') }} {{ rda.selectedPoint.value.l3.adm.done_h ?? '—' }} h</dd>
            <template v-if="rda.selectedPoint.value.l3.note"><dt>{{ tr('备注') }}</dt><dd>{{ tr(rda.selectedPoint.value.l3.note) }}</dd></template>
          </dl>
        </template>
      </div>
      <table class="tbl">
        <thead>
          <tr>
            <th>{{ tr('编号') }}</th><th>{{ tr('最大水深 m（时刻）') }}</th><th>{{ tr('最大面积 m²（时刻）') }}</th><th>{{ tr('最大积水量 m³（时刻）') }}</th><th>{{ tr('退水') }}</th>
            <th v-if="!rda.ponding.value?.custom">{{ tr('等级') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in listPoints" :key="p.id" :class="{ cur: p.id === rda.selPoint.value }" @click="pickPoint(p.id)">
            <td>{{ p.id.replace('SIM-', '') }}<i v-if="p.excluded || p.mostly_excluded" class="pill gray" :title="p.mostly_excluded ? tr('一半以上面积落在评估剔除区内，不计入热点覆盖') : ''">{{ tr('剔') }}</i></td>
            <td>{{ f2(p.hmax_m) }}<small class="tm">{{ at(p.t_hmax_h) }}</small></td>
            <td>{{ p.area_peak_m2 == null ? '—' : int(p.area_peak_m2) }}<small class="tm">{{ at(p.t_area_peak_h) }}</small></td>
            <td>{{ int(p.vol_peak_m3) }}<small class="tm">{{ at(p.t_peak_h) }}</small></td>
            <td :class="p.receded ? '' : 'bad'">{{ p.receded ? f1(p.recede_h) + ' h' : tr('未退') }}</td>
            <td v-if="!rda.ponding.value?.custom">
              <span v-if="p.l3" class="pill" :style="{ background: LEVEL_COLOR[p.l3.level] }">{{ tr(p.l3.level) }}</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="rda.shownPoints && rda.visiblePoints.value.length > 100" class="small">
        <a href="#" @click.prevent="rda.showAll.value = !rda.showAll.value">
          {{ rda.showAll.value ? tr('只看前 {n} 片', { n: 100 }) : tr('显示全部 {n} 片', { n: rda.visiblePoints.value.length }) }}
        </a>
      </p>
    </div>
</template>
