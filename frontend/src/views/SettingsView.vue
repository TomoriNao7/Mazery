<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useSettingsStore } from '../stores/settings'
import type { ModelPreset } from '../api'
import { toast } from '../utils/toast'

const router = useRouter()
const store = useSettingsStore()

const model = ref('')
const baseUrl = ref('')
const temperature = ref(0.7)
const maxTokens = ref(16384)
const apiKey = ref('')
const saving = ref(false)

onMounted(async () => {
  await store.load()
  const s = store.settings
  if (s) {
    model.value = s.model
    baseUrl.value = s.base_url
    temperature.value = s.temperature
    maxTokens.value = s.max_tokens
  }
})

function applyPreset(p: ModelPreset) {
  model.value = p.models[0] || ''
  baseUrl.value = p.default_base_url
  if (!p.requires_key) apiKey.value = ''
}

async function save() {
  saving.value = true
  try {
    await store.save({
      model: model.value,
      base_url: baseUrl.value,
      temperature: temperature.value,
      max_tokens: maxTokens.value,
      api_key: apiKey.value || undefined,
    })
    apiKey.value = ''
    toast('已保存并生效', 'success')
  } catch (e) {
    toast((e as Error).message, 'error')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="page anim-fade settings">
    <header class="page-head">
      <button class="back-btn" @click="router.push('/')">← 返回</button>
      <h2 class="h2">设置</h2>
      <p class="muted">选择本地 Ollama 模型，或使用云端 API</p>
    </header>

    <div class="settings-card">
      <div class="label-title dim">模型预设</div>
      <div v-if="store.loading" class="skeleton" style="height: 40px"></div>
      <div v-else class="preset-grid">
        <button
          v-for="p in store.models"
          :key="p.id"
          class="preset-item card card-hover"
          @click="applyPreset(p)"
        >
          {{ p.name }}
        </button>
      </div>

      <div class="label-title dim" style="margin-top: 24px">连接配置</div>
      <div class="form-col">
        <label class="field-label">Base URL</label>
        <input v-model="baseUrl" class="input" placeholder="http://localhost:11434/v1" />
      </div>
      <div class="form-row">
        <div class="form-col">
          <label class="field-label">模型</label>
          <input v-model="model" class="input" placeholder="如 qwen3.5:4b / qwen3.7-max" />
        </div>
        <div class="form-col">
          <label class="field-label">Temperature</label>
          <input v-model.number="temperature" class="input" type="number" min="0" max="2" step="0.1" />
        </div>
        <div class="form-col">
          <label class="field-label">Max Tokens</label>
          <input v-model.number="maxTokens" class="input" type="number" min="256" step="256" />
        </div>
      </div>

      <div class="form-col">
        <label class="field-label">API Key <span class="dim">（本地模型可留空）</span></label>
        <input
          v-model="apiKey"
          class="input"
          type="password"
          :placeholder="store.settings?.api_key_set ? store.settings.api_key_masked : 'sk-…'"
        />
      </div>

      <div class="settings-actions">
        <button class="btn btn-primary" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存并应用' }}
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.page-head {
  margin-bottom: 24px;
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
.settings-card {
  max-width: 680px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: 26px;
}
.label-title {
  font-size: 11px;
  letter-spacing: 0.25em;
  margin-bottom: 12px;
}
.preset-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
}
.preset-item {
  padding: 12px 14px;
  border: none;
  color: var(--text-2);
  font-size: 13px;
  cursor: pointer;
  background: var(--bg-soft);
  text-align: center;
}
.preset-item:hover {
  color: var(--accent-strong);
  border-color: var(--border-strong);
}
.form-row {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr;
  gap: 12px;
  margin-bottom: 16px;
}
.form-col {
  display: flex;
  flex-direction: column;
  margin-bottom: 16px;
}
.settings-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}
</style>
