<script setup>
/* 任务详情：「Open ›」落到这里。挂了交付成果的任务（has_layers）先出结果地图（最大水深 /
   时间过程），下面是本次降雨的雨型图（设计暴雨才有），再列任务参数、结果指标与分析标签；排队中的任务可取消。
   地图右侧是「{防线}仿真」总览（LevelPanel）：只出溢水量 / 最大积水面积 / 最大积水深度 / 系统储水能力四项，
   切防线（L 等级）标签就出到该等级为止的对比（L1 / L1 vs L2 / L1、L2 与规划态）；地图播放或拖动时换成本帧当前值（mapNow）。
   右上角是防线切换（Line 1 / Line 2 Current / Line 2 Planned，同一场雨的三个任务，见后端
   simulation._line_runs）与「Compare」：开了对比，右侧总览换成三道并排（RunCompare）；
   对比开关记在 ?compare=1，切防线时带着走。差距分析页（Figma 04）还没做。
   多态任务（run.states，一个任务涵盖几种工况，如 Mussafah 四态 L1 / L2 / L2+A / L2+B）右上角换成态切换，
   当前态记在 ?state=（默认态不写），地图、总览、对比都按态取；总览里的防线与雨停后时长取该态自己的。
   效果分析（?view=perf，总览底部按钮进来，多态任务才有）：既有 = 第一态，方案 = ?vs=（不给取最后一态），
   时刻档 ?h=；地图画方案态水深、溢水点取第一态并按对照类别着色，右侧换 PerfPanel。
   全市任务（run.has_l2，#100 / #101 / #102）的「第二道现状」不跳到别的任务，而是本任务的第二道视图（?line=l2）：
   右侧总览的第二道溢水量、面积、水深按 L1 × (1 − 一维报告减少比例) 折算（sim_l2.estimate），储水能力取一维报告。
   多态任务（Mussafah #191）的总览四项全部取效果分析的 columns（交付实算，不折算）；切到 L2 态地图另叠已建成调蓄塘；对比按钮收起。 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { cancelSimulation, fetchSimulation, fetchSimulationL2, fetchSimulationOptions, fetchSimulationPerf } from '../api'
import AppIcon from '../components/AppIcon.vue'
import ResultMap from '../components/sim/ResultMap.vue'
import RunCompare from '../components/sim/RunCompare.vue'
import LevelPanel from '../components/sim/LevelPanel.vue'
import PerfPanel from '../components/sim/PerfPanel.vue'
import RunHyetograph from '../components/sim/RunHyetograph.vue'
import RunSummary from '../components/sim/RunSummary.vue'
import SimShell from '../components/sim/SimShell.vue'
import { locale, t } from '../i18n'
import { useToastStore } from '../stores/toast'
import { PERF_COLOR, perfClass, perfPopup } from '../utils/perf'
import { analysisLabel, fmtInt, fmtWhen, stateCode, statusLabel } from '../utils/sim'

const props = defineProps({ id: { type: String, required: true } })
const route = useRoute()
const router = useRouter()
const toast = useToastStore()

const run = ref(null)
const options = ref(null)
const mapRef = ref(null)
const mapNow = ref(null)   // 地图时间过程下的本帧当前值，右侧总览跟着换
const layerMeta = ref(null)
const ponding = ref(null)
const hotspots = ref(null)   // /hotspots，ResultMap 取回后抛上来，右侧总览出报告口径对比
const pondErr = ref('')
const pondActive = ref(null)
const onPonding = (p, err) => {
  ponding.value = p
  pondErr.value = err
}

async function load() {
  try {
    ;[run.value, options.value] = await Promise.all([fetchSimulation(props.id), fetchSimulationOptions()])
    if (run.value.status === 'draft') router.replace(`/simulations/${props.id}/edit`)
  } catch (e) {
    toast.show(e.message, 'var(--red)')
  }
}
watch([() => props.id, locale], load, { immediate: true })
watch(() => props.id, () => {
  layerMeta.value = ponding.value = pondActive.value = hotspots.value = null
  pondErr.value = ''
})

const res = computed(() => run.value?.result)
const isCustom = computed(() => run.value?.rain_source === 'design_storm' && !run.value?.storm_preset_key)
const isPreset = computed(() => options.value?.storm_presets.find(p => p.key === run.value?.storm_preset_key))
const metrics = computed(() => [
  ['stillPond', res.value?.still_pond_count],
  ['drained', res.value?.drained_volume_m3],
  ['overflow', res.value?.overflow_node_count],
  ['duration', res.value?.ponding_duration_h],
  ['validation', res.value?.validation_hit_rate_pct != null ? `${fmtInt(res.value.validation_hit_rate_pct)}%` : null],
])

const states = computed(() => run.value?.states || null)
const stateKey = computed(() => {
  if (!states.value) return null
  return states.value.some(s => s.key === route.query.state) ? route.query.state : run.value.state_default
})
const curState = computed(() => states.value?.find(s => s.key === stateKey.value) || null)
const setState = k => router.replace({ query: { ...route.query, state: k === run.value?.state_default ? undefined : k } })
const stateTitle = s => stateCode(s.same_as ? t('sim.detail.sameAs', { label: s.label, as: s.same_as }) : s.label)
watch(stateKey, () => {
  layerMeta.value = ponding.value = pondActive.value = hotspots.value = null
  pondErr.value = ''
})
/** 总览吃的 run：多态时防线、雨停后时长换成当前态的（L2+A / L2+B 只演算到 5 h，不能沿用 L1 的） */
const viewRun = computed(() => {
  const r = run.value
  const s = curState.value
  if (!r || !s) return r
  const simH = layerMeta.value?.domain?.simulation_duration_hours
  return {
    ...r,
    defence_line_key: s.defence_line_key,
    defence_line_label: t('sim.detail.stateTitle', { label: stateCode(s.label), line: s.defence_line_label }),
    after_rain_max_h: simH != null && r.duration_h != null ? Math.round((simH - Number(r.duration_h)) * 10) / 10 : r.after_rain_max_h,
  }
})

