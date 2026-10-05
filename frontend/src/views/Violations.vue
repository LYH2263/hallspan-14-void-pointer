<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const viols = ref<any[]>([])
const unplaced = ref<any[]>([])
const isEmpty = ref(false)
const planId = ref<number | null>(null)
onMounted(async () => {
  const res = await api('/seating/violations?hall_id=1')
  viols.value = res.violations; unplaced.value = res.unplaced
  isEmpty.value = !!res.empty; planId.value = res.active_plan_id ?? null
})
</script>
<template>
  <h1>违规</h1>
  <p class="sub">间距不足或同试卷四邻相邻</p>
  <p v-if="isEmpty" class="muted" style="background:#fff7e6;padding:.6rem .8rem;border-radius:6px;color:#9a6200">
    当前没有有效方案（方案已全部作废），违规页为空——作废不会自动重排。
  </p>
  <div class="card" v-else>
    <table>
      <thead><tr><th>类型</th><th>考生A</th><th>考生B</th><th>说明</th></tr></thead>
      <tbody>
        <tr v-for="(v,i) in viols" :key="i">
          <td>{{ v.kind }}</td><td>{{ v.a_id }}</td><td>{{ v.b_id }}</td><td>{{ v.detail }}</td>
        </tr>
      </tbody>
    </table>
    <p v-if="!viols.length" class="muted">无违规</p>
  </div>
  <div class="card" v-if="unplaced.length">
    <h3>未排上</h3>
    <div v-for="u in unplaced" :key="u.id">{{ u.name }}（{{ u.ticket_no }}）</div>
  </div>
</template>
