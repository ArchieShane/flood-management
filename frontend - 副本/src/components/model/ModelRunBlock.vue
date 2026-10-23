<script setup>
/* 这批片区是哪来的 —— run 自述 + 使用边界。

   摆在计算器面板里是有意的：片区那一路的每一个结论都建立在「这是 Al Bateen 一个
   100 年一遇 run 的诊断性成果」之上，不知道这一点，下面那些三道防线的数字就没法用。
   文案全部由后端随成果发回（`/api/model-ponding` 的 run 与 caveats），此处原样展示。 */
import { computed } from 'vue'

import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'
import { fmt } from '../../utils/format'

const S = useScenarioStore()

const run = computed(() => (S.model ? S.model.run : null))
const sum = computed(() => (S.model ? S.model.summary : null))
</script>

<template>
  <div v-if="S.source === 'model' && run">
    <h3>{{ t('model.runHeading') }}</h3>
    <div class="rows">
      <div class="row">
        <span class="l">{{ t('model.runArea') }}</span
        ><b style="text-align: right">{{ run.area_label }}</b>
      </div>
      <div class="row">
        <span class="l">{{ t('model.runStorm') }}</span
        ><b style="text-align: right"
          >{{ t('model.rpOnceIn', { n: run.return_period_yr }) }} · {{ run.duration_min }} min ·
          {{ run.rain_total_mm }} mm</b
        >
      </div>
      <div class="row">
        <span class="l">{{ t('model.runSolver') }}</span
        ><b style="text-align: right">{{ run.solver }} · {{ run.grid_m }} m · {{ run.sim_hours }} h</b>
      </div>
      <div class="row">
        <span class="l">{{ t('model.runCoupling') }}</span
        ><b style="text-align: right">{{ run.coupling }}</b>
      </div>
      <div class="row">
        <span class="l">{{ t('model.runCriterion') }}</span
        ><b style="text-align: right">{{ run.criterion }}</b>
      </div>
    </div>

    <div v-if="sum" class="stat" style="grid-template-columns: 1fr 1fr; margin-top: 8px">
      <div>
        <div class="v">{{ fmt(sum.count) }}</div>
        <div class="l">{{ t('model.sumClusters', { cells: fmt(sum.cells) }) }}</div>
      </div>
      <div>
        <div class="v">{{ fmt(sum.max_depth_m, 2) }}<small style="font-size: 12px"> m</small></div>
        <div class="l">{{ t('model.sumMaxDepth') }}</div>
      </div>
      <div>
        <div class="v">{{ fmt(sum.area_ge_0_30m_ha, 1) }}<small style="font-size: 12px"> ha</small></div>
        <div class="l">{{ t('model.sumArea30', { all: fmt(sum.area_ha, 1) }) }}</div>
      </div>
      <div>
        <div class="v" :style="{ color: sum.never_drained ? 'var(--red)' : 'inherit' }">
          {{ fmt(sum.never_drained) }}
        </div>
        <div class="l">{{ t('model.sumNeverDrained', { h: run.sim_hours }) }}</div>
      </div>
    </div>

    <div class="note" style="margin-top: 8px">{{ t('model.runNote', { id: run.run_id }) }}</div>

    <!-- 使用边界。后端随成果一起发来的，原样摆着 —— 这几句是结论能不能用的前提 -->
    <div class="note warn" style="margin-top: 8px">
      <div v-for="c in S.model.caveats" :key="c" style="margin-bottom: 4px">· {{ c }}</div>
    </div>
  </div>
</template>