const compare = computed(() => route.query.compare === '1')
const setCompare = on => router.replace({ query: { ...route.query, compare: on ? '1' : undefined } })
const openLine = id => id && id !== run.value?.id && router.push({ path: `/simulations/${id}`, query: route.query })
const lineTitle = lr =>
  !lr.run_id ? t('sim.detail.lineNone') : !lr.has_layers ? t('sim.detail.lineNoLayers', { id: lr.run_id }) : `#${lr.run_id}`

/* ---------------- 第二道现状（全市任务） ---------------- */
const l2View = computed(() => !!run.value?.has_l2 && route.query.view !== 'perf' &&
  (states.value ? curState.value?.defence_line_key === 'line2_current' : route.query.line === 'l2'))
/** 规划态（L2+planned / L2+suggested / L2+B）：地图注记换成该态，对比按钮收起 */
const planView = computed(() => !!run.value?.has_l2 && route.query.view !== 'perf' && !!states.value &&
  curState.value?.defence_line_key === 'line2_planned')
const l2 = ref(null)
const l2Err = ref('')
const setL2 = on => router.replace({ query: { ...route.query, line: on ? 'l2' : undefined, compare: undefined } })
/** 全市任务（#100–102）与多态 #561 一样只出 L1 / L2 两个 tab；第二道规划没有演算，不出 */
const lineTabs = computed(() => (run.value?.has_l2
  ? run.value.line_runs.filter(lr => lr.defence_line_key !== 'line2_planned') : run.value?.line_runs || []))
/** 线路 tab：全市任务的第二道现状指向本任务的第二道视图，第一道回到本视图 */
const lineOn = lr => (run.value?.has_l2 && lr.run_id === run.value.id ? !l2View.value
  : run.value?.has_l2 && lr.defence_line_key === 'line2_current' ? l2View.value : lr.run_id === run.value?.id)
function clickLine(lr) {
  if (run.value?.has_l2 && lr.defence_line_key === 'line2_current') return setL2(true)
  if (run.value?.has_l2 && lr.run_id === run.value.id) return setL2(false)
  openLine(lr.run_id)
}
async function loadL2() {
  if (!(l2View.value || planView.value) || (l2.value && l2.value.run_id === run.value.id)) return
  l2Err.value = ''
  try {
    l2.value = { ...(await fetchSimulationL2(run.value.id)), run_id: run.value.id }
  } catch (e) {
    l2.value = null
    l2Err.value = e.message
  }
}
watch([l2View, planView], loadL2, { immediate: true })
watch(() => props.id, () => { l2.value = null })

