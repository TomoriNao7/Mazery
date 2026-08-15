<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api, { type CharL1, type CharL2 } from '../api'
import AppModal from '../components/AppModal.vue'
import { toast } from '../utils/toast'

const route = useRoute()
const router = useRouter()
const scriptId = route.params.id as string

const loading = ref(true)
const error = ref('')
const title = ref('')
const characters = ref<CharL1[]>([])

const detailShow = ref(false)
const detail = ref<CharL2 | null>(null)
const detailLoading = ref(false)
const selectedId = ref('')
const starting = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await api.getScriptCharacters(scriptId)
    title.value = res.title
    characters.value = res.characters
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function pick(c: CharL1) {
  selectedId.value = c.id
  detailShow.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await api.getCharacterDetail(scriptId, c.id)
  } catch (e) {
    toast((e as Error).message, 'error')
  } finally {
    detailLoading.value = false
  }
}

async function start() {
  if (!selectedId.value) return
  starting.value = true
  try {
    const res = await api.startGame(scriptId, selectedId.value)
    detailShow.value = false
    router.push(`/game/${res.game_id}`)
  } catch (e) {
    toast((e as Error).message, 'error')
  } finally {
    starting.value = false
  }
}

function describe(v: unknown): string {
  if (v == null) return '未知'
  if (typeof v === 'string') return v
  if (typeof v === 'object') {
    const parts = Object.entries(v as Record<string, unknown>).map(([k, val]) =>
      typeof val === 'string' || typeof val === 'number' ? `${k}: ${val}` : k,
    )
    return parts.join('；')
  }
  return String(v)
}
</script>

<template>
  <section class="page anim-fade">
    <header class="page-head">
      <button class="back-btn" @click="router.back()">← 返回</button>
      <h2 class="h2">{{ title }}</h2>
      <p class="muted">选择你要扮演的角色</p>
    </header>

    <div v-if="loading" class="char-grid">
      <div v-for="i in 4" :key="i" class="skeleton" style="height: 130px"></div>
    </div>
    <div v-else-if="error" class="error">
      <p class="muted">{{ error }}</p>
      <button class="btn btn-sm" @click="load">重试</button>
    </div>
    <div v-else class="char-grid">
      <button
        v-for="(c, i) in characters"
        :key="c.id"
        class="char-card card card-hover"
        :style="{ animationDelay: i * 60 + 'ms' }"
        @click="pick(c)"
      >
        <div class="char-avatar">{{ (c.name || '?').slice(0, 1) }}</div>
        <div class="char-name display">{{ c.name }}</div>
        <div class="char-meta muted">
          <span v-if="c.age">{{ c.age }}岁</span>
          <span v-if="c.gender">{{ c.gender }}</span>
          <span v-if="c.profession">· {{ c.profession }}</span>
        </div>
        <div class="char-person dim">{{ c.personality || '' }}</div>
      </button>
    </div>

    <AppModal :show="detailShow" width="480px" @close="detailShow = false">
      <div v-if="detailLoading" class="p20">
        <div class="skeleton" style="height: 20px; width: 50%"></div>
        <div class="skeleton" style="height: 13px; width: 100%; margin-top: 16px"></div>
        <div class="skeleton" style="height: 13px; width: 90%; margin-top: 8px"></div>
      </div>
      <div v-else-if="detail" class="char-detail">
        <div class="cd-head">
          <div class="cd-avatar">{{ (detail.name || '?').slice(0, 1) }}</div>
          <div>
            <div class="cd-name display gold">{{ detail.name }}</div>
            <div class="cd-identity muted">{{ detail.identity || '身份未知' }}</div>
          </div>
        </div>

        <div v-if="detail.appearance" class="cd-block">
          <div class="cd-label dim">外貌</div>
          <p class="cd-text">{{ detail.appearance }}</p>
        </div>
        <div v-if="detail.background" class="cd-block">
          <div class="cd-label dim">身份背景</div>
          <p class="cd-text">{{ detail.background }}</p>
        </div>

        <div v-if="detail.relationships?.length" class="cd-block">
          <div class="cd-label dim">人物关系</div>
          <ul class="cd-rels">
            <li v-for="(r, i) in detail.relationships" :key="i" class="cd-text">
              <span class="gold">{{ (r as any).name || (r as any).target || '他人' }}</span>
              <span v-if="(r as any).relation">（{{ (r as any).relation }}）</span>
              <span v-if="(r as any).description">：{{ (r as any).description }}</span>
            </li>
          </ul>
        </div>

        <div class="cd-block">
          <div class="cd-label dim">当前目标</div>
          <p class="cd-text">{{ describe(detail.goal) }}</p>
        </div>
        <div class="cd-block">
          <div class="cd-label dim">需要隐藏的部分</div>
          <ul class="cd-rels">
            <li v-for="(s, i) in detail.secrets" :key="i" class="cd-text">{{ describe(s) }}</li>
          </ul>
        </div>

        <div class="cd-actions">
          <button class="btn btn-ghost" @click="detailShow = false">再看看</button>
          <button class="btn btn-primary" :disabled="starting" @click="start">
            {{ starting ? '进入中…' : '继续 · 以该角色开始游戏' }}
          </button>
        </div>
      </div>
    </AppModal>
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
.back-btn {
  background: none;
  border: none;
  color: var(--text-2);
  cursor: pointer;
  font-size: 13px;
  margin-bottom: 12px;
  padding: 0;
}
.back-btn:hover {
  color: var(--accent-strong);
}
.char-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 18px;
}
.char-card {
  padding: 20px;
  text-align: center;
  border: none;
  color: var(--text);
  cursor: pointer;
  animation: fadeUp 0.5s var(--ease) both;
  background: var(--surface);
}
.char-avatar {
  width: 54px;
  height: 54px;
  margin: 0 auto 12px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 24px;
  color: var(--accent-strong);
  background: radial-gradient(circle at 30% 25%, var(--surface-3), var(--surface-2));
  border: 1px solid var(--border);
}
.char-name {
  font-size: 17px;
}
.char-meta {
  font-size: 12px;
  margin-top: 6px;
  display: flex;
  gap: 6px;
  justify-content: center;
}
.char-person {
  font-size: 12px;
  margin-top: 8px;
  min-height: 16px;
}
.error {
  text-align: center;
  padding: 80px 0;
}
.p20 {
  padding: 10px 0;
}
.char-detail {
  padding: 4px 0;
}
.cd-head {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 18px;
}
.cd-avatar {
  width: 60px;
  height: 60px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 26px;
  color: var(--accent-strong);
  background: radial-gradient(circle at 30% 25%, var(--surface-3), var(--surface-2));
  border: 1px solid var(--border-strong);
}
.cd-name {
  font-size: 22px;
}
.cd-identity {
  font-size: 13px;
  margin-top: 2px;
}
.cd-block {
  margin-top: 14px;
}
.cd-label {
  font-size: 11px;
  letter-spacing: 0.2em;
  margin-bottom: 5px;
}
.cd-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.8;
  color: var(--text);
}
.cd-rels {
  margin: 0;
  padding-left: 0;
  list-style: none;
}
.cd-rels li {
  font-size: 13px;
  line-height: 1.8;
}
.cd-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 26px;
}
</style>
