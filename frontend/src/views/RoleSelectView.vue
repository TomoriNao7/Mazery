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
const phase = ref<'confirm' | 'ready'>('confirm')

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
  phase.value = 'confirm'
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

function confirmRole() {
  if (detail.value) phase.value = 'ready'
}

/** 弹窗关闭：确定角色后锁定，只能点「开始游戏」进入。 */
function onClose() {
  if (phase.value === 'confirm') detailShow.value = false
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
</script>

<template>
  <section class="page anim-fade">
    <header class="page-head">
      <button class="back-btn" @click="router.back()">← 返回</button>
      <h2 class="h2">{{ title }}</h2>
      <p class="muted">选择你要扮演的角色</p>
    </header>

    <div v-if="loading" class="char-grid">
      <div v-for="i in 4" :key="i" class="skeleton" style="height: 130px; width: 190px"></div>
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

    <AppModal :show="detailShow" width="480px" @close="onClose">
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

        <!-- 第一步：仅公开信息 -->
        <template v-if="phase === 'confirm'">
          <div v-if="detail.appearance" class="cd-block">
            <div class="cd-label dim">外貌</div>
            <p class="cd-text">{{ detail.appearance }}</p>
          </div>
          <div v-if="detail.personality" class="cd-block">
            <div class="cd-label dim">个性</div>
            <p class="cd-text">{{ detail.personality }}</p>
          </div>
          <div v-if="detail.background" class="cd-block">
            <div class="cd-label dim">身份背景</div>
            <p class="cd-text">{{ detail.background }}</p>
          </div>
          <p class="phase-hint dim">确认后，你将看到该角色的完整角色卡——人物关系、当前目标与需要隐藏的秘密。</p>
          <div class="cd-actions">
            <button class="btn btn-ghost" @click="detailShow = false">再看看</button>
            <button class="btn btn-primary" @click="confirmRole">确定选择该角色</button>
          </div>
        </template>

        <!-- 第二步：角色卡（关系 / 目标 / 秘密 / 说话风格 / 信息边界） -->
        <template v-else>
          <div v-if="detail.is_murderer" class="murderer-banner">
            <div class="mb-title">你是真凶</div>
            <p class="mb-text">{{ detail.murderer_notice }}</p>
          </div>

          <div v-if="detail.relationships?.length" class="cd-block">
            <div class="cd-label dim">人物关系</div>
            <ul class="cd-rels">
              <li v-for="(r, i) in detail.relationships" :key="i" class="cd-text">
                <span class="gold">{{ r.name || '他人' }}</span>
                <span v-if="r.relation">（{{ r.relation }}）</span>
                <span v-if="r.description">：{{ r.description }}</span>
              </li>
            </ul>
          </div>

          <div v-if="detail.goal" class="cd-block">
            <div class="cd-label dim">当前目标</div>
            <p class="cd-text">{{ detail.goal }}</p>
          </div>

          <div v-if="detail.secrets?.length" class="cd-block">
            <div class="cd-label dim">需要隐藏的部分</div>
            <ul class="cd-rels">
              <li v-for="(s, i) in detail.secrets" :key="i" class="cd-text">{{ s }}</li>
            </ul>
          </div>

          <div v-if="detail.speaking_style" class="cd-block">
            <div class="cd-label dim">说话风格</div>
            <p class="cd-text">{{ detail.speaking_style }}</p>
          </div>

          <div v-if="detail.knowledge_boundary?.length" class="cd-block">
            <div class="cd-label dim">信息边界</div>
            <ul class="cd-rels">
              <li v-for="(kb, i) in detail.knowledge_boundary" :key="i" class="cd-text">{{ kb }}</li>
            </ul>
          </div>

          <div v-if="detail.own_clues?.length" class="cd-block">
            <div class="cd-label dim">可能指向你的线索</div>
            <p class="own-clue-hint">开局前先了解这些线索，一旦有人当众出示，你能从容应对。</p>
            <ul class="own-clues">
              <li v-for="cl in detail.own_clues" :key="cl.id" class="own-clue">
                <div class="oc-name gold">{{ cl.name }}</div>
                <div class="oc-desc cd-text">{{ cl.description }}</div>
                <div v-if="cl.location" class="oc-loc dim">📍 发现于：{{ cl.location }}</div>
              </li>
            </ul>
          </div>

          <div class="cd-actions ready-only">
            <button class="btn btn-primary" :disabled="starting" @click="start">
              {{ starting ? '进入中…' : '开始游戏' }}
            </button>
          </div>
        </template>
      </div>
    </AppModal>
  </section>
</template>

<style scoped>
.page {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.page-head {
  padding: 22px 24px 0;
  margin-bottom: 8px;
  text-align: center;
}
.page-head .back-btn {
  display: block;
  margin: 0 auto 10px;
}
.page-head p {
  margin: 8px 0 0;
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
  flex: 1;
  min-height: 0;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  align-items: center;
  align-content: center;
  gap: 22px;
  padding: 10px 24px 40px;
}
.char-card {
  width: 200px;
  height: 196px;
  padding: 22px 18px;
  text-align: center;
  border: none;
  color: var(--text);
  cursor: pointer;
  animation: fadeUp 0.5s var(--ease) both;
  background: var(--surface);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
}
.char-avatar {
  width: 54px;
  height: 54px;
  flex-shrink: 0;
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
  flex-wrap: wrap;
}
.char-person {
  font-size: 12px;
  margin-top: 10px;
  min-height: 34px;
  line-height: 1.55;
  color: var(--text-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
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
.murderer-banner {
  border: 1px solid rgba(220, 60, 60, 0.5);
  background: rgba(220, 60, 60, 0.08);
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 16px;
}
.mb-title {
  font-family: var(--font-display);
  font-size: 17px;
  color: #e05a5a;
  letter-spacing: 0.08em;
}
.mb-text {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text);
}
.own-clue-hint {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--text-2);
  line-height: 1.6;
}
.own-clues {
  margin: 0;
  padding: 0;
  list-style: none;
}
.own-clue {
  border: 1px dashed var(--border-strong);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 10px;
  background: var(--surface-2);
}
.oc-name {
  font-size: 14px;
  margin-bottom: 4px;
}
.oc-desc {
  font-size: 12.5px;
}
.oc-loc {
  margin-top: 5px;
  font-size: 11.5px;
}
.phase-hint {
  margin: 18px 0 0;
  font-size: 12px;
  line-height: 1.7;
}
.cd-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 26px;
}
.ready-only {
  justify-content: center;
}
.ready-only .btn {
  min-width: 180px;
}
</style>
