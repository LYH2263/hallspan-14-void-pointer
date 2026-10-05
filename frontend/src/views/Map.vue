<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

const data = ref<any>(null)
const candidates = ref<any[]>([])
const violKeys = ref<Set<string>>(new Set())
const selected = ref<number[]>([])
const busy = ref(false)
const notice = ref('')
const errorMsg = ref('')

function errText(e: unknown): string {
  const raw = (e as Error)?.message ?? String(e)
  try { return JSON.parse(raw).detail ?? raw } catch { return raw }
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

// 挂载与每次操作后：只读「当前有效指针」，绝不自动生成新方案
async function loadLatest() {
  data.value = await api('/seating/latest?hall_id=1')
  selected.value = []
  await refreshViolations()
}

// 显式动作：生成一张全新方案并把指针切到它
async function run() {
  busy.value = true; errorMsg.value = ''; notice.value = ''
  try {
    const plan = await api('/seating/run?hall_id=1', { method: 'POST' })
    data.value = plan
    selected.value = []
    await refreshViolations()
    notice.value = `已生成新方案 #${plan.id} 并设为当前方案`
  } catch (e) { errorMsg.value = errText(e) } finally { busy.value = false }
}

// 作废当前方案：只切指针（回上一张有效方案，或三口同时为空），不重排
async function voidCurrent() {
  if (!data.value || data.value.empty) return
  if (!window.confirm(`确认作废当前方案 #${data.value.id}？作废后仅切回上一张有效方案，不会自动重排。`)) return
  busy.value = true; errorMsg.value = ''; notice.value = ''
  try {
    const res = await api('/seating/void?hall_id=1', {
      method: 'POST', body: JSON.stringify({}),
    })
    data.value = res.plan
    selected.value = []
    await refreshViolations()
    notice.value = res.plan.empty
      ? `方案 #${res.voided_id} 已作废，已无任何有效方案（排座图 / 违规 / 统计同时为空）`
      : `方案 #${res.voided_id} 已作废，当前切回方案 #${res.active_plan_id}`
  } catch (e) { errorMsg.value = errText(e) } finally { busy.value = false }
}

// 点两张有人课桌即对调；已作废方案由后端按 plan_id 拒绝
function onCell(cell: any) {
  if (!data.value || data.value.empty || cell.empty || busy.value) return
  const id = cell.candidate_id ?? cell.id
  if (id == null) return
  const i = selected.value.indexOf(id)
  if (i >= 0) { selected.value.splice(i, 1); return }
  selected.value.push(id)
  if (selected.value.length === 2) void doSwap()
}

async function doSwap() {
  const [a, b] = selected.value
  busy.value = true; errorMsg.value = ''
  try {
    const plan = await api('/seating/swap?hall_id=1', {
      method: 'POST',
      body: JSON.stringify({ a_id: a, b_id: b, plan_id: data.value.id }),
    })
    data.value = plan
    notice.value = `方案 #${plan.id} 内座位已对调（考生 ${a} ↔ ${b}）`
    await refreshViolations()
  } catch (e) {
    errorMsg.value = errText(e)
    await loadLatest() // 被拒绝（方案已作废）时，立刻回到服务端指针所指方案
  } finally {
    selected.value = []
    busy.value = false
  }
}

onMounted(async () => {
  try {
    candidates.value = await api('/candidates')
    await loadLatest()
  } catch (e) { errorMsg.value = errText(e) }
})

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
  const id = cell.candidate_id ?? cell.id
  return id != null && selected.value.includes(id)
}
function paperClass(pid: number) { return pid % 2 === 0 ? 'b' : 'a' }
</script>

<template>
  <h1>考场课桌网格</h1>
  <p class="sub">课桌网格为主视图 · 左侧考生名册夹板 · 违规课桌高亮 · 点两张课桌对调</p>

  <div class="toolbar">
    <button class="btn" :disabled="busy" @click="run">重新排座（生成新方案）</button>
    <button class="btn btn-danger" :disabled="busy || !data || data.empty" @click="voidCurrent">
      作废当前方案
    </button>
    <span v-if="data && !data.empty" class="badge">当前方案 #{{ data.id }}</span>
    <span v-else-if="data" class="badge badge-empty">无有效方案</span>
  </div>

  <p v-if="notice" class="notice">{{ notice }}</p>
  <p v-if="errorMsg" class="notice notice-err">{{ errorMsg }}</p>
  <p v-if="data && data.empty" class="notice notice-empty">
    当前没有有效方案（已全部作废）：排座图、违规、统计同时为空。作废不会自动重排，需要时点「重新排座」。
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
          :class="{
            empty: cell.empty,
            'hs-viol': isViol(cell),
            'hs-pick': isSelected(cell),
          }"
          @click="onCell(cell)"
        >
          <template v-if="!cell.empty">
            <span class="hs-paper-tag" :class="paperClass(cell.paper_id)">卷{{ cell.paper_id }}</span>
            <div>{{ cell.name }}</div>
          </template>
          <template v-else>·</template>
        </div>
      </div>
      <p class="hint">点击两张有人课桌进行对调；对调只写入当前方案，已作废方案会被拒绝。</p>
    </div>
  </div>
</template>

<style scoped>
.toolbar { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; }
.btn { padding: .45rem .9rem; border: 1px solid #888; border-radius: 6px; background: #fff; cursor: pointer; }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.btn-danger { border-color: #c0392b; color: #c0392b; }
.badge { font-size: .85rem; padding: .15rem .55rem; border-radius: 999px; background: #eef5ff; color: #1d5fb8; }
.badge-empty { background: #f4f4f4; color: #777; }
.notice { margin: .6rem 0 0; padding: .5rem .7rem; border-radius: 6px; background: #eefaf0; color: #1d7a36; font-size: .9rem; }
.notice-err { background: #fdecea; color: #b3261e; }
.notice-empty { background: #fff7e6; color: #9a6200; }
.hint { color: #888; font-size: .82rem; margin-top: .5rem; }
.hs-classroom { display: flex; gap: 1rem; align-items: flex-start; }
.hs-clipboard { min-width: 200px; border: 1px solid #ddd; border-radius: 8px; padding: .7rem; background: #fafafa; }
.hs-clipboard h2 { font-size: 1rem; margin: 0 0 .5rem; }
.hs-roster-row { display: flex; justify-content: space-between; padding: .3rem 0; border-bottom: 1px dashed #e2e2e2; font-size: .88rem; }
.hs-ticket { color: #999; font-size: .75rem; }
.hs-grid-board { display: grid; gap: 6px; }
.hs-desk {
  width: 72px; height: 56px; border: 1px solid #b9c6d6; border-radius: 6px;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  font-size: .78rem; background: #fff; cursor: pointer; position: relative; user-select: none;
}
.hs-desk.empty { background: #f7f8fa; color: #c4cbd4; cursor: default; }
.hs-desk.hs-viol { border-color: #e04b3b; background: #fdecea; }
.hs-desk.hs-pick { outline: 3px solid #1d5fb8; border-color: #1d5fb8; }
.hs-paper-tag { position: absolute; top: 2px; left: 4px; font-size: .65rem; padding: 0 4px; border-radius: 4px; }
.hs-paper-tag.a { background: #e7f0ff; color: #1d5fb8; }
.hs-paper-tag.b { background: #fff0e6; color: #c05a1d; }
</style>
