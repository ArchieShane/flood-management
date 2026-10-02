<script setup>
import { computed } from 'vue'

import AssumptionsTab from './AssumptionsTab.vue'
import DataTab from './DataTab.vue'
import HyetographTab from './HyetographTab.vue'
import IdfTab from './IdfTab.vue'
import ProfilesTab from './ProfilesTab.vue'
import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'

const S = useScenarioStore()

const TABS = computed(() => [
  ['profiles', t('drawer.tabProfiles')],
  ['assumptions', t('drawer.tabAssumptions')],
  ['idf', t('drawer.tabIdf')],
  ['hyeto', t('drawer.tabHyeto')],
  ['data', t('drawer.tabData')],
])

const nextV = computed(() => S.nextV())

// 点遮罩关闭，点面板本身不关
const onBackdrop = ev => {
  if (ev.target.classList.contains('drawer')) S.cancelDrawer()
}
</script>

<template>
  <div v-if="S.drawer && S.draft" class="drawer" @click="onBackdrop">
    <div class="sheet">
      <div class="hd">
        <div>
          <h2>{{ t('drawer.title') }}</h2>
          <div class="note">
            {{ t('drawer.subtitle', { v: S.inputs.v }) }}<template v-if="S.inputs.ts">
              · {{ S.inputs.ts }}</template
            >
          </div>
        </div>
        <div style="display: flex; gap: 8px">
          <button class="ghost" style="flex: none" @click="S.cancelDrawer()">{{ t('drawer.cancel') }}</button>
          <button class="cta" style="width: auto; padding: 10px 20px" @click="S.saveDrawer()">
            {{ t('drawer.saveAs', { v: nextV }) }}
          </button>
        </div>
      </div>

      <div class="tabs2">
        <span v-for="[k, label] in TABS" :key="k" :class="{ on: S.tab === k }" @click="S.tab = k">{{
          label
        }}</span>
      </div>

      <div class="sheetbody">
        <ProfilesTab v-if="S.tab === 'profiles'" />
        <AssumptionsTab v-else-if="S.tab === 'assumptions'" />
        <IdfTab v-else-if="S.tab === 'idf'" />
        <HyetographTab v-else-if="S.tab === 'hyeto'" />
        <DataTab v-else-if="S.tab === 'data'" />
      </div>

      <div class="note">{{ t('drawer.footer') }}</div>
    </div>
  </div>
</template>
