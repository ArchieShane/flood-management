<script setup>
import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'

const S = useScenarioStore()
</script>

<template>
  <!-- 模式切换条 —— 两种交互的入口，放在侧栏标题旁边 -->
  <div class="pills" style="padding: 3px">
    <span
      :class="{ on: S.mode === 'point' }"
      style="padding: 5px 10px"
      @click="S.setMode('point')"
      >{{ t('mode.point') }}</span
    >
    <span :class="{ on: S.mode === 'batch' }" style="padding: 5px 10px" @click="S.setMode('batch')"
      >{{ t('mode.batch') }}</span
    >
  </div>
</template>
