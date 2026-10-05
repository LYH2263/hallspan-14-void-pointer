<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const viols = ref<any[]>([])
const unplaced = ref<any[]>([])
const planId = ref<number | null>(null)
onMounted(async () => {
  const res = await api('/seating/violations?hall_id=1')
  viols.value = res.violations; unplaced.value = res.unplaced; planId.value = res.plan_id
})
</script>
<template>
  <h1>违规</h1>
  <p class="sub">间距不足或同试卷四邻相邻 · 只反映当前有效方案</p>
  <div class="card" v-if="planId == null">
    <p class="muted">当前无有效方案，违规页为空（与排座图、统计三口同时为空）。</p>
  </div>
  <template v-else>
    <p class="muted">当前有效方案 #{{ planId }}</p>
    <div class="card">
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
</template>
