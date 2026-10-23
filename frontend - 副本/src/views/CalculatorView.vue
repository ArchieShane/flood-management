<script setup>
/* 单点快算：推理公式法筛查工具，按积水点 × 重现期测算所需调蓄容量与应急车队规模。
   与指挥中心共用后端，但不读台账 —— 七个参数全部手填，用于导则口径的对照与试算。 */
import { computed, onMounted, ref, watch } from 'vue'

import { calcHotspot, compareDatasets, fetchIdfDatasets } from '../api'
import { useBodyTheme } from '../composables/useBodyTheme'
import { LOCALES, locale, setLocale, t } from '../i18n'
import '../styles/calculator.css'

useBodyTheme('theme-calc')

const meta = ref(null)
const current = ref(null)
const error = ref('')

const form = ref({
  hotspot_id: 'H1',
  area_ha: 12,
  runoff_c: 0.75,
  tc_min: 20,
  qcap_m3s: 1.8,
  pond_available_m3: 0,
  priority: '',
})

const calcResult = ref(null)
const compareResult = ref(null)

const f = (v, d = 2) => (v === null || v === undefined ? '—' : Number(v).toFixed(d))

const payload = () => ({
  dataset: current.value.key,
  hotspot: {
    hotspot_id: form.value.hotspot_id || 'H1',
    area_ha: +form.value.area_ha,
    runoff_c: +form.value.runoff_c,
    tc_min: +form.value.tc_min,
    qcap_m3s: +form.value.qcap_m3s,
    pond_available_m3: +form.value.pond_available_m3,
    priority: form.value.priority ? +form.value.priority : null,
  },
})

function select(key) {
  current.value = meta.value.datasets.find(d => d.key === key)
  // 迪拜没有 Table 3-3，优先级选择器置灰而不是消失 —— 让差异可见
  if (calcResult.value) run()
}

async function run() {
  error.value = ''
  try {
    const d = await calcHotspot(payload())
    calcResult.value = d
    compareResult.value = null
  } catch (e) {
    error.value = e.message
  }
}

async function compare() {
  error.value = ''
  try {
    const p = payload()
    const keys = [p.dataset, ...meta.value.datasets.map(d => d.key).filter(k => k !== p.dataset)]
    const d = await compareDatasets({ hotspot: p.hotspot, datasets: keys })
    d._keys = keys
    compareResult.value = d
    calcResult.value = null
  } catch (e) {
    error.value = e.message
  }
}

/** 对照面板里每套数据集的「所需调蓄合计」相对基准的百分比。 */
const compareRows = computed(() => {
  const d = compareResult.value
  if (!d) return []
  const base = d.results[d._keys[0]]
  const baseStorage = base.reduce((a, s) => a + s.required_storage_m3, 0)
  return d.datasets.map(ds => {
    const rs = d.results[ds.key]
    const tot = rs.reduce((a, s) => a + s.required_storage_m3, 0)
    return {
      ds,
      rows: rs,
      delta:
        ds.key === d._keys[0] || !baseStorage
          ? ''
          : t('calcview.cmpDelta', {
              sign: tot >= baseStorage ? '+' : '',
              pc: f(100 * (tot / baseStorage - 1), 0),
            }),
    }
  })
})

async function loadMeta() {
  try {
    const keep = current.value && current.value.key
    meta.value = await fetchIdfDatasets()
    select(keep || meta.value.default)
  } catch (e) {
    error.value = e.message
  }
}

onMounted(loadMeta)

// datasets[].label / source / notes、priorities[].label 都是后端文案 —— 换语言重取；
// 算过的结果也得跟着换，否则一屏英文里留着一段中文口径说明
watch(locale, async () => {
  document.title = t('app.calculator')
  await loadMeta()
  if (calcResult.value) await run()
  else if (compareResult.value) await compare()
})
</script>

