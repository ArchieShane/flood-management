<script setup>
import { computed } from 'vue'

import { catchmentBasis, pondingBasis, qcapBasis, storageBasis } from '../../utils/basis'

const props = defineProps({
  kind: { type: String, required: true }, // qcap | catchment | storage | ponding
  basis: { type: String, default: '' },
})

const PICK = { qcap: qcapBasis, catchment: catchmentBasis, storage: storageBasis, ponding: pondingBasis }
const b = computed(() => PICK[props.kind](props.basis))
</script>

<template>
  <span class="tag" :class="b[0]" :title="b[2]">{{ b[1] }}</span>
</template>
