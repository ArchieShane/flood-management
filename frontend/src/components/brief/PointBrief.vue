<script setup>
/** 单点简报：这个点从 5 年一遇一路加码到 100 年一遇，各级分别要做什么。 */
import { computed } from 'vue'

import AppIcon from '../AppIcon.vue'
import { RPS } from '../../constants'
import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'
import { fmt, muniLabel } from '../../utils/format'

const S = useScenarioStore()

const c = computed(() => S.curve)
const p = computed(() => S.byUid.get(c.value.point.uid))
const rows = computed(() => c.value.scenarios)
const hours = computed(() => S.asm.drawdown_hours)

const allDone = computed(() => RPS.every(x => rows.value.some(y => y.return_period_yr === x)))
const missing = computed(() => RPS.filter(x => !rows.value.some(y => y.return_period_yr === x)))

const rpShort = r =>
  r.return_period_yr ? t('point.rpShortYears', { n: r.return_period_yr }) : t('point.rpShortCustom')
const bg = r => (r.line === 3 ? 'rgba(224,87,78,.1)' : 'rgba(255,255,255,.05)')
const border = r => (r.line === 3 ? 'rgba(224,87,78,.2)' : 'var(--hair)')
// line 为 null（没跑过演算）给中性灰 —— 不能落到蓝色，那是「第一道成立」的颜色
const accent = r =>
  r.line === null
    ? 'rgba(255,255,255,.35)'
    : r.line === 3
      ? 'var(--red)'
      : r.line === 2
        ? 'var(--green)'
        : 'var(--blue)'
</script>

<template>
  <aside class="panel">
    <div style="display: flex; align-items: center; gap: 10px">
      <AppIcon name="orb" :size="20" /><b style="font-size: 20px">{{ t('brief.pointTitle') }}</b>
    </div>

    <div class="content">
      <div style="display: flex; justify-content: space-between; align-items: center">
        <b style="font-size: 14px">{{ p.uid }} · {{ p.location }}</b>
        <span class="src">v{{ S.inputs.v }}</span>
      </div>
      <div class="note" style="margin-top: -8px">
        {{ muniLabel(p.municipality) }} · {{ p.area }} · {{ c.dataset.label }} ·
        {{ t('brief.windowShared', { h: hours }) }}
      </div>

      <div class="stat">
        <div :style="{ borderLeft: '3px solid ' + (S.holdSummary.cls === 's' ? 'var(--green)' : 'var(--amber)') }">
          <div class="l">{{ S.holdSummary.text }}{{ t('point.tailStop') }}</div>
          <div class="v">
            {{ S.holdSummary.short }}
            <span class="l" style="font-size: 14px">{{
              S.useCustom ? t('brief.holdConclusion') : t('brief.holdCeiling')
            }}</span>
          </div>
        </div>
      </div>

      <div>
        <b style="font-size: 14px"
          >📍 {{ S.useCustom ? t('brief.dispatchOne') : t('brief.dispatchPerRp') }}</b
        >
        <div class="note" style="margin: 6px 0 8px">
          {{ S.useCustom ? t('brief.dispatchNoteCustom') : t('brief.dispatchNoteEach')
          }}{{ t('brief.dispatchNoteTail', { h: hours })
          }}<template v-if="!S.useCustom && !allDone"
            ><span
              v-html="t('brief.dispatchOnlyDone', { n: rows.length, missing: missing.join(' / ') })"
          /></template>
        </div>

        <div
          v-for="r in rows"
          :key="r.return_period_yr"
          style="margin-bottom: 8px; padding: 10px 12px; border-radius: 6px; cursor: pointer"
          :style="{ background: bg(r), border: '1px solid ' + border(r), borderLeft: '3px solid ' + accent(r) }"
          @click="S.setCurveRp(r.return_period_yr)"
        >
          <div style="display: flex; justify-content: space-between; gap: 10px; margin-bottom: 6px">
            <b
              >{{ rpShort(r) }}<span class="l" style="font-weight: 400">
                · I {{ fmt(r.intensity_mm_hr, 1) }} mm/h · Q {{ fmt(r.peak_flow_m3s, 2) }} m³/s</span
              ></b
            >
            <!-- null 要先判：落到 v-else 会把「没算」说成「需出动车队」 -->
            <span v-if="r.line === null" class="tag l">{{ t('curve.tagNone') }}</span>
            <span v-else-if="r.line === 1" class="tag b">{{ t('curve.tagLine1') }}</span>
            <span v-else-if="r.line === 2" class="tag s">{{ t('curve.tagLine2') }}</span>
            <span v-else class="tag d">{{ S.pumpBrief(r) }}</span>
          </div>

          <div style="line-height: 1.5">
            <template v-if="r.line === 3">
              <span style="color: var(--amber)" v-html="t('brief.orderLabel')" />
              <span
                v-html="
                  t('brief.orderPoint3', {
                    brief: S.pumpBrief(r),
                    loads: r.tanker_loads,
                    h: hours,
                    v: fmt(r.shortfall_m3),
                    ledger: fmt(p.pumps_qty),
                  })
                "
              />
            </template>
            <template v-else-if="r.line === 2">
              <span
                v-html="
                  t('brief.orderPoint2', {
                    h: hours,
                    drained: fmt(r.network_drained_m3),
                    residual: fmt(r.residual_after_network_m3),
                  })
                "
              />
            </template>
            <template v-else-if="r.line === null">
              <span class="l" v-html="t('brief.orderPointNone')" />
            </template>
            <template v-else>
              <span v-html="t('brief.orderPoint1', { runoff: fmt(r.runoff_volume_m3), h: hours })" /><template
                v-if="r.peak_exceeds_capacity"
                ><br /><span
                  class="warn"
                  v-html="
                    t('brief.orderPoint1Warn', {
                      q: fmt(r.peak_flow_m3s, 2),
                      qcap: fmt(r.qcap_m3s, 2),
                      h: hours,
                    })
                  "
              /></template>
            </template>
          </div>
        </div>
      </div>

      <div>
        <b style="font-size: 14px">{{ t('brief.caveatsHeading') }}</b>
        <div class="note" style="margin-top: 6px">
          <template v-for="(x, i) in (c.limitations || [])" :key="i">· {{ x }}<br /></template>
        </div>
        <div class="note" style="margin-top: 6px" v-html="t('brief.pointCaveat')" />
      </div>
    </div>

    <div class="note" style="text-align: center">{{ t('brief.footerComputed') }}</div>
  </aside>
</template>
