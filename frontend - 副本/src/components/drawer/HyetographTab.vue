<script setup>
/* 雨型图（只读）—— 9 个雨量 × 历时预设 + 自定义场景，选一个就画它的派生雨型。
   只看不算：不写 store、不影响任何批算结果。DDF 表、生成算法、合法性校验都在后端
   （backend/src/stormwater/hyetograph.py，`/api/hyetograph*`），这里只取数出图。
   自定义场景只存本浏览器，不进后端。 */
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { fetchHyetograph, fetchHyetographPresets } from '../../api'
import HyetographChart from '../HyetographChart.vue'
import { locale, t } from '../../i18n'
import { fmt } from '../../utils/format'

const STORAGE_KEY = 'fm.hyetoCustom'

const base = ref(null) // /api/hyetograph/presets
const baseErr = ref('')

const keyOf = s => `${s.P}|${s.D}|${s.step}|${s.peakPct}`
const series = reactive(new Map()) // keyOf → /api/hyetograph 的返回；数字与语言无关，切语言不用重取
const seriesErr = ref('')

const presets = computed(() =>
  base.value
    ? base.value.presets.map(p => ({
        id: `p-${p.depth_mm}-${p.duration_min}`,
        P: p.depth_mm,
        D: p.duration_min,
        step: p.step_min,
        peakPct: p.peak_pct,
        eq: p.equivalent,
      }))
    : [],
)
const presetRows = computed(() => {
  if (!base.value) return []
  const n = base.value.preset_durations_min.length
  return base.value.preset_depths_mm.map((P, i) => ({ P, cells: presets.value.slice(i * n, i * n + n) }))
})
const defaultId = computed(() =>
  base.value ? `p-${base.value.default.depth_mm}-${base.value.default.duration_min}` : null,
)

function loadCustom() {
  try {
    const v = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
    return Array.isArray(v) ? v.filter(s => s && s.id && s.P > 0 && s.D > 0 && s.step > 0) : []
  } catch {
    return [] // 隐私模式或存坏了：当没有自定义场景
  }
}
function saveCustom() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(custom.value))
  } catch {
    // 存不下就只在本次会话生效
  }
}

const custom = ref(loadCustom())
const selId = ref(null)
const sel = computed(
  () =>
    [...presets.value, ...custom.value].find(s => s.id === selId.value) ||
    presets.value.find(s => s.id === defaultId.value) ||
    null,
)

/** 雨量：整数不带小数，否则一位。 */
const mm = P => fmt(P, Number.isInteger(P) ? 0 : 1)
const durLabel = D => (D % 60 === 0 ? t('hyeto.durH', { n: D / 60 }) : t('hyeto.durMin', { n: D }))
const scenarioName = s => s.name || t('hyeto.cellName', { p: mm(s.P), d: durLabel(s.D) })

function eqText(eq) {
  if (eq.kind === 'within') return t('hyeto.eqWithin', { n: fmt(eq.years, eq.years < 10 ? 1 : 0) })
  if (eq.kind === 'above') return t('hyeto.eqAbove', { r: fmt(eq.ratio, 2) })
  return t('hyeto.eqBelow', { r: fmt(eq.ratio, 2) })
}
/** 预设的等效重现期随 presets 一起来；自定义场景的取它那条雨型时顺带拿到。 */
const eqOf = s => s.eq || series.get(keyOf(s))?.equivalent || null

/* ---------------- 取数 ---------------- */

async function loadBase() {
  baseErr.value = ''
  try {
    base.value = await fetchHyetographPresets()
  } catch (e) {
    baseErr.value = e.message
  }
}

async function ensureSeries(s) {
  const k = keyOf(s)
  if (series.has(k)) return series.get(k)
  const d = await fetchHyetograph(s)
  series.set(k, d)
  return d
}

// 选中哪个就取哪条；切得快时只认最后一次
let ticket = 0
watch(
  sel,
  async s => {
    if (!s) return
    const my = ++ticket
    seriesErr.value = ''
    try {
      await ensureSeries(s)
    } catch (e) {
      if (my === ticket) seriesErr.value = e.message
    }
  },
  { immediate: true },
)

// 来源 / 方法 / 证据边界是后端文案，换语言得重取
watch(locale, loadBase)

onMounted(() => {
  loadBase()
  // 自定义场景的徽标要等效重现期 —— 逐个取一次，结果进缓存，点开时不再等
  custom.value.forEach(s => ensureSeries(s).catch(() => {}))
})

/* ---------------- 新建自定义场景 ---------------- */

const formOpen = ref(false)
const form = ref({})
const formErr = ref('')
const saving = ref(false)

function openForm() {
  form.value = { name: '', P: 45, D: 180, step: 5, peakPct: base.value?.default_peak_pct ?? 40 }
  formErr.value = ''
  formOpen.value = true
}

