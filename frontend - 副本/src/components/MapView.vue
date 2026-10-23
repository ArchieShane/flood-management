<script setup>
import L from 'leaflet'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  BASEMAPS, COVERAGE_STYLE, DISTRICT_STYLE, MECHANISM_STYLE,
  NETWORK_ORDER, NETWORK_STYLE, RADIUS, modelRadius,
} from '../constants'
import { locale } from '../i18n'
import { useScenarioStore } from '../stores/scenario'
import { popupHtml, tooltipHtml } from '../utils/mapHtml'

const S = useScenarioStore()
const el = ref(null)

let map = null
let layerGroup = null
let coverageGroup = null
let networkGroup = null
let districtGroup = null
let modelGroup = null
let baseTiles = null
let labelTiles = null
const markers = new Map()

/* ---------------- 底图 ---------------- */
function setBasemap(key) {
  const b = BASEMAPS[key]
  if (baseTiles) map.removeLayer(baseTiles)
  if (labelTiles) {
    map.removeLayer(labelTiles)
    labelTiles = null
  }
  baseTiles = L.tileLayer(b.url, { maxNativeZoom: b.maxNativeZoom, maxZoom: 19, attribution: b.attribution }).addTo(map)
  if (b.labels)
    labelTiles = L.tileLayer(b.labels, {
      maxNativeZoom: b.maxNativeZoom,
      maxZoom: 19,
      pane: 'shadowPane',
    }).addTo(map)
}

/* ---------------- 图层 ---------------- */

/** 画「有管网数据的区域」。三层从大到小叠，鼠标不拦截（点还要能点）。 */
function drawCoverage() {
  if (!coverageGroup) return
  coverageGroup.clearLayers()
  if (!S.coverage || !S.showCoverage) return
  ;(S.coverage.features || []).forEach(f => {
    const st = COVERAGE_STYLE[f.properties.key]
    if (!st) return
    L.geoJSON(f, { style: { ...st, interactive: false } }).addTo(coverageGroup)
  })
}

/** 画雨水管网。每一级在 GeoJSON 里只有一个 Feature（几何是几万段的
 *  MultiLineString），故这里最多建 4 个 Leaflet 图层——逐条建对象会卡好几秒。
 *
 *  哪一级在什么缩放下出现，由 Feature 自带的 `min_zoom` 决定（后端
 *  `network_batch.CLASSES`）。市域尺度只剩主干管，放大才逐级长出支管；
 *  支管那 3.2 MB 也是到这一级才去取。 */
function drawNetwork() {
  if (!networkGroup || !map) return
  networkGroup.clearLayers()
  if (!S.showNetwork) return
  const z = map.getZoom()
  const feats = ['mains', 'laterals']
    .map(k => S.network[k])
    .filter(fc => fc && typeof fc === 'object')
    .flatMap(fc => fc.features || [])
  // 支管自己的 min_zoom 在它自己的文件里，没取回来时读不到 —— 故干管文件
  // 一并带了 lateral_min_zoom，放大到这一级就去把那 3.2 MB 取回来。
  const mains = S.network.mains
  if (mains && typeof mains === 'object' && z >= (mains.properties?.lateral_min_zoom ?? 14))
    S.loadNetwork('laterals')
  NETWORK_ORDER.forEach(cls => {
    const f = feats.find(x => x.properties.key === cls)
    if (!f || z < f.properties.min_zoom) return
    L.geoJSON(f, { style: { ...NETWORK_STYLE[cls], interactive: false } }).addTo(networkGroup)
  })
}

/** 画当前选中片区的轮廓。只画选中的那个 —— 122 个片区全画上去只剩一团线。
 *  轮廓简化过 25 m，只用来看清筛的是哪一片；点归不归这个区以 `district_key` 为准。 */
function drawDistricts() {
  if (!districtGroup) return
  districtGroup.clearLayers()
  if (!S.districts || !S.filters.district.length) return
  ;(S.districts.features || []).forEach(f => {
    if (!S.filters.district.includes(f.properties.key)) return
    L.geoJSON(f, { style: DISTRICT_STYLE }).addTo(districtGroup)
  })
}

