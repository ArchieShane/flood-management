<script setup>
/* 单点模式：选一级 → 看默认参数 → 计算。

   标准重现期的雨量与历时不是旋钮：历时由该点 tc（× 优先级乘数 M）定，
   强度由导则 IDF 公式按重现期反查，雨量 P = I × D / 60。三个数都没有可选余地，
   故页面只读地摆出来，让人算之前先看清这一级到底是多大一场雨。
   要脱开导则压力测试，只能切「自定义」——那一档才给输入框。 */
import { computed } from 'vue'

import AppIcon from '../AppIcon.vue'
import { RPS } from '../../constants'
import { t } from '../../i18n'
import { useScenarioStore } from '../../stores/scenario'
import { fmt } from '../../utils/format'

const S = useScenarioStore()

const q = computed(() => S.preset)
const done = computed(() => (S.useCustom ? S.isComputed(0) : S.isComputed(S.curveRp)))
const ready = computed(() => (S.useCustom ? true : !!S.preset))
const what = computed(() =>
  S.useCustom
    ? t('storm.whatCustom', { p: S.custom.P, d: S.custom.D })
    : t('storm.whatRp', { n: S.curveRp }),
)

function onCustom(field, e) {
  S.custom[field] = e.target.value === '' ? null : Number(e.target.value)
  S.invalidatePoint(t('storm.customChanged'))
  S.loadPreset()
}
</script>

<template>
  <div class="pills">
    <span
      v-for="r in RPS"
      :key="r"
      :class="{ on: !S.useCustom && S.curveRp === r }"
      :title="S.isComputed(r) ? t('storm.computedHint') : t('storm.notComputedHint')"
      @click="S.setStorm(r)"
      >{{ t('storm.rpYears', { n: r }) }}{{ S.isComputed(r) ? ' ✓' : '' }}</span
    >
    <span :class="{ on: S.useCustom }" @click="S.setStorm('custom')">{{ t('storm.custom') }}</span>
  </div>

  <!-- 选中这一级之后、按下「计算」之前显示的那一屏 -->
  <template v-if="S.useCustom">
    <div class="rows" style="margin-top: 8px">
      <div class="row">
        <span class="l">{{ t('storm.depthP') }}</span>
        <b
          ><input type="number" min="1" step="1" :value="S.custom.P" @change="onCustom('P', $event)" /> mm
          <span class="tag b">{{ t('storm.adjustable') }}</span></b
        >
      </div>
      <div class="row">
        <span class="l">{{ t('storm.givenD') }}</span>
        <b
          ><input type="number" min="1" step="5" :value="S.custom.D" @change="onCustom('D', $event)" /> min
          <span class="tag b">{{ t('storm.adjustable') }}</span></b
        >
      </div>
      <div class="row">
        <span class="l">{{ t('storm.actualD') }}</span><b>{{ q ? fmt(q.duration_min, 1) + ' min' : '…' }}</b>
      </div>
      <div class="row">
        <span class="l">{{ t('storm.intensityI') }}</span
        ><b>{{ q ? fmt(q.intensity_mm_hr, 1) + ' mm/h' : '…' }}</b>
      </div>
    </div>
    <div class="note" style="margin-top: 6px">
      <span v-html="t('storm.customNote')" /><template v-if="q && q.duration_min > S.custom.D"
        ><span
          v-html="t('storm.customNoteTc', { tc: fmt(q.tc_min, 1), d: fmt(q.duration_min, 1) })" /></template
      >{{ t('storm.customNoteTail') }}
    </div>
  </template>

  <div v-else-if="S.presetLoading || !q" style="margin-top: 8px">
    <div class="skel" />
    <div class="skel" style="width: 70%" />
    <div class="note">{{ t('storm.presetLoading', { n: S.curveRp }) }}</div>
  </div>

  <template v-else>
    <div class="rows" style="margin-top: 8px">
      <div class="row">
        <span class="l">{{ t('storm.depthP') }}</span>
        <b
          ><input type="number" :value="fmt(q.depth_mm, 1)" disabled /> mm
          <span class="tag n" :title="t('storm.locked')"
            ><AppIcon name="lock" :size="11" :opacity="0.85" /></span
        ></b>
      </div>
      <div class="row">
        <span class="l">{{ t('storm.durationD') }}</span>
        <b
          ><input type="number" :value="fmt(q.duration_min, 1)" disabled /> min
          <span class="tag n" :title="t('storm.locked')"
            ><AppIcon name="lock" :size="11" :opacity="0.85" /></span
        ></b>
      </div>
      <div class="row">
        <span class="l">{{ t('storm.intensityI') }}</span>
        <b
          >{{ fmt(q.intensity_mm_hr, 1) }} mm/h
          <span class="tag n" :title="t('storm.locked')"
            ><AppIcon name="lock" :size="11" :opacity="0.85" /></span
        ></b>
      </div>
    </div>
    <div class="note" style="margin-top: 6px">
      <span
        v-html="
          t('storm.stdNote', {
            rp: q.return_period_yr,
            dataset: q.dataset.label,
            tc: fmt(q.tc_min, 1),
            m: q.tc_multiplier,
          })
        "
      /><template v-if="q.priority_label">{{
        t('storm.stdNotePriority', { label: q.priority_label })
      }}</template
      ><span v-html="t('storm.stdNoteTail')" />
    </div>
  </template>

  <button
    class="cta"
    style="margin-top: 10px"
    :disabled="S.curveLoading || !ready"
    @click="S.runPoint()"
  >
    <AppIcon name="play" :size="16" />
    {{
      S.curveLoading
        ? t('storm.calculating')
        : done
          ? t('storm.recalcBtn', { what })
          : t('storm.calcBtn', { what })
    }}
  </button>
  <div v-if="!done" class="note" style="margin-top: 6px; text-align: center">
    {{ t('storm.chainNote') }}
  </div>
</template>
