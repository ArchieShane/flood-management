<script setup>
import { onMounted } from 'vue'

import BriefPanel from '../components/brief/BriefPanel.vue'
import BatchPanel from '../components/calc/BatchPanel.vue'
import PointPanel from '../components/calc/PointPanel.vue'
import HotspotSearch from '../components/HotspotSearch.vue'
import InputsDrawer from '../components/drawer/InputsDrawer.vue'
import KpiPanel from '../components/KpiPanel.vue'
import MapLegend from '../components/MapLegend.vue'
import MapTools from '../components/MapTools.vue'
import MapView from '../components/MapView.vue'
import SourceTabs from '../components/SourceTabs.vue'
import StatusBar from '../components/StatusBar.vue'
import TopMenu from '../components/TopMenu.vue'
import { useBodyTheme } from '../composables/useBodyTheme'
import { t } from '../i18n'
import { useLayout } from '../composables/useLayout'
import { useScenarioStore } from '../stores/scenario'
import '../styles/command-centre.css'

useBodyTheme('theme-cc')

const S = useScenarioStore()
const { calcRight, briefRight } = useLayout()

// 台账只载一次；切走再切回来不重打接口
onMounted(() => {
  if (!S.points.length) S.boot()
})
</script>

<template>
  <MapView />
  <TopMenu />
  <div class="crumb">{{ t('menu.crumb') }}<b>{{ t('menu.crumbLast') }}</b></div>
  <SourceTabs />
  <HotspotSearch />
  <StatusBar />
  <KpiPanel />
  <MapLegend />
  <MapTools />

  <!-- 两套点走同一条计算链，故计算器与研判简报两边共用，只是点集不同 -->
  <PointPanel v-if="S.mode === 'point'" :style="{ right: calcRight }" />
  <BatchPanel v-else :style="{ right: calcRight }" />
  <BriefPanel :style="{ right: briefRight }" />

  <InputsDrawer />
</template>
