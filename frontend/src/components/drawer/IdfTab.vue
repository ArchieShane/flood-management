<script setup>
/* IDF 表由后端提供，只读 —— 它是法定标准的原文数据，不是可调参数。 */
import { computed, ref, watch } from 'vue'

import { fetchIdfTable } from '../../api'
import { locale, t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'
import { fmt } from '../../utils/format'

const S = useScenarioStore()
const table = ref(null)
const error = ref('')

// 自动分区与自定义雨都没有自己的 IDF 表，回落到平原区那一套
const key = computed(() => (S.dataset === 'auto' || S.useCustom ? 'adqcc_zone_b' : S.dataset))

const returnPeriods = computed(() =>
  table.value ? Object.keys(table.value.intensity_mm_hr).sort((a, b) => b - a) : [],
)

async function load() {
  error.value = ''
  try {
    table.value = await fetchIdfTable(key.value)
  } catch (e) {
    error.value = e.message
  }
}

// label / source / notes 都是后端文案，换语言得重取一遍
watch([key, locale], load, { immediate: true })
</script>

<template>
  <div>
    <div class="note" style="margin-bottom: 12px" v-html="t('drawer.idfIntro')" />

    <div v-if="error" class="note warn">{{ t('drawer.idfError', { msg: error }) }}</div>
    <div v-else-if="!table"><div class="skel" /><div class="skel" /><div class="skel" /></div>
    <template v-else>
      <div style="margin-bottom: 10px">
        <b>{{ table.label }}</b>
        <div class="note">{{ table.source }}</div>
      </div>
      <table>
        <thead>
          <tr>
            <th>{{ t('drawer.idfHead') }}</th>
            <th v-for="x in table.durations_min" :key="x" class="r">{{ x }}</th>
            <th class="r">{{ t('drawer.idfDepth24h') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="rp in returnPeriods" :key="rp">
            <td><b>{{ t('drawer.idfRpRow', { n: rp }) }}</b></td>
            <td v-for="(v, i) in table.intensity_mm_hr[rp]" :key="i" class="r">{{ fmt(v, 2) }}</td>
            <td class="r"><b>{{ fmt(table.depth_24h_mm[rp], 2) }}</b></td>
          </tr>
        </tbody>
      </table>
      <div class="note" style="margin-top: 10px">
        <template v-for="(n, i) in table.notes" :key="i">· {{ n }}<br /></template>
      </div>
      <div class="note" style="margin-top: 6px">
        {{
          t('drawer.idfFooter', {
            tc: t(table.supports_tc_multiplier ? 'drawer.idfTcYes' : 'drawer.idfTcNo'),
            cf: t(table.supports_cf ? 'drawer.idfCfYes' : 'drawer.idfCfNo'),
          })
        }}
      </div>
    </template>
  </div>
</template>