/** 合法性由后端判：先取这条雨型，取得到才存。报错原文（已按语言翻好）直接印出来。 */
async function submitForm() {
  const s = {
    id: `c-${Date.now()}`,
    name: String(form.value.name || '').trim(),
    P: Number(form.value.P),
    D: Number(form.value.D),
    step: Number(form.value.step),
    peakPct: Number(form.value.peakPct),
  }
  saving.value = true
  formErr.value = ''
  try {
    await ensureSeries(s)
  } catch (e) {
    formErr.value = e.message
    return
  } finally {
    saving.value = false
  }
  custom.value.push(s)
  saveCustom()
  selId.value = s.id
  formOpen.value = false
}
function removeCustom(id) {
  custom.value = custom.value.filter(s => s.id !== id)
  saveCustom()
  if (selId.value === id) selId.value = null
}

/* ---------------- 图 ---------------- */

const H = computed(() => (sel.value ? series.get(keyOf(sel.value)) || null : null))
</script>

<template>
  <div>
    <div class="note" style="margin-bottom: 12px" v-html="t('hyeto.intro')" />

    <div v-if="baseErr" class="note warn">{{ t('hyeto.loadError', { msg: baseErr }) }}</div>
    <div v-else-if="!base"><div class="skel" /><div class="skel" /><div class="skel" /></div>

    <template v-else>
      <div class="hy-grid">
        <div />
        <div v-for="D in base.preset_durations_min" :key="D" class="hy-hd">{{ durLabel(D) }}</div>
        <template v-for="row in presetRows" :key="row.P">
          <div class="hy-rl">{{ t('hyeto.mm', { n: mm(row.P) }) }}</div>
          <div
            v-for="s in row.cells"
            :key="s.id"
            class="hy-cell"
            :class="{ on: sel && s.id === sel.id }"
            @click="selId = s.id"
          >
            <b>{{ scenarioName(s) }}</b>
            <span class="tag" :class="s.eq.kind === 'within' ? 'n' : 'w'">{{ eqText(s.eq) }}</span>
          </div>
        </template>
      </div>

      <div class="hy-custom">
        <div class="hy-rl">{{ t('hyeto.customRow') }}</div>
        <div
          v-for="s in custom"
          :key="s.id"
          class="hy-cell"
          :class="{ on: sel && s.id === sel.id }"
          @click="selId = s.id"
        >
          <b>
            {{ scenarioName(s) }}
            <span class="hy-x" :title="t('hyeto.delete')" @click.stop="removeCustom(s.id)">×</span>
          </b>
          <span class="note">{{ mm(s.P) }} mm / {{ durLabel(s.D) }} · {{ s.step }} min · {{ s.peakPct }}%</span>
          <span v-if="eqOf(s)" class="tag" :class="eqOf(s).kind === 'within' ? 'n' : 'w'">{{
            eqText(eqOf(s))
          }}</span>
        </div>
        <button v-if="!formOpen" class="ghost hy-add" @click="openForm">+ {{ t('hyeto.addCustom') }}</button>
      </div>

      <div v-if="formOpen" class="hy-form">
        <label
          >{{ t('hyeto.fName') }}<input v-model="form.name" type="text" :placeholder="t('hyeto.fNamePh')"
        /></label>
        <label>{{ t('hyeto.fP') }}<input v-model="form.P" type="number" min="1" step="1" @input="formErr = ''" /></label>
        <label>{{ t('hyeto.fD') }}<input v-model="form.D" type="number" min="15" step="5" @input="formErr = ''" /></label>
        <label
          >{{ t('hyeto.fStep') }}
          <select v-model="form.step" @change="formErr = ''">
            <option v-for="s in base.step_choices_min" :key="s" :value="s">{{ s }}</option>
          </select>
        </label>
        <label
          >{{ t('hyeto.fPeak', { n: form.peakPct }) }}
          <input v-model="form.peakPct" type="range" min="0" max="100" step="5" />
        </label>
        <div class="hy-form-act">
          <button class="ghost" :disabled="saving" @click="submitForm">{{ t('hyeto.save') }}</button>
          <button class="ghost" @click="formOpen = false">{{ t('hyeto.cancel') }}</button>
          <span v-if="formErr" class="warn">{{ formErr }}</span>
        </div>
      </div>

      <div v-if="seriesErr" class="note warn" style="margin-top: 16px">
        {{ t('hyeto.loadError', { msg: seriesErr }) }}
      </div>
      <div v-else-if="!H" style="margin-top: 16px">
        <div class="skel" /><div class="skel" style="width: 70%" />
        <div class="note">{{ t('hyeto.loading') }}</div>
      </div>

      <HyetographChart v-else :h="H" :title="scenarioName(sel)" />

      <div class="note warn" style="margin-top: 10px">{{ base.boundary }}</div>
      <div class="note" style="margin-top: 4px">{{ base.method }} · {{ base.source }}</div>
    </template>
  </div>
</template>
