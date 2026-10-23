<script setup>
import { computed } from 'vue'

import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'
import { fmt } from '../../utils/format'

const S = useScenarioStore()

const bySource = computed(() => {
  const out = {}
  S.points.forEach(p => {
    out[p.source] = (out[p.source] || 0) + 1
  })
  return Object.entries(out)
    .map(([k, v]) => `${k} ${v}`)
    .join(' · ')
})

const flags = computed(() => {
  const out = {}
  S.points.forEach(p => p.qc_flags.forEach(f => (out[f] = (out[f] || 0) + 1)))
  return (
    Object.entries(out)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${k} ${v}`)
      .join(' · ') || t('drawer.dataFlagsNone')
  )
})

const z = computed(() => S.meta.zone)
const totalPumps = computed(() => S.points.reduce((a, p) => a + (p.pumps_qty || 0), 0))
const totalTankers = computed(() => S.points.reduce((a, p) => a + (p.tankers_qty || 0), 0))
const versions = computed(() => [...S.history].reverse())
</script>

<template>
  <div>
    <table>
      <thead>
        <tr><th>{{ t('drawer.dataKey') }}</th><th>{{ t('drawer.dataValue') }}</th></tr>
      </thead>
      <tbody>
        <tr>
          <td>{{ t('drawer.dataTotal') }}</td>
          <td><b>{{ S.meta.count }}</b>{{ t('drawer.dataTotalNote') }}</td>
        </tr>
        <tr><td>{{ t('drawer.dataSources') }}</td><td>{{ bySource }}</td></tr>
        <tr>
          <td>{{ t('drawer.dataCoords') }}</td>
          <td>{{ t('drawer.dataCoordsNote', { n: S.meta.count }) }}</td>
        </tr>
        <tr>
          <td>{{ t('drawer.dataZone') }}</td>
          <td>{{ t('drawer.dataZoneValue', { a: z.zone_a, b: z.zone_b, src: z.source }) }}</td>
        </tr>
        <tr><td>{{ t('drawer.dataFlags') }}</td><td>{{ flags }}</td></tr>
        <tr>
          <td>{{ t('drawer.dataFleet') }}</td>
          <td>{{ t('drawer.dataFleetNote', { pumps: fmt(totalPumps), tankers: fmt(totalTankers) }) }}</td>
        </tr>
      </tbody>
    </table>

    <h3 style="margin: 20px 0 10px">{{ t('drawer.versionsHeading') }}</h3>
    <table>
      <thead>
        <tr>
          <th>{{ t('drawer.verV') }}</th><th>{{ t('drawer.verTs') }}</th><th>{{ t('drawer.verWhat') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="h in versions" :key="h.v">
          <td>
            <b>v{{ h.v }}</b><span v-if="h.v === S.inputs.v" class="tag s">{{ t('drawer.verCurrent') }}</span>
          </td>
          <td>{{ h.ts }}</td>
          <td>{{ h.what }}</td>
        </tr>
        <tr v-if="!versions.length"><td colspan="3" class="note">{{ t('drawer.verNone') }}</td></tr>
      </tbody>
    </table>

    <div class="note" style="margin-top: 10px">{{ t('drawer.versionWarn') }}</div>
  </div>
</template>
