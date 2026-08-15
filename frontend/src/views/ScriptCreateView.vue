<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'
import AppModal from '../components/AppModal.vue'
import { toast } from '../utils/toast'

const router = useRouter()

const TYPES = [
  { value: 'modern', label: '现代本格' },
  { value: 'ancient', label: '古风悬疑' },
  { value: 'republic', label: '民国谍战' },
  { value: 'japanese', label: '日式推理' },
  { value: 'campus', label: '校园青春' },
  { value: '仙侠', label: '仙侠' },
  { value: '科幻', label: '科幻' },
  { value: '西幻', label: '西幻' },
  { value: '欧式推理', label: '欧式推理' },
  { value: '恐怖志怪', label: '恐怖志怪' },
]

const type = ref('')
const background = ref('')
const count = ref(4)
const title = ref('')
const outline = ref('')
const extra = ref('')
const errors = ref<Record<string, string>>({})

const generating = ref(false)
const progress = ref(0)
const stageIdx = ref(0)
const resultId = ref('')
const genError = ref('')
const saving = ref(false)

const STAGES = [
  '正在构建世界…',
  '正在设计案件…',
  '正在安排角色…',
  '正在铺设线索…',
  '正在编排幕次…',
  '正在审查公平性…',
]

let timer: ReturnType<typeof setInterval> | null = null

const currentStage = computed(() => STAGES[Math.min(stageIdx.value, STAGES.length - 1)])

function validate(): boolean {
  const e: Record<string, string> = {}
  if (!type.value) e.type = '请选择剧本类型'
  if (!background.value.trim()) e.background = '请填写剧本背景'
  if (!count.value || count.value < 2 || count.value > 12) e.count = '人物数量需在 2-12 之间'
  errors.value = e
  return Object.keys(e).length === 0
}

function startProgress() {
  progress.value = 0
  stageIdx.value = 0
  timer = setInterval(() => {
    if (progress.value >= 95) return
    progress.value = Math.min(95, progress.value + 1.5 + Math.random() * 1.5)
    stageIdx.value = Math.min(STAGES.length - 1, Math.floor((progress.value / 100) * STAGES.length))
  }, 240)
}

function stopProgress() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

async function submit() {
  if (generating.value) return
  if (!validate()) return
  generating.value = true
  genError.value = ''
  resultId.value = ''
  startProgress()
  try {
    const outlineText = [outline.value.trim(), extra.value.trim()].filter(Boolean).join('\n')
    const res = await api.generateCustomScript({
      title: title.value.trim() || null,
      category: type.value,
      scene: background.value.trim(),
      player_count: count.value,
      outline: outlineText || null,
      is_custom: 1,
    })
    resultId.value = res?.id || res?.script_id || ''
    progress.value = 100
    stageIdx.value = STAGES.length - 1
  } catch (e) {
    genError.value = (e as Error).message
    progress.value = 0
    stageIdx.value = 0
  } finally {
    generating.value = false
    stopProgress()
  }
}

async function saveResult() {
  if (!resultId.value) return
  saving.value = true
  try {
    await api.saveScript(resultId.value)
    toast('已保存到本地剧本库', 'success')
  } catch (e) {
    toast((e as Error).message, 'error')
  } finally {
    saving.value = false
  }
}

function startGame() {
  if (!resultId.value) return
  generating.value = false
  router.push(`/script/${resultId.value}/select`)
}

onBeforeUnmount(stopProgress)
</script>

