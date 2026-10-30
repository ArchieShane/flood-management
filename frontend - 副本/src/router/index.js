import { createRouter, createWebHistory } from 'vue-router'

import { t } from '../i18n'

// 两个页面就是原来后端那两个路由：/ 指挥中心、/calculator 单点快算。
// 路径保持不变，旧书签不会失效。/simulations 起是仿真任务（列表 + 新建向导）。
const routes = [
  {
    path: '/',
    name: 'command-centre',
    component: () => import('../views/CommandCentre.vue'),
    meta: { titleKey: 'app.commandCentre' },
  },
  {
    path: '/calculator',
    name: 'calculator',
    component: () => import('../views/CalculatorView.vue'),
    meta: { titleKey: 'app.calculator' },
  },
  {
    path: '/simulations',
    name: 'simulations',
    component: () => import('../views/SimulationHome.vue'),
    meta: { titleKey: 'sim.title' },
  },
  {
    path: '/simulations/new',
    name: 'simulation-new',
    component: () => import('../views/SimulationWizard.vue'),
    meta: { titleKey: 'sim.wizard.title' },
  },
  {
    path: '/simulations/:id(\\d+)/edit',
    name: 'simulation-edit',
    component: () => import('../views/SimulationWizard.vue'),
    props: true,
    meta: { titleKey: 'sim.wizard.title' },
  },
  {
    path: '/simulations/:id(\\d+)',
    name: 'simulation-detail',
    component: () => import('../views/SimulationDetail.vue'),
    props: true,
    meta: { titleKey: 'sim.title' },
  },
  {
    path: '/rda',
    name: 'rda',
    component: () => import('../views/RdaView.vue'),
    meta: { title: 'RD-A 全套成果' },
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({ history: createWebHistory(), routes })

// 标题跟着语言走：切换时 TopMenu / CalculatorView 会再设一次
router.afterEach(to => {
  if (to.meta.titleKey) document.title = t(to.meta.titleKey)
  else if (to.meta.title) document.title = to.meta.title
})

export default router
