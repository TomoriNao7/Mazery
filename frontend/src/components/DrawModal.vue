<script setup lang="ts">
import { ref, watch } from 'vue'
import { useGameStore } from '../stores/game'
import AppModal from './AppModal.vue'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const game = useGameStore()
const cards = ref<{ card_id: string; index: number }[]>([])
const clue = ref<{ id: string; name: string; description: string; location?: string } | null>(null)
const loading = ref(false)
const error = ref('')
const picking = ref('')

async function load() {
  loading.value = true
  error.value = ''
  cards.value = []
  clue.value = null
  try {
    const res = await game.getDraw()
    cards.value = res.cards
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function pick(cardId: string) {
  if (picking.value) return
  picking.value = cardId
  error.value = ''
  try {
    const res = await game.pickDraw(cardId)
    clue.value = res.clue
    cards.value = []
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    picking.value = ''
  }
}

async function next() {
  try {
    await game.advanceNow()
    emit('close')
  } catch (e) {
    error.value = (e as Error).message
  }
}

watch(
  () => props.show,
  (v) => {
    if (v) void load()
  },
)
</script>

<template>
  <AppModal :show="show" width="560px" title="线索搜证">
    <div class="draw">
      <p v-if="!clue" class="draw-hint dim">从牌堆中选一张翻开，线索将收入你的手中</p>
      <p v-else class="draw-hint dim">你得到的线索</p>

      <div v-if="loading" class="draw-loading">
        <div v-for="i in 5" :key="i" class="skeleton" style="height: 170px; width: 110px; border-radius: 10px"></div>
      </div>

      <div v-else-if="error" class="draw-error">
        <p class="dim">{{ error }}</p>
        <button class="btn btn-sm" @click="load">重试</button>
      </div>

      <div v-else-if="!clue" class="draw-cards">
        <div
          v-for="(c, i) in cards"
          :key="c.card_id"
          class="draw-card"
          :style="{ animationDelay: i * 70 + 'ms', animationDuration: '0.5s' }"
          :class="{ picking: picking === c.card_id }"
          @click="pick(c.card_id)"
        >
          <div class="dc-back">
            <span class="dc-filigree">✦</span>
            <span class="dc-word dim">谜</span>
          </div>
        </div>
      </div>

      <div v-else class="draw-reveal anim-scale">
        <div class="clue-name gold">{{ clue.name }}</div>
        <div v-if="clue.location" class="clue-loc dim">发现于：{{ clue.location }}</div>
        <p class="clue-desc">{{ clue.description }}</p>
        <button class="btn btn-primary" @click="next">进入下一幕</button>
      </div>
    </div>
  </AppModal>
</template>

<style scoped>
.draw {
  text-align: center;
}
.draw-hint {
  font-size: 13px;
  margin: 0 0 22px;
}
.draw-loading,
.draw-cards {
  display: flex;
  justify-content: center;
  gap: 16px;
  min-height: 170px;
  align-items: center;
}
.draw-card {
  width: 108px;
  height: 168px;
  cursor: pointer;
  animation: fadeUp 0.5s var(--ease) both;
  perspective: 700px;
}
.draw-card:hover {
  transform: translateY(-8px);
}
.dc-back {
  width: 100%;
  height: 100%;
  border-radius: 10px;
  background:
    radial-gradient(120px 120px at 50% 30%, rgba(201, 162, 110, 0.12), transparent 70%),
    linear-gradient(160deg, #23232e, #181820);
  border: 1px solid var(--border-strong);
  box-shadow: var(--shadow-1);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  transition: all 0.3s var(--ease);
}
.draw-card:hover .dc-back {
  border-color: rgba(224, 192, 140, 0.6);
  box-shadow: var(--shadow-gold);
}
.draw-card.picking .dc-back {
  animation: scaleIn 0.4s var(--ease);
}
.dc-filigree {
  color: var(--accent);
  font-size: 22px;
}
.dc-word {
  font-family: var(--font-display);
  font-size: 28px;
  letter-spacing: 0.1em;
}
.draw-reveal {
  padding: 12px 18px 6px;
  animation: scaleIn 0.4s var(--ease) both;
}
.clue-name {
  font-size: 20px;
  letter-spacing: 0.08em;
}
.clue-loc {
  font-size: 12px;
  margin-top: 6px;
}
.clue-desc {
  font-size: 14px;
  line-height: 1.9;
  color: var(--text);
  margin: 18px 0 24px;
  text-align: left;
  background: var(--bg-soft);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px 18px;
}
.draw-error {
  padding: 40px 0;
}
</style>