<template>
  <div class="wrap">
    <div class="head">
      <div>
        <h1>{{ t('calcview.title') }}</h1>
        <p class="sub">{{ t('calcview.sub') }}</p>
      </div>
      <!-- 这一页没有顶栏，语言开关只能自己带一个；否则直接进 /calculator 就切不了 -->
      <div class="lang" role="group" :aria-label="t('menu.language')">
        <button
          v-for="l in LOCALES"
          :key="l.key"
          type="button"
          :aria-pressed="String(locale === l.key)"
          @click="setLocale(l.key)"
        >
          {{ l.label }}
        </button>
      </div>
    </div>

    <!-- ========== 数据集切换 ========== -->
    <section v-if="meta" class="panel">
      <h2>{{ t('calcview.datasetHeading') }}</h2>
      <div class="switch" role="group" :aria-label="t('calcview.datasetAria')">
        <button
          v-for="d in meta.datasets"
          :key="d.key"
          type="button"
          :aria-pressed="String(current && current.key === d.key)"
          @click="select(d.key)"
        >
          <span class="nm">{{ d.label }}</span>
          <span class="src">{{ d.source }}</span>
        </button>
      </div>
      <div v-if="current && current.notes.length" class="notes">
        <ul><li v-for="(n, i) in current.notes" :key="i">{{ n }}</li></ul>
      </div>
      <div v-if="current" class="meta">
        <span class="tag">{{
          t('calcview.availableRps', { list: current.return_periods.join(' / ') })
        }}</span>
        <span class="tag">{{ t(current.supports_cf ? 'calcview.cfYes' : 'calcview.cfNo') }}</span>
        <span class="tag">{{ t(current.supports_tc_multiplier ? 'calcview.tcYes' : 'calcview.tcNo') }}</span>
      </div>
    </section>

    <!-- ========== 输入 ========== -->
    <section class="panel">
      <h2>{{ t('calcview.inputHeading') }}</h2>
      <div class="grid">
        <div>
          <label for="hotspot_id">{{ t('calcview.fieldId') }}</label>
          <input id="hotspot_id" v-model="form.hotspot_id" />
        </div>
        <div>
          <label for="area_ha">{{ t('calcview.fieldArea') }}</label>
          <input id="area_ha" v-model.number="form.area_ha" type="number" step="0.1" min="0.1" />
        </div>
        <div>
          <label for="runoff_c">{{ t('calcview.fieldC') }}</label>
          <input id="runoff_c" v-model.number="form.runoff_c" type="number" step="0.01" min="0.01" max="1" />
          <div class="hint">{{ t('calcview.fieldCHint') }}</div>
        </div>
        <div>
          <label for="tc_min">{{ t('calcview.fieldTc') }}</label>
          <input id="tc_min" v-model.number="form.tc_min" type="number" step="1" min="1" />
        </div>
        <div>
          <label for="qcap_m3s">{{ t('calcview.fieldQcap') }}</label>
          <input id="qcap_m3s" v-model.number="form.qcap_m3s" type="number" step="0.1" min="0" />
        </div>
        <div>
          <label for="pond">{{ t('calcview.fieldPond') }}</label>
          <input id="pond" v-model.number="form.pond_available_m3" type="number" step="10" min="0" />
        </div>
        <div>
          <label for="priority">{{ t('calcview.fieldPriority') }}</label>
          <select id="priority" v-model="form.priority" :disabled="!current || !current.supports_tc_multiplier">
            <option value="">{{ t('calcview.priorityNone') }}</option>
            <option v-for="p in (meta ? meta.priorities : [])" :key="p.value" :value="p.value">
              {{ p.label }}
            </option>
          </select>
          <div class="hint">
            {{
              t(
                current && current.supports_tc_multiplier
                  ? 'calcview.priorityHintYes'
                  : 'calcview.priorityHintNo',
              )
            }}
          </div>
        </div>
      </div>

      <div class="actions">
        <button class="btn" :disabled="!current" @click="run">{{ t('calcview.run') }}</button>
        <button class="btn ghost" :disabled="!current" @click="compare">{{ t('calcview.compare') }}</button>
        <span class="err">{{ error }}</span>
      </div>
    </section>

    <!-- ========== 结果 ========== -->
    <section v-if="calcResult" class="panel">
      <h2>{{ t('calcview.resultHeading', { label: calcResult.dataset.label }) }}</h2>
      <!-- 口径说明必须在表格之前：这一页的数字与指挥中心的三道防线不是一回事，
           不标出来会被当成同一套数拿去比 -->
      <div class="notes" v-html="t('calcview.basisNote')" />
      <div v-if="calcResult.warnings.length" class="notes">
        <ul><li v-for="(w, i) in calcResult.warnings" :key="i">{{ w }}</li></ul>
      </div>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>{{ t('calcview.thRp') }}</th><th>{{ t('calcview.thDuration') }}</th>
              <th>{{ t('calcview.thM') }}</th><th>{{ t('calcview.thI') }}</th>
              <th>{{ t('calcview.thCadj') }}</th><th>{{ t('calcview.thQ') }}</th>
              <th>{{ t('calcview.thExcess') }}</th><th>{{ t('calcview.thStorage') }}</th>
              <th>{{ t('calcview.thShortfall') }}</th><th>{{ t('calcview.thPumps') }}</th>
              <th>{{ t('calcview.thTankers') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in calcResult.scenarios" :key="s.return_period_yr">
              <td>{{ t('calcview.rpYears', { n: s.return_period_yr }) }}</td>
              <td>{{ f(s.duration_min, 1) }}</td>
              <td>{{ f(s.tc_multiplier, 0) }}×</td>
              <td>{{ f(s.intensity_mm_hr) }}</td>
              <td>{{ f(s.c_adjusted, 4) }}</td>
              <td>{{ f(s.peak_flow_m3s, 3) }}</td>
              <td :class="s.excess_flow_m3s > 0 ? 'over' : 'safe'">{{ f(s.excess_flow_m3s, 3) }}</td>
              <td>{{ f(s.required_storage_m3, 1) }}</td>
              <td :class="s.shortfall_m3 > 0 ? 'over' : 'safe'">{{ f(s.shortfall_m3, 1) }}</td>
              <td>{{ s.pumps_required }}</td>
              <td>{{ s.tanker_loads }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <footer>
        <strong>{{ t('calcview.limitations') }}</strong>
        <ul><li v-for="(l, i) in calcResult.limitations" :key="i">{{ l }}</li></ul>
      </footer>
    </section>

    <!-- ========== 对照 ========== -->
    <section v-if="compareResult" class="panel">
      <h2>{{ t('calcview.compareHeading') }}</h2>
      <div v-for="item in compareRows" :key="item.ds.key">
        <div class="cmp-head">
          <strong>{{ item.ds.label }}</strong>
          <span class="delta"
            >{{ t(item.ds.supports_cf ? 'calcview.cmpCf' : 'calcview.cmpNoCf') }} ·
            {{ t(item.ds.supports_tc_multiplier ? 'calcview.cmpTc' : 'calcview.cmpNoTc') }}</span
          >
          <span v-if="item.delta" class="delta">{{ item.delta }}</span>
        </div>
        <div class="scroll">
          <table>
            <thead>
              <tr>
                <th>{{ t('calcview.thRp') }}</th><th>{{ t('calcview.thDuration') }}</th>
                <th>{{ t('calcview.thM') }}</th><th>{{ t('calcview.thI') }}</th>
                <th>{{ t('calcview.thCadj') }}</th><th>{{ t('calcview.thQ') }}</th>
                <th>{{ t('calcview.thExcess') }}</th><th>{{ t('calcview.thStorage') }}</th>
                <th>{{ t('calcview.thShortfall') }}</th><th>{{ t('calcview.thPumps') }}</th>
                <th>{{ t('calcview.thTankers') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in item.rows" :key="s.return_period_yr">
                <td>{{ t('calcview.rpYears', { n: s.return_period_yr }) }}</td>
                <td>{{ f(s.duration_min, 1) }}</td>
                <td>{{ f(s.tc_multiplier, 0) }}×</td>
                <td>{{ f(s.intensity_mm_hr) }}</td>
                <td>{{ f(s.c_adjusted, 4) }}</td>
                <td>{{ f(s.peak_flow_m3s, 3) }}</td>
                <td :class="s.excess_flow_m3s > 0 ? 'over' : 'safe'">{{ f(s.excess_flow_m3s, 3) }}</td>
                <td>{{ f(s.required_storage_m3, 1) }}</td>
                <td :class="s.shortfall_m3 > 0 ? 'over' : 'safe'">{{ f(s.shortfall_m3, 1) }}</td>
                <td>{{ s.pumps_required }}</td>
                <td>{{ s.tanker_loads }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="meta" style="margin-bottom: 22px">{{ item.ds.source }}</p>
      </div>
    </section>
  </div>
</template>
