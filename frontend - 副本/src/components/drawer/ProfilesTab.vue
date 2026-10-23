<script setup>
import { computed } from 'vue'

import { priorityList } from '../../constants'
import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'
import { causeLabel, muniLabel } from '../../utils/format'

const S = useScenarioStore()
const D = computed(() => S.draft)

const FIELDS = [
  { key: 'area_ha', step: 0.1, eff: 'catchment' },
  { key: 'runoff_c', step: 0.05, eff: 'catchment' },
  { key: 'tc_min', step: 0.1, eff: 'catchment' },
  { key: 'qcap_m3s', step: 0.1, eff: 'qcap' },
  { key: 'pond_available_m3', step: 100, eff: null },
]

const priorities = computed(() => priorityList())
const groups = computed(() => Object.keys(D.value.profiles))
const basis = computed(() => S.meta.profile_field_basis)

const effective = (field, group) =>
  field.eff === 'qcap'
    ? S.qcapEditableCount(group)
    : field.eff === 'catchment'
      ? S.catchmentEditableCount(group)
      : null

const setProfile = (g, f, e) => {
  D.value.profiles[g][f] = e.target.value === '' ? null : Number(e.target.value)
}

const noNetworkMeasured = computed(
  () => S.points.filter(p => p.qcap_basis === 'measured_no_network').length,
)
const noNetworkLedger = computed(
  () => S.points.filter(p => p.qcap_basis === 'no_coverage' && p.network_available === false).length,
)
const cov = computed(() => (S.meta ? S.meta.coverage : null))
const covOutside = computed(() =>
  cov.value
    ? Object.entries(cov.value.outside_by_municipality)
        .map(([k, v]) => `${muniLabel(k)} ${v}`)
        .join(' · ')
    : '',
)
</script>

<template>
  <div>
    <div class="note" style="margin-bottom: 12px" v-html="t('drawer.profileIntro')" />

    <table>
      <thead>
        <tr>
          <th>{{ t('drawer.profGroup') }}</th>
          <th class="r">{{ t('drawer.profCount') }}</th>
          <th class="r">{{ t('drawer.profArea') }}</th>
          <th class="r">{{ t('drawer.profC') }}</th>
          <th class="r">{{ t('drawer.profTc') }}</th>
          <th class="r" v-html="t('drawer.profQcap')" />
          <th class="r">{{ t('drawer.profPond') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="g in groups" :key="g">
          <td>
            <b>{{ g === '_default' ? t('drawer.profOther') : causeLabel(g) }}</b>
            <div class="note">{{ g }}</div>
          </td>
          <td class="r">{{ S.groupCounts[g] || 0 }}</td>
          <td v-for="f in FIELDS" :key="f.key" class="r">
            <input
              type="number"
              :step="f.step"
              min="0"
              class="key"
              :value="D.profiles[g][f.key]"
              @change="setProfile(g, f.key, $event)"
            />
            <div v-if="effective(f, g) !== null" class="note" style="margin-top: 2px">
              <span v-if="effective(f, g) === 0" style="color: var(--amber)">{{
                t('drawer.profNoEffect')
              }}</span>
              <template v-else>{{
                t('drawer.profEffective', { n: effective(f, g), total: S.groupCounts[g] || 0 })
              }}</template>
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <div class="note" style="margin-top: 10px">
      {{ t('drawer.profBasisHead') }}<br />
      <template v-for="([f, x], i) in Object.entries(basis)" :key="i">· <b>{{ f }}</b> —— {{ x }}<br /></template>
    </div>

    <div class="rows" style="margin-top: 14px; max-width: 560px">
      <div class="row">
        <span class="l"
          >{{ t('drawer.covOnlyLabel') }}<br />
          <span style="opacity: 0.7">
            <template v-if="cov"
              ><span
                v-html="
                  t('drawer.covOnlyWith', {
                    inside: cov.inside,
                    outside: cov.outside,
                    byMuni: covOutside,
                  })
                "
            /></template>
            <template v-else>{{ t('drawer.covOnlyWithout') }}</template>
          </span>
        </span>
        <input v-model="D.coverageOnly" type="checkbox" style="width: auto" />
      </div>

      <div class="row">
        <span class="l"
          ><span v-html="t('drawer.zeroQcapLabel')" /><br />
          <span
            style="opacity: 0.7"
            v-html="
              t('drawer.zeroQcapNote', { measured: noNetworkMeasured, ledger: noNetworkLedger })
            "
          />
        </span>
        <input v-model="D.zeroQcap" type="checkbox" style="width: auto" />
      </div>

      <div class="row">
        <span class="l"
          ><span v-html="t('drawer.priorityLabel')" /><br />
          <span style="opacity: 0.7">{{ t('drawer.priorityNote') }}</span>
        </span>
        <select v-model="D.priority">
          <option v-for="o in priorities" :key="String(o.v)" :value="o.v">{{ o.label }}</option>
        </select>
      </div>
    </div>
  </div>
</template>
