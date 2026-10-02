<script setup>
import { computed } from 'vue'

import { basemapLabel } from '../constants'
import { t } from '../i18n'
import { useScenarioStore } from '../stores/scenario'

const S = useScenarioStore()
const scoped = computed(() => S.filtered.filter(S.inScope).length)
const dropped = computed(() => S.filtered.length - scoped.value)
</script>

<template>
  <div class="status">
    <!-- 模型片区：说清这是哪一次 run、覆盖多大、判据是什么 -->
    <template v-if="S.source === 'model'">
      <template v-if="S.meta && S.model">
        {{ t('status.modelLine1', { n: S.meta.count, cells: S.model.summary.cells, shown: S.filtered.length }) }}<br />
        {{ t('status.line2', { scoped }) }}<br />
        {{ t('status.modelLine3', { rp: S.model.run.return_period_yr, d: S.model.run.duration_min, mm: S.model.run.rain_total_mm }) }}<br />
        {{ t('status.basemap', { name: basemapLabel(S.basemap) }) }}
      </template>
      <template v-else>{{ t('status.modelLoading') }}</template>
    </template>
    <template v-else-if="S.meta">
      {{ t('status.line1', { total: S.meta.count, shown: S.filtered.length }) }}<br />
      {{ t('status.line2', { scoped }) }}<template v-if="dropped">{{
        t('status.dropped', { n: dropped })
      }}</template
      ><br />
      {{
        t('status.zone', {
          a: S.meta.zone.zone_a,
          b: S.meta.zone.zone_b,
          threshold: S.meta.zone.threshold_m,
        })
      }}<br />
      {{ t('status.basemap', { name: basemapLabel(S.basemap) }) }}
    </template>
    <template v-else>{{ t('status.loading') }}</template>
  </div>
</template>