/* ---------------- 效果分析 ---------------- */
const perf = computed(() => route.query.view === 'perf' && !!states.value)
const perfOptions = computed(() => states.value?.slice(1) || [])
const perfVs = computed(() => {
  const o = perfOptions.value
  return o.some(s => s.key === route.query.vs) ? route.query.vs : o[o.length - 1]?.key
})
const perfH = computed(() => (route.query.h != null ? Number(route.query.h) : null))
const perfData = ref(null)
const perfErr = ref('')
/** 从规划态进效果分析，方案默认就是这一态；其余态进去取默认方案（最后一态） */
const openPerf = () => router.push({ query: {
  ...route.query, view: 'perf', compare: undefined, state: undefined,
  vs: planView.value && stateKey.value !== perfOptions.value.at(-1)?.key ? stateKey.value : undefined,
} })
const closePerf = () => router.push({ query: { ...route.query, view: undefined, vs: undefined, h: undefined } })
const setVs = k => router.replace({ query: { ...route.query, vs: k === perfOptions.value.at(-1)?.key ? undefined : k } })
const setH = h => router.replace({ query: { ...route.query, h: h === 2 ? undefined : h } })

let perfSeq = 0
async function loadPerf() {
  if (!perf.value) return
  const seq = ++perfSeq
  perfErr.value = ''
  try {
    const d = await fetchSimulationPerf(props.id, perfVs.value, perfH.value)
    if (seq === perfSeq) perfData.value = d
  } catch (e) {
    if (seq === perfSeq) {
      perfData.value = null
      perfErr.value = e.message
    }
  }
}
watch([perf, perfVs, perfH, () => props.id, locale], loadPerf)
// 方案或时刻一换，旧数字作废（不拿别的方案 / 时刻的分类顶着）
watch([perfVs, perfH, () => props.id], () => { perfData.value = null })

const perfFit = computed(() => (perfData.value?.vs.key === perfVs.value ? perfData.value : null))
const pondClass = computed(() => (perf.value && perfFit.value ? perfClass(perfFit.value) : null))
const pondPopup = computed(() => (perf.value && perfFit.value ? perfPopup(perfFit.value) : null))
const pondLegend = computed(() => {
  const d = perfFit.value
  if (!perf.value || !d) return null
  return {
    title: t('sim.perf.legend', { h: d.h }),
    rows: Object.keys(PERF_COLOR).map(k => ({ color: PERF_COLOR[k], label: t(`sim.perf.cat.${k}`), n: d.category_counts[k] })),
    note: t('sim.perf.catRule', { pct: d.reduced_pct, d: d.active_depth_m }),
  }
})

async function cancel() {
  try {
    run.value = await cancelSimulation(run.value.id)
    toast.show(t('sim.detail.cancelled'))
  } catch (e) {
    toast.show(e.message, 'var(--red)')
  }
}
</script>

