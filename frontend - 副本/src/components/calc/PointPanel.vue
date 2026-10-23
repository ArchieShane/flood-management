<script setup>
/* 单点 · 多情景（默认交互）
   点地图上任一积水点 → 选一级重现期 → 看清那一级默认落多少雨、落多久 → 按「计算」。
   逐行走的是全域批算同一条计算链，故同一行数字与批算逐字段相等。 */
import { computed } from 'vue'

import AppIcon from '../AppIcon.vue'
import CurveBars from './CurveBars.vue'
import CurveTable from './CurveTable.vue'
import DetailBlock from './DetailBlock.vue'
import FilterChips from './FilterChips.vue'
import InputsBlock from './InputsBlock.vue'
import ClusterBlock from '../model/ClusterBlock.vue'
import ModelRunBlock from '../model/ModelRunBlock.vue'
import ModePills from './ModePills.vue'
import PointHeader from './PointHeader.vue'
import StormChooser from './StormChooser.vue'
import { RPS } from '../../constants'
import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'
import { useToastStore } from '../../stores/toast'
import { fmt } from '../../utils/format'
import { exportPointCsv } from '../../utils/csv'

const S = useScenarioStore()
const toast = useToastStore()

const p = computed(() => (S.sel ? S.byUid.get(S.sel) : null))
const rows = computed(() => (S.curve && S.curve.point.uid === S.sel ? S.curve.scenarios : []))
const r = computed(() => (rows.value.length ? S.currentRow : null))
//『算过的那一行』优先；还没算就用默认参数那一份 —— 两者字段同名同义
const src = computed(() => r.value || S.preset)

const worst = computed(() => rows.value[rows.value.length - 1])
const allDone = computed(() => RPS.every(x => rows.value.some(y => y.return_period_yr === x)))
const missing = computed(() => RPS.filter(x => !rows.value.some(y => y.return_period_yr === x)))

const rpLabel = computed(() =>
  r.value
    ? r.value.return_period_yr
      ? t('point.rpOnceIn', { n: r.value.return_period_yr })
      : t('toast.pointRpCustom', { p: S.custom.P, d: S.custom.D })
    : '',
)
const rpShort = row =>
  row.return_period_yr ? t('point.rpShortYears', { n: row.return_period_yr }) : t('point.rpShortCustom')

const ledgerPumps = computed(() => (p.value && p.value.pumps_qty) || 0)
const gapNote = computed(() =>
  r.value && r.value.pumps_required > ledgerPumps.value
    ? t('point.gapOver', { n: fmt(r.value.pumps_required - ledgerPumps.value) })
    : t('point.gapOk'),
)
const gapOver = computed(() => !!(r.value && r.value.pumps_required > ledgerPumps.value))

const tierRows = computed(() => Object.entries((r.value && r.value.pumps_by_tier) || {}))
const tierLabel = k => ((r.value.pump_tiers || []).find(x => x.key === k) || { label: k }).label

function onExport() {
  const done = exportPointCsv(S)
  if (done)
    toast.show(
      t('point.exported', { uid: done.uid, n: done.count, lang: t('csv.lang'), v: S.inputs.v }),
    )
}
</script>

