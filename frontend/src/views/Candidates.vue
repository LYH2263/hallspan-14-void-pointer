<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
onMounted(async () => { rows.value = await api('/candidates') })
</script>
<template>
  <h1>考生名册</h1>
  <p class="sub">参加本场考试的考生与试卷套分配 · 作废排座不会改动本名单</p>
  <div class="card">
    <table>
      <thead><tr><th>考号</th><th>姓名</th><th>考室</th><th>试卷套</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>{{ r.ticket_no }}</td><td>{{ r.name }}</td><td>{{ r.hall_id }}</td><td>卷{{ r.paper_id }}</td>
        </tr>
      </tbody>
    </table>
    <p v-if="!rows.length" class="muted">暂无考生</p>
  </div>
</template>
