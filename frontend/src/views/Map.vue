<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
const data = ref<any>(null)
const candidates = ref<any[]>([])
const violKeys = ref<Set<string>>(new Set())
const selected = ref<number | null>(null)
const msg = ref('')
const busy = ref(false)

function errText(e: any) {
  try { return JSON.parse(e.message).detail || e.message } catch { return e.message }
}
async function refreshViolations() {
  try {
    const v = await api('/seating/violations?hall_id=1')
    const keys = new Set<string>()
    for (const x of v.violations || []) {
      if (x.a_id != null) keys.add(String(x.a_id))
      if (x.b_id != null) keys.add(String(x.b_id))
    }
    violKeys.value = keys
  } catch { violKeys.value = new Set() }
}
async function load() {
  // 只读当前有效指针；无有效方案时返回空壳，绝不借读取自动生成
  data.value = await api('/seating/latest?hall_id=1')
  selected.value = null
  await refreshViolations()
}
async function run() {
  busy.value = true; msg.value = ''
  try {
    await api('/seating/run?hall_id=1', { method: 'POST' })
    await load()
  } catch (e: any) { msg.value = '排座失败：' + errText(e) } finally { busy.value = false }
}
async function voidCurrent() {
  if (!hasPlan.value || busy.value) return
  if (!confirm('确认作废当前方案？作废后图/违规/统计将切回上一张有效方案，或三口同时为空，不会自动重排。')) return
  busy.value = true; msg.value = ''
  try {
    const res = await api(`/seating/${data.value.id}/void?hall_id=1`, { method: 'POST' })
    data.value = res.current  // 切指针：上一张有效方案，或空壳
    selected.value = null
    await refreshViolations()
  } catch (e: any) { msg.value = '作废失败，状态未改变：' + errText(e) } finally { busy.value = false }
}
async function clickDesk(cell: any) {
  if (cell.empty || !hasPlan.value || busy.value) return
  const cid = cell.candidate_id
  if (selected.value === null) { selected.value = cid; return }
  if (selected.value === cid) { selected.value = null; return }
  const a = selected.value
  selected.value = null
  busy.value = true; msg.value = ''
  try {
    data.value = await api('/seating/swap', {
      method: 'POST',
      body: JSON.stringify({ a_id: a, b_id: cid, hall_id: 1, plan_id: data.value.id }),
    })
    await refreshViolations()
  } catch (e: any) { msg.value = '调座被拒绝：' + errText(e); await load() }
  finally { busy.value = false }
}
onMounted(async () => {
  candidates.value = await api('/candidates')
  await load()
})
const hasPlan = computed(() => !!(data.value && data.value.id))
const planLabel = computed(() => hasPlan.value ? `当前有效方案 #${data.value.id}` : '当前无有效方案')
const gridStyle = computed(() => data.value ? ({ gridTemplateColumns: `repeat(${data.value.cols}, 72px)` }) : {})
const cells = computed(() => {
  if (!data.value) return []
  const map = new Map<string, any>()
  for (const a of data.value.assignments || []) map.set(a.row + ',' + a.col, a)
  const out: any[] = []
  for (let r = 0; r < data.value.rows; r++) {
    for (let c = 0; c < data.value.cols; c++) {
      out.push(map.get(r + ',' + c) || { empty: true, row: r, col: c })
    }
  }
  return out
})
function isViol(cell: any) {
  if (cell.empty) return false
  const id = cell.candidate_id ?? cell.id
  return id != null && violKeys.value.has(String(id))
}
function isSelected(cell: any) {
  return !cell.empty && selected.value === cell.candidate_id
}
function paperClass(pid: number) {
  return pid % 2 === 0 ? 'b' : 'a'
}
</script>
<template>
  <h1>考场课桌网格</h1>
  <p class="sub">课桌网格为主视图 · 左侧考生名册夹板 · 违规课桌高亮 · 点两张课桌对调</p>
  <div class="hs-toolbar">
    <button class="btn" :disabled="busy" @click="run">重新排座</button>
    <button class="btn btn-danger" :disabled="busy || !hasPlan" @click="voidCurrent">作废当前方案</button>
    <span class="muted">{{ planLabel }}</span>
  </div>
  <p v-if="msg" class="hs-msg">{{ msg }}</p>
  <p v-if="!hasPlan" class="card hs-empty">
    当前没有有效方案，排座图 / 违规 / 统计三口同时为空。点击「重新排座」生成一张新方案。
  </p>
  <div class="hs-classroom" style="margin-top:0.85rem">
    <aside class="hs-clipboard">
      <h2>考生名册</h2>
      <div v-for="c in candidates" :key="c.id" class="hs-roster-row">
        <div>
          <div>{{ c.name }}</div>
          <div class="hs-ticket">{{ c.ticket_no }}</div>
        </div>
        <div>卷{{ c.paper_id }}</div>
      </div>
    </aside>
    <div class="hs-desk-stage" v-if="data">
      <div class="hs-grid-board" :style="gridStyle">
        <div
          v-for="(cell,i) in cells" :key="i"
          class="hs-desk"
          :class="{ empty: cell.empty, 'hs-viol': isViol(cell), 'hs-selected': isSelected(cell), clickable: hasPlan && !cell.empty }"
          @click="clickDesk(cell)"
        >
          <template v-if="!cell.empty">
            <span class="hs-paper-tag" :class="paperClass(cell.paper_id)">卷{{ cell.paper_id }}</span>
            <div>{{ cell.name }}</div>
          </template>
          <template v-else>·</template>
        </div>
      </div>
    </div>
  </div>
</template>
