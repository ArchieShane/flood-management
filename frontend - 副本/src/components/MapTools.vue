<script setup>
import AppIcon from './AppIcon.vue'
import { useLayout } from '../composables/useLayout'
import { BASEMAP_ORDER, basemapLabel } from '../constants'
import { t } from '../i18n'
import { useScenarioStore } from '../stores/scenario'
import { useToastStore } from '../stores/toast'

const S = useScenarioStore()
const toast = useToastStore()
// 侧栏盖住地图右侧，工具条贴着侧栏外沿走
const { toolsRight } = useLayout()

function toggleCoverage() {
  S.showCoverage = !S.showCoverage
  toast.show(t(S.showCoverage ? 'tools.coverageOn' : 'tools.coverageOff'))
}

function cycleBasemap() {
  S.basemap = BASEMAP_ORDER[(BASEMAP_ORDER.indexOf(S.basemap) + 1) % BASEMAP_ORDER.length]
  toast.show(t('tools.basemapSwitched', { name: basemapLabel(S.basemap) }))
}
</script>

<template>
  <div class="tools" :style="{ right: toolsRight }">
    <div class="t" :class="{ on: S.panel }" :title="t('tools.calculator')" @click="S.panel = !S.panel">
      <AppIcon name="calc" />
    </div>
    <div class="t" :class="{ on: S.brief }" :title="t('tools.brief')" @click="S.brief = !S.brief">
      <AppIcon name="chat" />
    </div>
    <div class="sep" />
    <div class="t" :class="{ on: S.showCoverage }" :title="t('tools.coverage')" @click="toggleCoverage">
      <AppIcon name="orb" />
    </div>
    <div
      class="t"
      :class="{ on: S.showNetwork, busy: S.network.mains === 'loading' }"
      :title="t('tools.network')"
      @click="S.toggleNetwork()"
    >
      <AppIcon name="pipe" />
    </div>
    <div class="t" :title="t('tools.basemap')" @click="cycleBasemap"><AppIcon name="layers" /></div>
    <div class="t" :title="t('tools.zoomIn')" @click="S.askMap('zoomIn')"><AppIcon name="plus" /></div>
    <div class="t" :title="t('tools.zoomOut')" @click="S.askMap('zoomOut')"><AppIcon name="minus" /></div>
    <div class="t" :title="t('tools.fit')" @click="S.askMap('fit')"><AppIcon name="locate" /></div>
  </div>
</template>
