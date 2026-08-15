<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import api, { type ScriptCard } from '../api'
import BookShelf from '../components/BookShelf.vue'
import ScriptDetailModal from '../components/ScriptDetailModal.vue'
import { toast } from '../utils/toast'

const router = useRouter()
const scripts = ref<ScriptCard[]>([])
const loading = ref(true)
const error = ref('')
const detailShow = ref(false)
const detailId = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    scripts.value = await api.getHistoryScripts()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}
onMounted(load)

function openScript(s: ScriptCard) {
  detailId.value = s.id
  detailShow.value = true
}
function play(id: string) {
  detailShow.value = false
  router.push(`/script/${id}/select`)
}
function added() {
  toast('已加入本地剧本库', 'success')
  load()
}
</script>

<template>
  <section class="page anim-fade">
    <header class="page-head">
      <h2 class="h2">历史游玩剧本库</h2>
      <p class="muted">最近游玩过的剧本 · 记录保留 7 天，可加回本地库</p>
    </header>

    <div v-if="loading" class="skeleton-grid">
      <div v-for="i in 6" :key="i" class="skeleton" style="height: 176px"></div>
    </div>
    <div v-else-if="error" class="error">
      <p class="muted">{{ error }}</p>
      <button class="btn btn-sm" @click="load">重试</button>
    </div>
    <BookShelf
      v-else
      :scripts="scripts"
      empty-text="还没有游玩记录，去玩一局吧"
      @open="openScript"
    />

    <ScriptDetailModal
      :show="detailShow"
      :script-id="detailId"
      can-add-to-local
      @close="detailShow = false"
      @play="play"
      @added="added"
    />
  </section>
</template>

<style scoped>
.page-head {
  margin-bottom: 26px;
}
.page-head p {
  margin: 6px 0 0;
  font-size: 13px;
}
.skeleton-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(148px, 1fr));
  gap: 30px 26px;
}
.error {
  text-align: center;
  padding: 80px 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
}
</style>
