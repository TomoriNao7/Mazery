<script setup lang="ts">
import { ref, watch } from 'vue'
import api, { type ScriptCard } from '../api'
import { categoryName, textSizeLabel } from '../utils/format'
import { toast } from '../utils/toast'
import AppModal from './AppModal.vue'

const props = defineProps<{
  show: boolean
  scriptId: string
  canAddToLocal?: boolean
  canEdit?: boolean
}>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'play', id: string): void
  (e: 'added'): void
  (e: 'updated'): void
}>()

const loading = ref(false)
const info = ref<ScriptCard | null>(null)
const adding = ref(false)

// 编辑态
const editing = ref(false)
const editTitle = ref('')
const editSummary = ref('')
const saving = ref(false)

watch(
  () => [props.show, props.scriptId],
  async ([show]) => {
    if (show && props.scriptId) {
      loading.value = true
      editing.value = false
      try {
        info.value = await api.getScriptInfo(props.scriptId)
      } catch {
        info.value = null
      } finally {
        loading.value = false
      }
    }
  },
)

async function addToLocal() {
  if (!props.scriptId) return
  adding.value = true
  try {
    await api.saveScript(props.scriptId)
    emit('added')
  } finally {
    adding.value = false
  }
}

function startEdit() {
  if (!info.value) return
  editTitle.value = info.value.title
  editSummary.value = info.value.summary ?? ''
  editing.value = true
}

async function saveEdit() {
  const title = editTitle.value.trim()
  if (!title || saving.value) return
  saving.value = true
  try {
    info.value = await api.updateScript(props.scriptId, {
      title,
      summary: editSummary.value.trim(),
    })
    editing.value = false
    emit('updated')
    toast('剧本信息已更新', 'success')
  } catch (e) {
    toast((e as Error).message, 'error')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <AppModal :show="show" width="460px" @close="emit('close')">
    <div v-if="loading" class="p20">
      <div class="skeleton" style="height: 20px; width: 55%"></div>
      <div class="skeleton" style="height: 14px; width: 100%; margin-top: 18px"></div>
      <div class="skeleton" style="height: 14px; width: 85%; margin-top: 8px"></div>
    </div>
    <div v-else-if="editing && info" class="edit">
      <div class="edit-title display gold">编辑剧本信息</div>
      <label class="edit-label dim">剧本名字</label>
      <input v-model="editTitle" class="input" maxlength="255" placeholder="剧本名字" />
      <label class="edit-label dim" style="margin-top: 14px">剧本简介</label>
      <textarea
        v-model="editSummary"
        class="textarea"
        rows="6"
        maxlength="500"
        placeholder="一句话介绍这个剧本……"
      />
      <div class="edit-actions">
        <button class="btn btn-ghost" :disabled="saving" @click="editing = false">取消</button>
        <button class="btn btn-primary" :disabled="saving || !editTitle.trim()" @click="saveEdit">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>
    <div v-else-if="info" class="detail">
      <div class="detail-title display gold">{{ info.title }}</div>
      <div class="detail-tags">
        <span class="tag">{{ categoryName(info.category) }}</span>
        <span class="tag">{{ textSizeLabel(info.text_size) }}</span>
        <span v-if="info.player_count" class="tag">{{ info.player_count }} 人</span>
      </div>
      <p v-if="info.summary" class="detail-summary muted">{{ info.summary }}</p>
      <p v-else class="detail-summary dim">暂无简介。</p>
      <div class="detail-actions">
        <button v-if="canAddToLocal" class="btn btn-sm" :disabled="adding" @click="addToLocal">
          {{ adding ? '加入中…' : '+ 加入本地剧本库' }}
        </button>
        <div class="detail-action-group">
          <button
            v-if="canEdit"
            class="btn btn-icon"
            title="编辑剧本信息"
            @click="startEdit"
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <circle cx="12" cy="12" r="3" />
              <path
                d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"
              />
            </svg>
          </button>
          <button class="btn btn-primary" @click="emit('play', info.id)">游玩剧本</button>
        </div>
      </div>
    </div>
  </AppModal>
</template>

<style scoped>
.p20 {
  padding: 12px 0;
}
.detail-title {
  font-size: 24px;
  letter-spacing: 0.08em;
}
.detail-tags {
  display: flex;
  gap: 8px;
  margin-top: 14px;
}
.tag {
  font-size: 12px;
  color: var(--text-2);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 3px 12px;
  letter-spacing: 0.06em;
}
.detail-summary {
  margin: 18px 0 22px;
  font-size: 14px;
  line-height: 1.8;
  max-height: 120px;
  overflow-y: auto;
}
.detail-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  align-items: center;
}
.detail-action-group {
  display: flex;
  gap: 10px;
  align-items: center;
}
.btn-icon {
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  color: var(--text-2);
  background: var(--surface-2);
  border: 1px solid var(--border);
}
.btn-icon:hover {
  color: var(--accent-strong);
  border-color: var(--border-strong);
}
/* 编辑态 */
.edit {
  display: flex;
  flex-direction: column;
}
.edit-title {
  font-size: 18px;
  letter-spacing: 0.1em;
  margin-bottom: 18px;
}
.edit-label {
  font-size: 11px;
  letter-spacing: 0.18em;
  margin-bottom: 6px;
}
.edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 18px;
}
.textarea {
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
  min-height: 120px;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text);
  background: var(--bg-soft);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 12px;
  outline: none;
  transition: border-color 0.2s;
}
.textarea:focus {
  border-color: var(--accent);
}
</style>
