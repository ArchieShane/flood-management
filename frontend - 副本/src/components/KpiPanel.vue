<script setup>
import { computed } from 'vue'

import { datasetLabel } from '../constants'
import { t } from '../i18n'
import { useScenarioStore } from '../stores/scenario'
import { fmt } from '../utils/format'
import { pumpTierSuffix } from '../utils/pumps'

const S = useScenarioStore()

/* ---- 全域批算 ---- */
const s = computed(() => (S.result ? S.result.summary : null))
const gap = computed(() => (S.result ? S.result.fleet_gap : null))
const dsLabel = computed(() =>
  S.useCustom ? t('dataset.noCf') : S.dataset === 'auto' ? t('dataset.autoLong') : datasetLabel(S.dataset),
)
const scopedCount = computed(() => S.filtered.filter(S.inScope).length)

/* ---- 单点模式 ---- */
const point = computed(() => (S.sel ? S.byUid.get(S.sel) : null))
const row = computed(() => (S.curve ? S.currentRow : null))
const rpLabel = computed(() =>
  row.value
    ? row.value.return_period_yr
      ? t('point.rpOnceIn', { n: row.value.return_period_yr })
      : t('toast.pointRpCustom', { p: S.custom.P, d: S.custom.D })
    : t('kpi.currentRp'),
)
/** 罐车一句话：「4 辆 · 34 车次」。单点与全域同一个写法 —— 两边字段同名。
 *
 *  ⚠ 每辆跑不满一趟时辆数是 null（单点）或 0 + `points_tanker_infeasible`（全域），
 *  两种都印「车次 · 超时限」而**不印 0 辆** —— 0 会读成「不需要罐车」。 */
const tankerBrief = row => {
  if (!row.tanker_loads) return t('kpi.noTankers')
  const blocked = row.tankers_required === null || row.points_tanker_infeasible > 0
  return blocked
    ? t('kpi.tankersBlocked', { loads: fmt(row.tanker_loads) })
    : t('kpi.tankersFmt', { n: fmt(row.tankers_required), loads: fmt(row.tanker_loads) })
}

const ledgerPumps = computed(() => (point.value && point.value.pumps_qty) || 0)

</script>

<template>
  <!-- 单点模式：把「这个点撑到第几级」摆在最显眼处 -->
  <div v-if="S.mode === 'point'" class="kpi">
    <div class="k">
      <div>
        <div class="h">{{ point ? point.uid : t('kpi.noPoint') }}</div>
        <div class="l">{{ point ? point.location : t('kpi.pickOnMap') }}</div>
      </div>
      <div>
        <div class="v">{{ S.curve ? fmt(S.curve.scenarios.length) : '—' }}</div>
        <div class="u">
          {{ S.curve ? (S.useCustom ? t('kpi.computedCustom') : t('kpi.computedRps')) : t('kpi.pending') }}
        </div>
      </div>
    </div>

    <div class="k">
      <div>
        <div class="h">{{ S.useCustom ? t('kpi.thisCustomStorm') : t('kpi.holdsUpTo') }}</div>
        <div class="l">{{ S.curve ? S.holdSummary.note : t('kpi.computeAfterPick') }}</div>
      </div>
      <div>
        <div class="v" :style="{ color: S.holdSummary.cls === 's' ? 'var(--green)' : 'var(--amber)' }">
          {{ S.curve ? S.holdSummary.short : '—' }}
        </div>
        <div class="u">{{ S.useCustom ? '' : t('kpi.onceIn') }}</div>
      </div>
    </div>

    <div class="k">
      <div>
        <div class="h">{{ rpLabel }}</div>
        <div class="l">
          {{
            row
              ? t('kpi.shortfallIn', { h: S.asm.drawdown_hours, v: fmt(row.shortfall_m3) })
              : t('kpi.pendingCalc')
          }}
        </div>
      </div>
      <div>
        <div class="v">{{ row ? fmt(row.pumps_required) : '—' }}</div>
        <div class="u">
          {{ row ? t('kpi.pumpsUnit') + pumpTierSuffix(row) + ' · ' + tankerBrief(row) : t('kpi.pendingCalc') }}
        </div>
      </div>
    </div>

    <div class="k">
      <div>
        <div class="h">{{ t('kpi.ledgerCompare') }}</div>
        <div class="l">{{ t('kpi.modelVsPointLedger') }}</div>
      </div>
      <div>
        <div
          class="v"
          :style="{ color: row && row.pumps_required > ledgerPumps ? 'var(--red)' : 'var(--green)' }"
        >
          {{ row ? (row.pumps_required > ledgerPumps ? '+' + fmt(row.pumps_required - ledgerPumps) : '0') : '—' }}
        </div>
        <div class="u">
          {{
            row
              ? fmt(row.pumps_required) + t('kpi.onLedger') + fmt(ledgerPumps)
              : t('kpi.pendingCalc')
          }}
        </div>
      </div>
    </div>
  </div>

  <!-- 全域批算 -->
  <div v-else class="kpi">
    <div class="k">
      <div>
        <div class="h">{{ t('kpi.scenario') }}</div>
        <div class="l">{{ S.stormLabel }} · {{ dsLabel }}</div>
      </div>
      <div>
        <div class="v">{{ scopedCount }}</div>
        <div class="u">{{ S.inputs.coverageOnly ? t('kpi.scopedComputed') : t('kpi.scopedAll') }}</div>
      </div>
    </div>

    <div class="k">
      <div>
        <div class="h">{{ t('kpi.line1Title') }}</div>
        <div class="l">{{ t('kpi.line1Sub', { h: S.asm.drawdown_hours }) }}</div>
        <!-- 分母不是全网，是有标定的那批点 —— 不标出来这个数会被当成覆盖率 -->
        <div v-if="s" class="l" style="opacity: 0.7">
          {{ t('kpi.calibScope', { done: fmt(s.calibrated_hotspots), blank: fmt(s.line_counts.uncalibrated) }) }}
        </div>
      </div>
      <div>
        <div class="v">{{ s ? fmt(s.line_counts['1']) : '—' }}</div>
        <div class="u">{{ s ? t('kpi.line1Unit', { v: fmt(s.line1_m3) }) : t('kpi.pendingCalc') }}</div>
      </div>
    </div>

    <div class="k">
      <div>
        <div class="h">{{ t('kpi.line3Title') }}</div>
        <div class="l">{{ t('kpi.line3Sub', { h: S.asm.drawdown_hours }) }}</div>
      </div>
      <div>
        <div class="v">{{ s ? fmt(s.pumps_required) : '—' }}</div>
        <div class="u">{{ s ? t('kpi.line3Unit', { v: tankerBrief(s) }) : t('kpi.pendingCalc') }}</div>
      </div>
    </div>

    <div class="k">
      <div>
        <div class="h">{{ t('kpi.ledgerCompare') }}</div>
        <div class="l">{{ t('kpi.modelVsLedger') }}</div>
      </div>
      <div>
        <div class="v" :style="{ color: gap && gap.pumps_gap > 0 ? 'var(--red)' : 'var(--green)' }">
          {{ gap ? (gap.pumps_gap > 0 ? '+' + fmt(gap.pumps_gap) : '0') : '—' }}
        </div>
        <div class="u">
          {{
            gap
              ? fmt(gap.pumps_required) + t('kpi.onLedger') + fmt(gap.pumps_on_ledger)
              : t('kpi.pendingCalc')
          }}
        </div>
      </div>
    </div>
  </div>
</template>