<template>
  <aside class="panel">
    <div style="display: flex; justify-content: space-between; align-items: center">
      <h2>{{ t('point.title') }}</h2>
      <span style="cursor: pointer" @click="S.panel = false"
        ><AppIcon name="close" :size="16" :opacity="0.55"
      /></span>
    </div>
    <ModePills />

    <!-- 第一步：选点。没选点就不谈雨 —— 历时与强度都跟着这个点的 tc 走。 -->
    <div v-if="!S.sel" class="content">
      <div class="empty">
        <AppIcon name="locate" :size="24" :opacity="0.55" />
        <b>{{ t('point.step1Title') }}</b>
        <div class="note">
          <span v-html="t('point.step1Note')" />
          {{ S.meta ? t('point.step1Count', { n: S.filtered.length }) : t('point.step1Loading') }}
        </div>
      </div>
      <FilterChips />
      <ModelRunBlock />
      <InputsBlock />
    </div>

    <div v-else class="content">
      <!-- 第二步与第三步：口径 + 选重现期 + 只读的默认降雨参数 + 计算按钮 -->
      <PointHeader v-if="src" :point="p" :row="src" />
      <div v-else>
        <h3>{{ p.uid }} · {{ p.location }}</h3>
        <div class="skel" /><div class="skel" /><div class="skel" style="width: 60%" />
        <div class="note">{{ t('point.loadingInputs') }}</div>
      </div>

      <div><h3>{{ t('point.step2') }}</h3><StormChooser /></div>

      <!-- 选中的这一级还没算：只摆输入，一个结论都不摆 -->
      <template v-if="!r">
        <div v-if="rows.length">
          <h3>{{ t('point.computedHeading') }}</h3>
          <CurveTable :rows="rows" />
          <div class="note" style="margin-top: 6px">
            {{
              t('point.pickRowNote', {
                what: S.useCustom
                  ? t('point.thisCustomStorm')
                  : t('point.rpOnceIn', { n: S.curveRp }),
              })
            }}
          </div>
        </div>
        <div class="empty">
          <AppIcon name="calc" :size="24" :opacity="0.55" />
          <b>{{ S.curveLoading ? t('point.calculating') : t('point.step3') }}</b>
          <div class="note">
            {{ S.curveLoading ? t('point.step3Loading', { v: S.inputs.v }) : t('point.step3Note') }}
          </div>
        </div>
        <ClusterBlock />
        <ModelRunBlock />
        <InputsBlock />
        <FilterChips />
      </template>

      <template v-else>
        <div>
          <h3>{{ t('point.dispatchHeading', { rp: rpLabel }) }}</h3>
          <div class="stat" style="grid-template-columns: 1fr 1fr 1fr">
            <div>
              <div class="v">{{ fmt(r.pumps_required) }}</div>
              <div class="l">{{ t('point.unitPumps') }}</div>
            </div>
            <div>
              <div class="v">{{ fmt(r.tanker_loads) }}</div>
              <div class="l">{{ t('point.unitTankers') }}</div>
            </div>
            <div>
              <div class="v" :style="{ color: r.shortfall_m3 ? 'var(--amber)' : 'var(--green)' }">
                {{ fmt(r.shortfall_m3) }}
              </div>
              <div class="l">{{ t('point.unitShortfall') }}</div>
            </div>
          </div>
          <div class="rows" style="margin-top: 8px">
            <template v-if="tierRows.length">
              <div v-for="[k, v] in tierRows" :key="k" class="row">
                <span class="l">· {{ tierLabel(k) }}</span
                ><b>{{ t('batch.pumpsUnit', { n: fmt(v) }) }}</b>
              </div>
            </template>
            <div v-else class="row">
              <span class="l">{{ t('point.rowTier') }}</span><b>{{ t('point.noDispatch') }}</b>
            </div>
            <div class="row">
              <span class="l">{{ t('point.rowDeployed') }}</span>
              <b
                >{{ fmt(r.pump_deployed_m3hr) }} m³/h
                <span class="l">{{
                  t('point.deployedNeed', { v: fmt(r.pumping_rate_m3hr) })
                }}</span></b
              >
            </div>
            <div class="row">
              <span class="l">{{ t('point.rowLedgerCompare') }}</span>
              <b :style="gapOver ? { color: 'var(--red)' } : null">{{ gapNote }}</b>
            </div>
          </div>
          <div class="note" style="margin-top: 6px">
            {{
              t('point.ranAt', {
                ts: S.curve.ranAt,
                v: S.inputs.v,
                over: S.overCount ? t('point.overSuffix') : '',
              })
            }}
            <span class="src">{{ t('point.screeningBasis') }}</span>
          </div>
        </div>

        <DetailBlock :res="r" />

        <!-- 选中的是模型识别片区：补上它独有的二维演算指标与汇水区边界出处 -->
        <ClusterBlock />

        <div>
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px">
            <h3 style="margin: 0">
              {{ allDone ? t('point.allRpHeading') : t('point.someRpHeading') }}
            </h3>
            <span class="tag" :class="S.holdSummary.cls">{{ S.holdSummary.tag }}</span>
          </div>
          <CurveTable :rows="rows" />
          <div v-if="S.curve.skipped.length" class="note warn" style="margin-top: 6px">
            {{ S.curve.skipped.map(x => x.reason).join('; ') }}
          </div>
          <div class="note" style="margin-top: 8px">
            {{ S.holdSummary.text }}{{ t('point.tailPick')
            }}<template v-if="!allDone">{{
              t('point.tailMissing', { list: missing.join(' / ') })
            }}</template
            >{{ t('point.tailStop') }}<template v-if="rows.length > 1">{{
              t('point.tailWorst', {
                rp: rpShort(worst),
                brief: S.pumpBrief(worst),
                loads: fmt(worst.tanker_loads),
              })
            }}</template>
          </div>
        </div>

        <div v-if="rows.length > 1">
          <h3>{{ t('point.barsHeading') }}</h3>
          <CurveBars :rows="rows" />
          <div class="note" style="display: flex; gap: 12px; flex-wrap: wrap; margin-top: 2px">
            <span
              ><i class="ic" style="width: 8px; height: 8px; background: var(--blue); border-radius: 50%" />
              {{ t('point.barsL1', { h: r.window_hours }) }}</span
            >
            <span
              ><i class="ic" style="width: 8px; height: 8px; background: var(--green); border-radius: 50%" />
              {{ t('point.barsL2') }}</span
            >
            <span
              ><i class="ic" style="width: 8px; height: 8px; background: var(--amber); border-radius: 50%" />
              {{ t('point.barsL3') }}</span
            >
          </div>
        </div>

        <ModelRunBlock />
        <InputsBlock />
        <FilterChips />
      </template>
    </div>

    <div class="bottom">
      <button class="ghost" :disabled="!S.curve" @click="onExport">
        <AppIcon name="exp" :size="16" /> {{ t('point.exportCsv') }}
      </button>
      <button class="ghost" @click="S.openDrawer()">
        <AppIcon name="lock" :size="16" /> {{ t('point.modelInputs', { v: S.inputs.v }) }}
      </button>
    </div>
  </aside>
</template>
