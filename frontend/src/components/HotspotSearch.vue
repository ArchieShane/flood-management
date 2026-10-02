<script setup>
/* 搜索积水点。只查已经载入的 845 条台账，纯前端不打接口 —— 台账一次性载完，
   再发请求只会更慢。命中排序与「输 31 找 ADM-031」的规则见 store.searchHits。 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { t } from '../i18n'
import { useScenarioStore } from '../stores/scenario'
import { critLabel, esc, muniLabel } from '../utils/format'

const SEARCH_LIMIT = 12

const S = useScenarioStore()
const input = ref(null)

const shown = computed(() => S.qHits.slice(0, SEARCH_LIMIT))
const open = ref(false)

function onInput(e) {
  S.setQuery(e.target.value)
  open.value = true
}

function clear() {
  S.setQuery('')
  if (input.value) {
    input.value.value = ''
    input.value.focus()
  }
}

/** 命中处高亮。按原始输入找，找不到就原样返回 —— 高亮不对不如不高亮。 */
function hl(text, raw) {
  const str = String(text == null ? '' : text)
  const query = raw.trim()
  if (!query) return esc(str)
  const i = str.toLowerCase().indexOf(query.toLowerCase())
  if (i < 0) return esc(str)
  return (
    esc(str.slice(0, i)) + '<mark>' + esc(str.slice(i, i + query.length)) + '</mark>' + esc(str.slice(i + query.length))
  )
}

/** 一行右侧那个状态标签：没参与计算 / 被筛掉 / 防线结论 / 台账严重度。 */
function tagOf(p) {
  if (!S.inScope(p)) return { text: t('search.tagOutOfScope'), color: 'var(--amber)' }
  if (S.blockedBy(p).length) return { text: t('search.tagFiltered'), color: 'rgba(255,255,255,.4)' }
  const res = S.resFor(p)
  if (res)
    return {
      text:
        // null 要先判 —— 落到 tagLine3 会印成「0 台泵」（改口径前）或把
        // 「无标定」套进「{brief} 需出动」的模板里，两种都是错的
        res.line === null
          ? t('search.tagNone')
          : res.line === 1
            ? t('search.tagLine1')
            : res.line === 2
              ? t('search.tagLine2')
              : t('search.tagLine3', { brief: S.pumpBrief(res) }),
      color: null,
    }
  return { text: critLabel(p.criticality), color: null }
}

function pick(uid) {
  open.value = false
  S.chooseHit(uid)
}

/* ---- 键盘 ---- */
function onKeydown(ev) {
  const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes((ev.target.tagName || '').toUpperCase())
  // 「/」与 ⌘K / Ctrl+K 聚焦搜索框 —— 现场报点位时手不用离开键盘
  if (
    input.value &&
    !typing &&
    !S.drawer &&
    (ev.key === '/' || ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'k'))
  ) {
    ev.preventDefault()
    input.value.focus()
    input.value.select()
    return
  }
  if (ev.target !== input.value) return

  if (ev.key === 'Escape') {
    if (S.q) clear()
    else input.value.blur()
    return
  }
  if (!S.qHits.length) return
  const last = Math.min(S.qHits.length, SEARCH_LIMIT) - 1
  if (ev.key === 'ArrowDown') {
    ev.preventDefault()
    S.qIdx = S.qIdx >= last ? 0 : S.qIdx + 1
  } else if (ev.key === 'ArrowUp') {
    ev.preventDefault()
    S.qIdx = S.qIdx <= 0 ? last : S.qIdx - 1
  } else if (ev.key === 'Enter') {
    ev.preventDefault()
    pick(S.qHits[S.qIdx].uid)
  }
}

// 点到别处收起结果，但保留输入内容 —— 免得刚搜完一看地图就得重打一遍
function onDocClick(ev) {
  if (!ev.target.closest('.search')) open.value = false
}

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  document.addEventListener('click', onDocClick, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.removeEventListener('click', onDocClick, true)
})
</script>

<template>
  <div class="search">
    <div class="sbox">
      <i class="ic" style="width: 15px; height: 15px; color: rgba(255, 255, 255, 0.5)">
        <svg viewBox="0 0 20 20">
          <circle cx="9" cy="9" r="5.5" /><line x1="13" y1="13" x2="17" y2="17" />
        </svg>
      </i>
      <input
        ref="input"
        type="search"
        autocomplete="off"
        spellcheck="false"
        :placeholder="t('search.placeholder')"
        @input="onInput"
        @focus="open = true"
      />
      <kbd v-if="!S.q">/</kbd>
      <span v-else class="x" :title="t('search.clear')" @click="clear">&times;</span>
    </div>

    <div v-if="open && S.q.trim()" class="sres">
      <div v-if="!S.points.length" class="hint">{{ t('search.loading') }}</div>
      <template v-else-if="!S.qHits.length">
        <div class="hint">
          {{ t('search.noHit', { q: S.q }) }}<br />{{ t('search.noHitHint') }}
        </div>
      </template>
      <template v-else>
        <div
          v-for="(p, i) in shown"
          :key="p.uid"
          class="r"
          :class="{ on: i === S.qIdx }"
          @click="pick(p.uid)"
        >
          <span class="n">
            <b v-html="hl(p.uid, S.q)" />
            <span class="l"> · <span v-html="hl(p.location, S.q)" /></span><br />
            <span class="l"><span v-html="hl(p.area, S.q)" /> · {{ muniLabel(p.municipality) }}</span>
          </span>
          <span class="t" :style="tagOf(p).color ? { color: tagOf(p).color } : null">{{ tagOf(p).text }}</span>
        </div>
        <div class="hint">
          <template v-if="S.qHits.length > shown.length">{{
            t('search.more', { total: S.qHits.length, shown: shown.length })
          }}</template>
          <template v-else>{{ t('search.keys', { total: S.qHits.length }) }}</template>
        </div>
      </template>
    </div>
  </div>
</template>
