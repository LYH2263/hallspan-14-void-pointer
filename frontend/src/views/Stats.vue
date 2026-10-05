<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const s = ref<any>({})
onMounted(async () => { s.value = await api('/seating/stats?hall_id=1') })
</script>
<template>
  <h1>统计</h1>
  <p class="sub">排座占用与违规汇总 · 只反映当前有效方案</p>
  <p class="muted" v-if="s.plan_id == null">当前无有效方案，统计页为空（与排座图、违规三口同时为空）。</p>
  <p class="muted" v-else>当前有效方案 #{{ s.plan_id }}</p>
  <div class="card" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem">
    <div><div class="muted">已排座</div><div class="stat">{{ s.seated ?? 0 }}</div></div>
    <div><div class="muted">未排上</div><div class="stat">{{ s.unplaced ?? 0 }}</div></div>
    <div><div class="muted">违规数</div><div class="stat">{{ s.violations ?? 0 }}</div></div>
    <div><div class="muted">座位容量</div><div class="stat">{{ s.capacity ?? 0 }}</div></div>
  </div>
</template>