const helpers = () => ({ inScope: S.inScope, lineLabel: S.lineLabel, pumpBrief: S.pumpBrief })

/** 重建地图上的点。845 个 circleMarker 走 canvas 渲染，缩放不卡。
 *  两套点共用这一层：颜色与半径由 store 的 `colorFor` 决定（台账按严重度、
 *  片区按成因，跑完批算后两边统一按三道防线）。 */
function drawMarkers() {
  if (!layerGroup) return
  layerGroup.clearLayers()
  markers.clear()
  S.filtered.forEach(p => {
    const res = S.resFor(p)
    const sel = S.sel === p.uid
    const out = !S.inScope(p) // 数据区外：空心灰圈，一眼看出没参与计算
    // 台账点按上报严重度定大小；片区没有严重度，按演算积水量定
    const base =
      p.cluster_rank != null ? modelRadius(p.ponding_net_inflow_m3 || 0) : RADIUS[p.criticality] || 4
    const m = L.circleMarker([p.lat, p.lon], {
      radius: base + (sel ? 3 : 0),
      color: sel ? '#fff' : out ? 'rgba(255,255,255,.5)' : 'rgba(0,0,0,.55)',
      weight: sel ? 2 : 1,
      dashArray: out ? '2 2' : null,
      fillColor: S.colorFor(p, res),
      fillOpacity: out ? 0 : 0.9,
    })
    m.bindTooltip(tooltipHtml(p, res, helpers()), { direction: 'top', offset: [0, -6] })
    m.on('click', () => S.select(p.uid, false))
    m.addTo(layerGroup)
    markers.set(p.uid, m)
  })
}

/** 画模型识别出的易积水片区的**面**。代表点不在这里画 —— 两套点共用
 *  `drawMarkers()` 那一层，故片区的点与台账点一样能选中、能算、能按防线上色。
 *
 *  107 个片区合计 1,378 个 20 m 方格（未融合），全部建成 Leaflet 对象会慢，
 *  故一个片区只建一个 geoJSON 图层（它的 MultiPolygon 整个交给 Leaflet），
 *  面本身不接鼠标 —— 点击落在上面那层的点上，与管网/覆盖面同一个做法。 */
function drawModel() {
  if (!modelGroup) return
  modelGroup.clearLayers()
  if (S.source !== 'model' || !S.model) return
  const selRank = S.modelSelFeature ? S.modelSelFeature.properties.rank : null
  S.modelFeatures.forEach(f => {
    const p = f.properties
    const on = selRank === p.rank
    L.geoJSON(f, {
      style: { ...MECHANISM_STYLE(p.mechanism_key), ...(on ? { weight: 2, color: '#fff', opacity: 1 } : {}) },
    }).addTo(modelGroup)
  })
}

/* ---------------- 视野 ---------------- */

/** 右侧两条侧栏盖着地图，算可视范围时要把它们让出来。 */
const rightInset = () => {
  const wide = window.innerWidth >= 1560
  return (S.panel ? 420 : 0) + (S.brief && wide ? 420 : 0)
}

/** 全图。两套点各看各的范围 —— 模型那 107 个片区只在 Al Bateen 一个区里，
 *  按台账那 845 个点的包络去缩会把它缩成一个看不清的小点，故放宽 maxZoom。 */
function fitToPoints() {
  if (!map) return
  const pts = S.filtered.map(p => [p.lat, p.lon])
  if (!pts.length) return
  map.fitBounds(L.latLngBounds(pts), {
    paddingTopLeft: [window.innerWidth > 820 ? 340 : 30, 60],
    paddingBottomRight: [rightInset() + 40, 60],
    maxZoom: S.source === 'model' ? 15 : 12,
  })
}

/** 把一个经纬度挪到「中间那条真正看得见的带子」上 —— 左边 KPI 栏、右边侧栏
 *  都盖着地图，居中到窗口中点等于藏到侧栏底下。 */