<template>
  <SimShell :users="options?.users || []">
    <div class="wiz-head">
      <button class="wiz-back" :title="t('sim.title')" @click="router.push('/simulations')"><AppIcon name="back" :size="16" /></button>
      <h1 v-if="perf" class="sim-h1 sd-crumb">
        <button @click="closePerf">{{ t('sim.detail.title', { id }) }}</button><span>/</span>{{ t('sim.perf.crumb') }}
      </h1>
      <h1 v-else class="sim-h1">{{ t('sim.detail.title', { id }) }}</h1>
      <span v-if="perf && perfFit" class="sim-tag sd-variant">{{ stateCode(perfFit.base.label) }} vs {{ stateCode(perfFit.vs.label) }}</span>
      <span v-else-if="l2View && !planView && !(curState && !curState.same_as)" class="sim-tag sd-variant">{{ t('sim.l2.tag') }}</span>
      <span v-else-if="curState || run?.variant_label" class="sim-tag sd-variant">{{ curState ? stateTitle(curState) : stateCode(run.variant_label) }}</span>
      <span v-if="run" :class="'st-' + run.status" style="width: auto">
        <span class="sim-dot" />{{ statusLabel(run) }}
      </span>
      <div v-if="perf" class="sd-lines">
        <span class="sd-vs">{{ stateCode(states[0].key) }} vs</span>
        <div class="sd-seg" role="tablist">
          <button v-for="s in perfOptions" :key="s.key" role="tab" :class="{ on: s.key === perfVs }"
                  :aria-selected="s.key === perfVs" :title="stateTitle(s)" @click="setVs(s.key)">
            {{ stateCode(s.key) }}
          </button>
        </div>
      </div>
      <div v-else-if="run?.line_runs" class="sd-lines">
        <div v-if="states" class="sd-seg" role="tablist">
          <button v-for="s in states" :key="s.key" role="tab" :class="{ on: s.key === stateKey }"
                  :aria-selected="s.key === stateKey" :title="`${stateTitle(s)} · ${s.defence_line_label}`"
                  @click="setState(s.key)">
            {{ stateCode(s.key) }}
          </button>
        </div>
        <div v-else class="sd-seg" role="tablist">
          <button v-for="lr in lineTabs" :key="lr.defence_line_key" role="tab"
                  :class="{ on: lineOn(lr), empty: lr.run_id && !lr.has_layers && !(run.has_l2 && lr.defence_line_key === 'line2_current') }"
                  :aria-selected="lineOn(lr)"
                  :disabled="!lr.run_id && !(run.has_l2 && lr.defence_line_key === 'line2_current')"
                  :title="run.has_l2 && lr.defence_line_key === 'line2_current' ? t('sim.l2.tabHint') : lineTitle(lr)"
                  @click="clickLine(lr)">
            {{ t(`sim.detail.lineTab.${lr.defence_line_key}`) }}
          </button>
        </div>
        <button v-if="!l2View && !planView" class="sd-cmp" :class="{ on: compare }" :aria-pressed="compare" @click="setCompare(!compare)">
          <AppIcon name="compare" :size="14" />{{ t('sim.compare.btn') }}
        </button>
      </div>
      <button v-if="run && ['queued'].includes(run.status)" class="sim-btn" @click="cancel">
        {{ t('sim.detail.cancel') }}
      </button>
    </div>

    <div v-if="run?.has_layers && perf" class="sd-grid">
      <ResultMap :key="`${run.id}|perf|${perfVs}`" :run-id="run.id" :state="perfVs" :ponding-state="states[0].key"
                 :pond-class="pondClass" :pond-popup="pondPopup" :pond-legend="pondLegend" :show-residual="false" fit-ponds
                 @hotspots="hotspots = $event" />
      <PerfPanel :data="perfFit" :error="perfErr" :rain="run.rain_label" :hotspots="hotspots" @h="setH" />
    </div>
    <div v-else-if="run?.has_layers" class="sd-grid">
      <ResultMap ref="mapRef" :key="`${run.id}|${stateKey || ''}`" :run-id="run.id" :state="stateKey"
                 :l2-ponds="l2View && !states && l2?.ponds?.length ? l2.ponds : null"
                 :l2-note="planView ? t('sim.l2.mapNotePlan', { s: stateCode(stateKey) }) : l2View ? t(!states ? 'sim.l2.mapNote' : curState?.same_as ? 'sim.l2.mapNoteState' : 'sim.l2.mapNoteReal', { s: stateCode(stateKey) }) : ''"
                 @meta="layerMeta = $event" @ponding="onPonding" @active="pondActive = $event" @now="mapNow = $event" @hotspots="hotspots = $event" />
      <RunCompare v-if="compare && !l2View && !planView" :run="run" :state="stateKey" :meta="layerMeta" :ponding="ponding"
                  @open="openLine" @state="setState" @locate="mapRef?.flyToPoint($event.lat, $event.lon)" />
      <LevelPanel v-else :run="viewRun" :states="states" :state-key="stateKey" :l2-view="l2View" :meta="layerMeta"
                  :ponding="ponding" :active="pondActive" :now="mapNow" :hotspots="hotspots" @focus="mapRef?.focusPond($event)" @perf="openPerf" />
    </div>
    <RunCompare v-else-if="run && compare" class="sd-cmp-solo" :run="run" @open="openLine" />

    <div v-if="run && options" class="wiz-body" style="margin-top: 24px">
      <p v-if="!run.has_layers" class="sim-empty" style="padding-top: 0">{{ t('sim.detail.resultsPending') }}</p>
      <!-- 设计暴雨一律按同一套雨量 / 历时画派生雨型，同雨深历时的任务（如全市 61 mm/2h 与 Mussafah_00）图必须一致 -->
      <RunHyetograph v-if="run.rain_source === 'design_storm' && (!run.has_layers || layerMeta)"
                     :run="run" :is-custom="isCustom" />
      <section class="sim-card wiz-confirm">
        <div class="wiz-kv">
          <span class="k">{{ t('sim.history.cols.basis') }}</span><span class="v">{{ run.defence_basis }}<template v-if="!states && run.variant_label"><span class="sep">｜</span>{{ run.variant_label }}</template></span>
          <span class="k">{{ t('sim.history.cols.start') }}</span><span class="v">{{ fmtWhen(run.started_at) }}</span>
          <span class="k">{{ t('sim.history.cols.end') }}</span>
          <span class="v">{{ fmtWhen(run.ended_at) }}<template v-if="run.ended_at && run.ended_is_estimate">{{ t('sim.history.est') }}</template></span>
          <span class="k">{{ t('sim.history.cols.analyses') }}</span>
          <span class="v">
            <template v-if="run.analyses.length">
              <span v-for="a in run.analyses" :key="a.id" class="sim-tag" :class="a.kind" style="margin-right: 6px">{{ analysisLabel(a) }}</span>
            </template>
            <template v-else>—</template>
          </span>
        </div>

        <div class="wiz-block">
          <div class="bh">{{ t('sim.detail.result') }}</div>
          <div v-if="res" class="wiz-kv">
            <template v-for="[k, v] in metrics" :key="k">
              <span class="k">{{ t(`sim.detail.${k}`) }}</span>
              <span class="v" :class="{ none: v == null }">{{ v == null ? '—' : typeof v === 'string' ? v : fmtInt(v) }}</span>
            </template>
          </div>
          <p v-else class="sim-empty" style="padding: 0">{{ t('sim.detail.noResult') }}</p>
        </div>

        <RunSummary
          :run="run"
          :lines="options.defence_lines"
          :start-utc="run.model_start_utc"
          :is-design-basis="!!isPreset?.is_design_basis"
          :is-custom="isCustom"
        />
      </section>
    </div>
  </SimShell>
