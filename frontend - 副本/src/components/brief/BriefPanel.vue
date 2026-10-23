<script setup>
import AppIcon from '../AppIcon.vue'
import BatchBrief from './BatchBrief.vue'
import PointBrief from './PointBrief.vue'
import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'

const S = useScenarioStore()
</script>

<template>
  <PointBrief v-if="S.mode === 'point' && S.curve" />
  <BatchBrief v-else-if="S.mode === 'batch' && S.result" />

  <!-- 还没算过：摆一段说明，别摆一张空骨架 -->
  <aside v-else class="panel">
    <div style="display: flex; align-items: center; gap: 10px">
      <AppIcon name="orb" :size="20" />
      <b style="font-size: 20px">{{ S.mode === 'point' ? t('brief.pointTitle') : t('brief.batchTitle') }}</b>
    </div>
    <div class="content">
      <div class="note">{{ S.mode === 'point' ? t('brief.emptyPoint') : t('brief.emptyBatch') }}</div>
    </div>
    <div class="note" style="text-align: center">{{ t('brief.footerSource') }}</div>
  </aside>
</template>