function centreOn(lat, lon, minZoom) {
  if (!map) return
  map.setView([lat, lon], Math.max(map.getZoom(), minZoom))
  const W = window.innerWidth
  const right = rightInset()
  const left = W > 820 ? 336 : 0
  const shift = W / 2 - (left + (W - right)) / 2
  if (Math.abs(shift) > 8) map.panBy([shift, 0], { animate: false })
}

function focusPoint(uid) {
  const p = S.byUid.get(uid)
  // 片区小（多数不到 1 ha），16 级才看得出形状；台账点 13 级就够
  if (p) centreOn(p.lat, p.lon, S.source === 'model' ? 16 : 13)
}

function openPopup(uid) {
  const m = markers.get(uid)
  const p = S.byUid.get(uid)
  if (!m || !p) return
  const html = popupHtml(p, S.resFor(p), helpers())
  if (m.getPopup()) m.setPopupContent(html)
  else m.bindPopup(html, { closeButton: true, autoPan: false })
  m.openPopup()
}

/* ---------------- 生命周期 ---------------- */
onMounted(() => {
  map = L.map(el.value, { zoomControl: false, preferCanvas: true, minZoom: 5, maxZoom: 19 }).setView(
    [24.2, 54.4],
    8,
  )
  // 覆盖面必须在点下面：先加它，再加片区轮廓，最后加 layerGroup。
  coverageGroup = L.layerGroup().addTo(map)
  networkGroup = L.layerGroup().addTo(map)
  districtGroup = L.layerGroup().addTo(map)
  modelGroup = L.layerGroup().addTo(map)
  layerGroup = L.layerGroup().addTo(map)
  setBasemap(S.basemap)
  drawCoverage()
  drawNetwork()
  drawDistricts()
  drawModel()
  drawMarkers()
  map.on('zoomend', drawNetwork)
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  if (map) map.remove()
  map = null
})

function onResize() {
  if (map) map.invalidateSize({ pan: false })
}

/* 任何影响画法的状态变了就重画 —— 点的颜色跟着计算结果走。 */
watch(
  () => [S.filtered, S.sel, S.mode, S.result, S.curve, S.curveRp, S.inputs.coverageOnly, S.source],
  () => drawMarkers(),
  { deep: false },
)
watch(() => [S.source, S.model, S.modelFeatures, S.sel], () => drawModel(), { deep: false })
/* tooltip / popup 是 HTML 串，不是 Vue 组件，语言变了不会自己重绘 —— 整批重建。
   已打开的 popup 由 store 的 refetchLocalised() 再发一条 popup 指令补上。 */
watch(locale, () => {
  drawMarkers()
  drawModel()
})
watch(() => [S.coverage, S.showCoverage], drawCoverage)
watch(() => [S.network.mains, S.network.laterals, S.showNetwork], drawNetwork)
watch(() => [S.districts, S.filters.district.slice()], drawDistricts)
watch(() => S.basemap, setBasemap)

// 侧栏开合会改变地图可视宽度，动画走完再让 Leaflet 重算尺寸
watch(
  () => [S.panel, S.brief],
  () => setTimeout(onResize, 210),
)

/** store 发来的地图指令。store 不碰 Leaflet 实例，只发指令；
 *  这个 watch 建得比上面几个晚，故排空队列时 drawMarkers 已经跑过，
 *  openPopup 一定找得到 marker。 */
watch(
  () => S.mapQueue,
  q => {
    if (!q.length || !map) return
    S.drainMapQueue().forEach(req => {
      if (req.type === 'fit') fitToPoints()
      else if (req.type === 'focus') focusPoint(req.payload)
      else if (req.type === 'popup') openPopup(req.payload)
      else if (req.type === 'zoomIn') map.zoomIn()
      else if (req.type === 'zoomOut') map.zoomOut()
    })
  },
)
</script>

<template>
  <div id="map" ref="el" />
</template>
