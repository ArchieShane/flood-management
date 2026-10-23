<script setup>
import { computed } from 'vue'

import { COLOR, MECHANISM_COLOR, NETWORK_STYLE } from '../constants'
import { t } from '../i18n'
import { useScenarioStore } from '../stores/scenario'
import { UNFILLED } from '../utils/format'

const S = useScenarioStore()

const ran = computed(() => S.mode === 'batch' && !!S.result)
// 没跑批算时，片区按成因分色（台账按严重度）—— 与 store 的 colorFor 同一口径
const model = computed(() => S.source === 'model' && !ran.value)

const items = computed(() =>
  ran.value
    ? [
        [COLOR.line1, t('legend.line1')],
        [COLOR.line2, t('legend.line2')],
        [COLOR.line3a, t('legend.line3a')],
        [COLOR.line3b, t('legend.line3b')],
        [COLOR.line3c, t('legend.line3c')],
        // 图例里必须有这一档 —— 地图上 483 个灰点没有图例就会被当成「没数据的底图点」
        [COLOR.uncalibrated, t('legend.uncalibrated')],
      ]
    : [
        [COLOR.crit['Very High'], t('legend.critVeryHigh')],
        [COLOR.crit.High, t('legend.critHigh')],
        [COLOR.crit.Medium, t('legend.critMedium')],
        [COLOR.crit.Low, t('legend.critLow')],
        [COLOR.crit[UNFILLED], t('legend.unrated')],
      ],
)

const showCov = computed(() => S.coverage && S.showCoverage)

/* 管网图例只列已经画出来的等级 —— 没到起画缩放的那几级列上去只会让人找不着。 */
const netItems = computed(() => {
  if (!S.showNetwork) return []
  const keys = ['TRUNK_MAIN', 'PRIMARY', 'SECONDARY', 'LATERAL']
  const labels = { TRUNK_MAIN: 'netTrunk', PRIMARY: 'netPrimary', SECONDARY: 'netSecondary', LATERAL: 'netLateral' }
  return keys.map(k => [NETWORK_STYLE[k], t(`legend.${labels[k]}`)])
})
</script>

<template>
  <!-- 模型片区：按成因分色，与台账那套「按严重度/按防线」是两套口径，不混用 -->
  <div v-if="model" class="legend">
    <b>{{
      S.model
        ? t('legend.modelTitle', { rp: S.model.run.return_period_yr, district: S.model.run.district })
        : t('legend.modelTitleIdle')
    }}</b>
    <div v-for="m in S.modelMechRows" :key="m.key">
      <i :style="{ background: MECHANISM_COLOR[m.key] }" />{{ m.label }} · {{ m.n }}
    </div>
    <!-- 管网线在两路数据下都能开，图例跟着一起列 -->
    <template v-if="netItems.length">
      <div v-for="([st, x]) in netItems" :key="x" style="margin-top: 2px">
        <i class="ln" :style="{ background: st.color, opacity: st.opacity }" />{{ x }}
      </div>
    </template>
    <span class="note">{{ t('legend.modelNote') }}</span>
  </div>

  <div v-else class="legend">
    <b>{{ ran ? t('legend.resultTitle') + S.stormLabel : t('legend.ledgerTitle') }}</b>
    <div v-for="([c, x]) in items" :key="x"><i :style="{ background: c }" />{{ x }}</div>
    <template v-if="netItems.length">
      <div v-for="([st, x]) in netItems" :key="x" style="margin-top: 2px">
        <i class="ln" :style="{ background: st.color, opacity: st.opacity }" />{{ x }}
      </div>
    </template>
    <template v-if="showCov">
      <div style="margin-top: 7px">
        <i class="sq" style="background: rgba(102, 197, 107, 0.45)" /><span v-html="t('legend.covComputable')" />
      </div>
      <div><i class="sq" style="background: rgba(71, 134, 201, 0.4)" />{{ t('legend.covNetwork') }}</div>
      <div>
        <i
          class="sq"
          style="background: rgba(71, 134, 201, 0.14); outline: 1px dashed rgba(71, 134, 201, 0.8)"
        />{{ t('legend.covExtent') }}
      </div>
      <div><i class="hollow" />{{ t('legend.covOutside') }}</div>
    </template>
    <span class="note"
      >{{ t('legend.noteHead')
      }}{{
        ran
          ? t('legend.noteRan')
          : S.mode === 'point'
            ? t('legend.notePoint')
            : t('legend.noteBatch')
      }}{{ S.coverage ? t('legend.noteCoverage') : '' }}</span
    >
  </div>
</template>