<template>
  <section class="page anim-fade create">
    <div class="create-wrap">
      <header class="page-head">
        <h2 class="h2">创建剧本</h2>
        <p class="muted">填写必填项，其余交给 AI 补全</p>
      </header>

      <div class="create-card">
      <div class="form-row">
        <div class="form-col">
          <label class="field-label">剧本类型 <span class="req">*</span></label>
          <select v-model="type" class="select">
            <option value="" disabled>选择类型</option>
            <option v-for="t in TYPES" :key="t.value" :value="t.value">{{ t.label }}</option>
          </select>
          <p v-if="errors.type" class="field-error">{{ errors.type }}</p>
        </div>
        <div class="form-col">
          <label class="field-label">剧本人物数量 <span class="req">*</span></label>
          <div class="stepper">
            <button class="step-btn" @click="count = Math.max(2, count - 1)">−</button>
            <span class="step-val">{{ count }} 人</span>
            <button class="step-btn" @click="count = Math.min(12, count + 1)">＋</button>
          </div>
          <p v-if="errors.count" class="field-error">{{ errors.count }}</p>
        </div>
      </div>

      <div class="form-col">
        <label class="field-label">剧本背景 <span class="req">*</span></label>
        <textarea v-model="background" class="textarea" placeholder="例如：民国年间，上海滩一间戏院里，名伶在谢幕时倒在台上……" />
        <p v-if="errors.background" class="field-error">{{ errors.background }}</p>
      </div>

      <div class="form-col">
        <label class="field-label">剧本名称 <span class="dim">（选填）</span></label>
        <input v-model="title" class="input" placeholder="留空则由 AI 命名" />
      </div>

      <div class="form-col">
        <label class="field-label">剧本故事大纲 <span class="dim">（选填）</span></label>
        <textarea v-model="outline" class="textarea" placeholder="一句话或一段大纲，AI 将据此完善剧情" />
      </div>

      <div class="form-col">
        <label class="field-label">其他补充 <span class="dim">（选填，如诡计偏好、希望加入的元素）</span></label>
        <textarea v-model="extra" class="textarea" placeholder="可留空，由 AI 自由发挥" style="min-height: 60px" />
      </div>

      <div class="create-actions">
        <button class="btn btn-primary" :disabled="generating" @click="submit">✨ 生成完整剧本</button>
      </div>
      </div>
    </div>

    <!-- 创作进度 -->
    <AppModal :show="generating || !!resultId || !!genError" :width="'440px'">
      <div class="gen">
        <div class="gen-title display gold">剧本创作中</div>

        <template v-if="resultId && !genError">
          <div class="gen-done">
            <div class="gen-check">✓</div>
            <p class="muted">剧本已生成，可以开始游戏了</p>
          </div>
        </template>

        <template v-else-if="genError">
          <div class="gen-error">
            <p class="gen-err-text">{{ genError }}</p>
            <button class="btn btn-sm" @click="genError = ''; resultId = ''">返回修改</button>
          </div>
        </template>

        <template v-else>
          <div class="gen-track">
            <div class="gen-bar" :style="{ width: progress + '%' }" />
          </div>
          <div class="gen-stage dim">{{ currentStage }}</div>
        </template>

        <div v-if="resultId && !genError" class="gen-actions">
          <button class="btn btn-sm" :disabled="saving" @click="saveResult">
            {{ saving ? '保存中…' : '保存剧本到本地库' }}
          </button>
          <button class="btn btn-primary" @click="startGame">开始游戏</button>
        </div>
      </div>
    </AppModal>
  </section>
</template>

<style scoped>
.create {
  height: 100%;
  display: flex;
  overflow-y: auto;
}
.create-wrap {
  margin: auto;
  width: 100%;
  max-width: 680px;
  padding: 24px 20px;
}
.page-head {
  margin-bottom: 24px;
}
.page-head p {
  margin: 6px 0 0;
  font-size: 13px;
}
.create-card {
  width: 100%;
  max-width: 640px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: 26px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.form-col {
  display: flex;
  flex-direction: column;
}
.field-error {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--danger);
}
.stepper {
  display: flex;
  align-items: center;
  gap: 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 8px 14px;
  background: var(--bg-soft);
}
.step-val {
  flex: 1;
  text-align: center;
  font-size: 14px;
}
.step-btn {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 16px;
  cursor: pointer;
  transition: all 0.2s;
}
.step-btn:hover {
  border-color: var(--border-strong);
  color: var(--accent-strong);
}
.create-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 6px;
}
/* 进度 */
.gen {
  text-align: center;
}
.gen-title {
  font-size: 18px;
  letter-spacing: 0.1em;
}
.gen-track {
  height: 6px;
  border-radius: 6px;
  background: var(--surface-2);
  margin: 22px 0 12px;
  overflow: hidden;
}
.gen-bar {
  height: 100%;
  border-radius: 6px;
  background: linear-gradient(90deg, var(--accent-dim), var(--accent-strong));
  transition: width 0.3s ease;
  box-shadow: 0 0 12px rgba(201, 162, 110, 0.4);
}
.gen-stage {
  font-size: 13px;
  letter-spacing: 0.08em;
  min-height: 20px;
}
.gen-done {
  padding: 26px 0 6px;
}
.gen-check {
  width: 52px;
  height: 52px;
  margin: 0 auto 14px;
  border-radius: 50%;
  background: var(--accent-soft);
  border: 1px solid var(--border-strong);
  color: var(--accent-strong);
  font-size: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: scaleIn 0.4s var(--ease) both;
}
.gen-error {
  padding: 24px 0 8px;
}
.gen-err-text {
  color: var(--danger);
  font-size: 13px;
  margin: 0 0 18px;
}
.gen-actions {
  display: flex;
  justify-content: center;
  gap: 12px;
  margin-top: 22px;
}
</style>
