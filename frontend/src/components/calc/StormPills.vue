<script setup>
/* 降雨选择条（全域批算用）—— 它决定这一次批算的是哪一场雨。 */
import { RPS } from '../../constants'
import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'

const S = useScenarioStore()

const onCustom = (field, e) => {
  S.custom[field] = e.target.value === '' ? null : Number(e.target.value)
}
</script>

<template>
  <div class="pills">
    <span
      v-for="r in RPS"
      :key="r"
      :class="{ on: !S.useCustom && S.rp === r }"
      @click="S.setStorm(r)"
      >{{ t('storm.rpYears', { n: r }) }}</span
    >
    <span :class="{ on: S.useCustom }" @click="S.setStorm('custom')">{{ t('storm.custom') }}</span>
  </div>
  <div
    v-if="S.useCustom"
    class="note"
    style="display: flex; gap: 6px; align-items: center; margin-top: 8px"
  >
    {{ t('storm.pillDepth') }}
    <input type="number" :value="S.custom.P" style="width: 66px" @change="onCustom('P', $event)" /> mm /
    {{ t('storm.pillDuration') }}
    <input type="number" :value="S.custom.D" style="width: 66px" @change="onCustom('D', $event)" /> min
    <span class="src">{{ t('storm.nonStandard') }}</span>
  </div>
</template>
