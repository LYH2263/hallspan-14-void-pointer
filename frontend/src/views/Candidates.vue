<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
onMounted(async () => { rows.value = await api('/candidates') })
</script>
<template>
  <h1>考生名册</h1>
  <p class="sub">排座与作废都不会改动本名单</p>
  <div class="card">
    <table>
      <thead><tr><th>ID</th><th>姓名</th><th>准考证号</th><th>试卷套</th><th>考室</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>{{ r.id }}</td><td>{{ r.name }}</td><td>{{ r.ticket_no }}</td>
          <td>卷{{ r.paper_id }}</td><td>{{ r.hall_id }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
