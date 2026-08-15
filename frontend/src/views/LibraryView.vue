<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const active = computed(() => route.path)

function onMenu(path: string) {
  router.push(path)
}
</script>

<template>
  <div class="lib">
    <aside class="lib-menu">
      <div class="lib-brand display" @click="router.push('/')">迷 城</div>
      <div class="lib-brand-sub dim">MAZERY</div>
      <nav class="lib-nav">
        <button
          class="nav-item"
          :class="{ on: active.startsWith('/library/local') }"
          @click="onMenu('/library/local')"
        >
          <span class="nav-dot" />
          本地剧本库
        </button>
        <button
          class="nav-item"
          :class="{ on: active.startsWith('/library/history') }"
          @click="onMenu('/library/history')"
        >
          <span class="nav-dot" />
          历史游玩剧本库
        </button>
        <button
          class="nav-item"
          :class="{ on: active.startsWith('/library/create') }"
          @click="onMenu('/library/create')"
        >
          <span class="nav-dot" />
          创建剧本
        </button>
      </nav>
      <div class="lib-foot">
        <button class="btn btn-ghost btn-sm" @click="router.push('/settings')">设置</button>
      </div>
    </aside>
    <main class="lib-content">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.lib {
  height: 100%;
  display: flex;
}
.lib-menu {
  width: 216px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  padding: 30px 18px;
  border-right: 1px solid var(--border);
  background: linear-gradient(180deg, #0e0e13, #0b0b0f);
}
.lib-brand {
  font-size: 26px;
  letter-spacing: 0.2em;
  padding-left: 10px;
  cursor: pointer;
  color: var(--text);
  transition: color 0.3s;
}
.lib-brand:hover {
  color: var(--accent-strong);
}
.lib-brand-sub {
  font-size: 10px;
  letter-spacing: 0.5em;
  padding-left: 12px;
  margin-bottom: 34px;
}
.lib-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 14px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: var(--text-2);
  font-size: 14px;
  cursor: pointer;
  text-align: left;
  transition: all 0.25s var(--ease);
}
.nav-item:hover {
  background: var(--surface);
  color: var(--text);
}
.nav-item.on {
  background: linear-gradient(90deg, var(--accent-soft), transparent 90%);
  color: var(--accent-strong);
}
.nav-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-3);
  transition: all 0.25s;
}
.nav-item.on .nav-dot {
  background: var(--accent);
  box-shadow: 0 0 8px var(--accent);
}
.lib-foot {
  margin-top: auto;
  padding-left: 8px;
}
.lib-content {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 30px 40px;
}
</style>
