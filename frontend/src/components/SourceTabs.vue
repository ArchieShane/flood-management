<script setup>
/* 地图上看哪一套积水点。两套数据并列，切换不合并：

   「历史上报」845 个台账点 —— ADM/AAM/DRM 报上来的点位，三道防线批算对着它算。
   「模型识别」107 个易积水片区 —— ANUGA 二维演算成果反算出来的，只有 Al Bateen
     一个 run，没有 A/C/tc/Qcap，故只看不算。

   第二个页签上挂着片区数，是为了一眼看清它的体量与覆盖范围 —— 「107 · AL BATEEN」
   比一个孤零零的名字更能说明「这不是全域的一套」。 */
import { computed } from 'vue'

import { t } from '../i18n'
import { useScenarioStore } from '../stores/scenario'

const S = useScenarioStore()

const ledgerCount = computed(() => (S.sets.ledger.meta ? S.sets.ledger.meta.count : null))
const modelCount = computed(() => (S.sets.model.meta ? S.sets.model.meta.count : null))
const modelScope = computed(() => (S.model ? S.model.run.district : 'AL BATEEN'))
</script>

<template>
  <div class="srcsw">
    <div
      class="s"
      :class="{ on: S.source === 'ledger' }"
      :title="t('source.ledgerHint')"
      @click="S.setSource('ledger')"
    >
      <b>{{ t('source.ledger') }}</b>
      <span>{{ ledgerCount === null ? t('source.loading') : t('source.ledgerSub', { n: ledgerCount }) }}</span>
    </div>
    <div
      class="s"
      :class="{ on: S.source === 'model', busy: S.modelLoading }"
      :title="t('source.modelHint')"
      @click="S.setSource('model')"
    >
      <b>{{ t('source.model') }}</b>
      <span>{{
        S.modelLoading
          ? t('source.loading')
          : modelCount === null
            ? t('source.modelSubIdle')
            : t('source.modelSub', { n: modelCount, scope: modelScope })
      }}</span>
    </div>
  </div>
</template>
