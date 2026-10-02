<script setup>
/* 仿真首页（Figma：FM demo / 00 Simulation / Run library）。
   只保留 Run history 表格（KPI 四卡与同场雨对比 / 任务队列 / New results 三栏已删）。
   数据：/api/simulations（表格，随标签重取）。 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { deleteSimulation, fetchSimulationOptions, fetchSimulations, openSimulation } from '../api'
import RunHistory from '../components/sim/RunHistory.vue'
import SimShell from '../components/sim/SimShell.vue'
import { useSimUser } from '../composables/useSimUser'
import { locale, t } from '../i18n'
import { useToastStore } from '../stores/toast'
import { stormLabel } from '../utils/sim'

const router = useRouter()
const toast = useToastStore()
const { user } = useSimUser()

const history = ref(null)
const users = ref([])
const tab = ref('all')
// 任务列表分页（页号从 0 起）；行数据固定英文，见 RunHistory.vue
const PAGE_SIZE = 10
const page = ref(0)
const loading = ref(false)

async function loadHistory() {
  loading.value = true
  try {
    const res = await fetchSimulations({
      tab: tab.value, user: user.value, limit: PAGE_SIZE, offset: page.value * PAGE_SIZE, lang: 'en',
    })
    // 删掉末页最后一条后当前页可能越界，退回最后一页再取
    const last = Math.max(0, Math.ceil(res.total / PAGE_SIZE) - 1)
    if (page.value > last) {
      page.value = last
      return loadHistory()
    }
    history.value = res
  } finally {
    loading.value = false
  }
}

async function loadAll() {
  try {
    await loadHistory()
  } catch (e) {
    toast.show(t('sim.history.loadFailed', { msg: e.message }), 'var(--red)')
  }
}

onMounted(async () => {
  loadAll()
  fetchSimulationOptions().then(o => (users.value = o.users)).catch(() => {})
})
// 运行中任务的进度靠轮询刷新；一分钟一次足够，页面隐藏时浏览器会自行降频
const timer = setInterval(loadAll, 60e3)
onBeforeUnmount(() => clearInterval(timer))

watch([tab, user], () => {
  if (page.value) page.value = 0   // 换页号会触发下面的 watch 去取
  else loadHistory()
})
watch(page, loadHistory)
// 防线名等后端文案随语言走，切语言要重取
watch(locale, loadAll)

async function open(run) {
  if (run.status === 'draft') return router.push(`/simulations/${run.id}/edit`)
  if (run.status === 'done' && !run.opened_at) await openSimulation(run.id).catch(() => {})
  router.push(`/simulations/${run.id}`)
}

async function remove(run) {
  if (!window.confirm(t('sim.history.confirmDelete', { rain: stormLabel(run) }))) return
  try {
    await deleteSimulation(run.id)
    toast.show(t('sim.history.deleted'))
  } catch (e) {
    toast.show(t('sim.history.deleteFailed', { msg: e.message }), 'var(--red)')
  }
  loadAll()
}
</script>

<template>
  <SimShell :users="users">
    <h1 class="sim-h1">{{ t('sim.title') }}</h1>

    <RunHistory
      :tab="tab"
      :data="history"
      :loading="loading"
      :page="page"
      :page-size="PAGE_SIZE"
      @tab="tab = $event"
      @page="page = $event"
      @open="open"
      @delete="remove"
      @new="router.push('/simulations/new')"
    />
  </SimShell>
</template>
