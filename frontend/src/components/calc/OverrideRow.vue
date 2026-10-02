<script setup>
import { computed } from 'vue'

import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'

const props = defineProps({
  label: { type: String, required: true },
  field: { type: String, required: true },
  unit: { type: String, required: true },
  step: { type: Number, required: true },
  // 这个旋钮的取值被别处的数据定住时，在标签下加一行说清是被谁定住的
  note: { type: String, default: '' },
})

const S = useScenarioStore()

const value = computed(() => S.asm[props.field])
const overridden = computed(
  () => S.over[props.field] != null && S.over[props.field] !== S.inputs.assumptions[props.field],
)

function onChange(e) {
  S.over[props.field] = e.target.value === '' ? null : Number(e.target.value)
  // 假设变了，这个点已算的结论跟着作废 —— 但不替人重算
  if (S.mode === 'point') S.invalidatePoint(t('inputs.assumptionChanged'))
}
</script>

<template>
  <div class="row">
    <span class="l"
      >{{ props.label }}<br />
      <span style="opacity: 0.7">{{
        overridden
          ? t('inputs.overrideOf', { v: S.inputs.v, value: S.inputs.assumptions[props.field] })
          : t('inputs.fromModel', { v: S.inputs.v })
      }}</span>
      <template v-if="props.note"
        ><br /><span class="src">{{ props.note }}</span></template
      >
    </span>
    <span style="display: flex; align-items: center; gap: 6px">
      <input type="number" :step="props.step" min="0" :value="value" @change="onChange" />
      <span class="l">{{ props.unit }}</span>
      <span
        v-if="overridden"
        class="tag b"
        style="cursor: pointer"
        @click="S.over[props.field] = null"
        >{{ t('inputs.reset') }}</span
      >
    </span>
  </div>
</template>