</template>

<style scoped>
/* 地图在左、总览在右；窄屏总览落到地图下面 */
.sd-grid { display: grid; grid-template-columns: minmax(0, 1fr) 420px; gap: 20px; align-items: start; }
.sd-grid > .ro { margin-top: 20px; position: sticky; top: 20px; }
.sd-variant { background: var(--blue-bg); color: var(--blue-lt); }
.sd-lines { margin-left: auto; display: flex; align-items: center; gap: 10px; }
.sd-seg { display: flex; gap: 2px; padding: 3px; border-radius: 999px; background: rgba(255, 255, 255, 0.04); }
.sd-seg button { border: 0; background: none; color: var(--fg-2); font: inherit; font-size: 14px; padding: 4px 10px;
  border-radius: 999px; cursor: pointer; white-space: nowrap; }
.sd-seg button:hover:not(:disabled):not(.on) { color: var(--fg); }
.sd-seg button.on { background: var(--blue); color: #fff; font-weight: 600; cursor: default; }
.sd-seg button.empty:not(.on) { color: var(--muted); }
.sd-seg button:disabled { color: var(--faint); cursor: not-allowed; }
.sd-cmp { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 12px; border-radius: 6px;
  border: 1px solid var(--line); background: none; color: var(--fg); font: inherit; font-size: 14px; font-weight: 600;
  cursor: pointer; }
.sd-cmp:hover { background: rgba(255, 255, 255, 0.05); }
.sd-cmp.on { border-color: var(--blue); background: var(--blue-bg); color: var(--blue-lt); }
.sd-crumb { display: flex; align-items: baseline; gap: 10px; }
.sd-crumb button { border: 0; background: none; padding: 0; font: inherit; font-weight: 400; color: var(--fg-2); cursor: pointer; }
.sd-crumb button:hover { color: var(--fg); }
.sd-crumb span { color: var(--faint); font-weight: 400; }
.sd-vs { color: var(--muted); font-size: 13px; }
.sd-cmp-solo { max-width: 560px; margin-top: 20px; }
@media (max-width: 1280px) {
  .sd-grid { grid-template-columns: minmax(0, 1fr); }
  .sd-grid > .ro { position: static; }
}
</style>
