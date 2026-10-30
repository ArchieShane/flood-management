<script setup>
import { computed, ref } from 'vue'

import { datasetList } from '../constants'
import { LOCALES, locale, setLocale, t } from '../i18n'
import { useScenarioStore } from '../stores/scenario'
import { useToastStore } from '../stores/toast'
import { nowStamp } from '../utils/format'

const S = useScenarioStore()
const toast = useToastStore()

// 时间戳是「这一屏是什么时候的」，不是时钟：只在挂载时取一次，与原行为一致
const stamp = ref(nowStamp())
const datasets = computed(() => datasetList())

/** 切语言。后端那批文案（IDF 口径、limitations、出处标签）是随结果发回来的，
 *  换了语言得重新取一遍，否则新中文界面里躺着一段旧英文。
 *  页面标题由 App.vue 监听 locale 改，这里不重复。 */
function switchLocale(key) {
  if (key === locale.value) return
  setLocale(key)
  S.refetchLocalised()
  toast.show(t('toast.localeSwitched'))
}
</script>

<template>
  <header class="menu">
    <div class="logo">LX</div>
    <div class="t">{{ t('menu.title') }}</div>
    <div class="nav">
      <span>{{ t('menu.nav1') }}</span><span>{{ t('menu.nav2') }}</span><b>{{ t('menu.nav3') }}</b
      ><RouterLink class="link" to="/simulations">{{ t('menu.simulation') }}</RouterLink
      ><RouterLink class="link" to="/rda">RD-A 成果</RouterLink><span>ADREC</span>
    </div>
    <div class="right">
      <span class="note">{{ t('menu.idfDataset') }}</span>
      <div class="seg">
        <span
          v-for="d in datasets"
          :key="d.key"
          :class="{ on: S.dataset === d.key && !S.useCustom }"
          :title="d.hint"
          @click="S.setDataset(d.key)"
          >{{ d.label }}</span
        >
        <span
          :class="{ on: S.useCustom }"
          :title="t('menu.customStormHint')"
          @click="S.setDataset('custom_storm')"
          >{{ t('menu.customStorm') }}</span
        >
      </div>
      <span class="note" style="margin-left: 4px">{{ t('menu.language') }}</span>
      <div class="seg">
        <span
          v-for="l in LOCALES"
          :key="l.key"
          :class="{ on: locale === l.key }"
          @click="switchLocale(l.key)"
          >{{ l.label }}</span
        >
      </div>
      <span class="note" style="margin-left: 4px">{{ stamp }}</span>
    </div>
  </header>
</template>
