<script setup>
import { computed } from 'vue'

import { MECHANISM_COLOR, QUICK_DISTRICT } from '../../constants'
import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'
import { causeLabel, critLabel, fmt, muniLabel } from '../../utils/format'

const S = useScenarioStore()

/* 台账那三组筛选（市政区 / 严重度 / 成因）对模型片区全是「未填写」——
   片区是演算结论，没有行政字段。那一路改用它自己的分类：四类成因。 */
const isModel = computed(() => S.source === 'model')

const GROUPS = computed(() =>
  isModel.value
    ? []
    : [
        { field: 'municipality', title: t('filters.municipality'), label: muniLabel },
        { field: 'criticality', title: t('filters.criticality'), label: critLabel },
        { field: 'root_cause', title: t('filters.rootCause'), label: causeLabel },
      ],
)

const quick = computed(() => S.districtRow(QUICK_DISTRICT))
const quickOn = computed(() => S.filters.district[0] === QUICK_DISTRICT)
const anyFilter = computed(
  () =>
    S.filters.municipality.length ||
    S.filters.criticality.length ||
    S.filters.root_cause.length ||
    S.filters.district.length ||
    S.modelMech.length,
)

/** 选中片区后那行小字 —— 说清这个区能不能算、算的是多少个点。 */
const districtNote = computed(() => {
  const row = S.districtRow(QUICK_DISTRICT)
  if (!row) return ''
  const dup = (S.meta && S.meta.district && S.meta.district.ambiguous_names) || []
  const warn = dup.includes(row.label)
    ? t('filters.dupWarn', { name: row.label, muni: muniLabel(row.municipality) })
    : ''
  const scope =
    row.in_coverage === row.count
      ? t('filters.scopeAll', { n: row.count })
      : row.in_coverage === 0
        ? t('filters.scopeNone', { n: row.count })
        : t('filters.scopeSome', {
            n: row.count,
            inCov: row.in_coverage,
            out: row.count - row.in_coverage,
          })
  // 英文两句之间要有空格，中文不用 —— 只在真的有警示时才加
  return warn ? `${warn} ${scope}` : scope
})

/** 这个片区跑过二维演算时，说清按钮替人改掉的重现期 —— 别让它悄悄地变。
 *  共用时限 T 不在替人改之列：它默认锁在 2 h，实测积水时长只作参照写出来。 */
const pondNote = computed(() => {
  const pond = S.ponding
  if (!pond) return ''
  return t('filters.pondingNote', {
    rp: pond.return_period_yr,
    window: S.pondingWindowLabel,
    n: pond.wet_points,
    total: fmt(pond.net_inflow_m3),
  })
})
</script>

<template>
  <div>
    <h3>{{ t('filters.heading') }}</h3>

    <!-- 片区：只做阿布扎比岛上的 AL BATEEN 一个固定按钮，再按一次取消。
         没跑过 district_batch.py 就整块藏掉，不摆一个按不动的按钮。 -->
    <div v-if="quick && !isModel" style="margin-bottom: 8px">
      <div class="note" style="margin-bottom: 5px">
        {{ t('filters.districtLabel') }}
        <span style="opacity: 0.6">{{ t('filters.districtNote') }}</span>
      </div>
      <button
        class="ghost"
        style="width: 100%; text-align: left"
        :style="quickOn ? { background: 'rgba(71,134,201,.28)', color: '#fff' } : null"
        @click="S.toggleQuickDistrict()"
      >
        {{ quickOn ? '✓ ' : ''
        }}{{ t('filters.onlyDistrict', { name: quick.label, muni: muniLabel(quick.municipality) }) }}
        <span style="opacity: 0.7; font-weight: 400">{{ t('filters.nPoints', { n: quick.count }) }}</span>
      </button>
      <div v-if="quickOn" class="note" style="margin-top: 5px" v-html="districtNote" />
      <div
        v-if="quickOn && pondNote"
        class="note"
        style="margin-top: 5px; border-left: 2px solid var(--blue); padding-left: 8px"
        v-html="pondNote"
      />
    </div>

    <!-- 模型片区：按二维演算判出的四类成因筛，按处置优先级排 -->
    <div v-if="isModel" style="margin-bottom: 8px">
      <div class="note" style="margin-bottom: 5px">{{ t('model.mechHeading') }}</div>
      <div class="chips">
        <span
          v-for="m in S.modelMechRows"
          :key="m.key"
          class="chipb"
          :class="{ on: S.modelMech.includes(m.key) }"
          @click="S.toggleMech(m.key)"
        >
          <i
            style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px"
            :style="{ background: MECHANISM_COLOR[m.key] }"
          />{{ m.label }} <span style="opacity: 0.6">{{ m.n }}</span>
        </span>
      </div>
      <div class="note" style="margin-top: 5px">
        {{ S.modelMech.length ? t('model.mechFiltered', { n: S.filtered.length }) : t('model.mechAll') }}
      </div>
    </div>

    <div v-for="g in GROUPS" :key="g.field" style="margin-bottom: 8px">
      <div class="note" style="margin-bottom: 5px">{{ g.title }}</div>
      <div class="chips">
        <span
          v-for="x in (S.meta ? S.meta.facets[g.field] : [])"
          :key="x.value"
          class="chipb"
          :class="{ on: S.filters[g.field].includes(x.value) }"
          @click="S.toggleFilter(g.field, x.value)"
        >
          {{ g.label(x.value) }} <span style="opacity: 0.6">{{ x.count }}</span>
        </span>
      </div>
    </div>

    <div class="note">
      {{ S.mode === 'point' ? t('filters.notePoint') : t('filters.noteBatch') }}
      <span v-if="anyFilter" class="tag b" style="cursor: pointer" @click="S.clearFilters()">{{
        t('filters.clear')
      }}</span>
    </div>
  </div>
</template>
