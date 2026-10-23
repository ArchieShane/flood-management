<script setup>
/* 推理公式法算出的来水量 × 二维演算实测的积水量，**并列对照**。

   这是全项目唯一一处能拿实测量去校核推理公式法的地方 —— 107 个模型片区全都有，
   845 个台账点里只有 Al Bateen 的 18 个有。

   ⚠ 两个数**历时口径不同，比值不是误差**：推理公式法的来水量是 tc 历时（本批
     中位 13 min）内那一段设计峰值过程线的体积，是筛查排序用的量；演算积水量是
     整场 180 min 雨下来实际滞留的水，还含管网溢流注入与汇流范围外流进来的水。
     故后者系统性地大得多 —— 这正是交接文档 §3.7 第一条「推理公式法属筛查工具、
     非最终设计」的量化版本。说明文字由后端随结果发来，此处原样展示。

   页面选的重现期与该 run 的重现期不一致时（`comparable === false`），
   两个数不是同一场雨，此处会把它说破，而不是让人以为可以直接比。 */
import { computed } from 'vue'

import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'
import { fmt } from '../../utils/format'

const S = useScenarioStore()

const c = computed(() => (S.result ? S.result.ponding_check : null))
</script>

<template>
  <div v-if="c">
    <h3>{{ t('check.title') }}</h3>
    <div class="rows">
      <div class="row">
        <span class="l">{{ t('check.rational') }}</span
        ><b>{{ fmt(c.rational_runoff_m3) }} m³</b>
      </div>
      <div class="row">
        <span class="l">{{ t('check.anuga', { rp: c.run_return_period_yr }) }}</span
        ><b>{{ fmt(c.anuga_net_inflow_m3) }} m³</b>
      </div>
      <div class="row">
        <span class="l">{{ t('check.ratio') }}</span>
        <b v-if="c.comparable" class="tag w">{{ fmt(c.ratio, 2) }}×</b>
        <span v-else class="tag n">{{ t('check.notComparable') }}</span>
      </div>
      <div class="row">
        <span class="l">{{ t('check.points') }}</span
        ><b>{{ fmt(c.points) }}</b>
      </div>
    </div>
    <div class="note warn" v-if="!c.comparable" style="margin-top: 6px">
      {{ t('check.rpMismatch', { rp: c.run_return_period_yr }) }}
    </div>
    <div class="note" style="margin-top: 6px">{{ c.note }}</div>
  </div>
</template>
