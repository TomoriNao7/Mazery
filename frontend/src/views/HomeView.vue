<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="home">
    <div class="orb orb-a" />
    <div class="orb orb-b" />
    <div class="home-inner">
      <div class="home-brand anim-fade-up">MAZERY</div>
      <div class="home-title display anim-fade-up">迷 城</div>
      <div class="home-sub anim-fade-up">每一局推理，皆独一无二</div>
      <div class="home-line anim-fade-up" />
      <div class="home-actions anim-fade-up">
        <button class="btn btn-primary home-start glow-hover" @click="router.push('/library')">
          开始游戏
        </button>
        <button class="btn btn-ghost home-settings" @click="router.push('/settings')">设置</button>
      </div>    </div>
  </div>
</template>

<style scoped>
.home {
  position: relative;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  opacity: 0.35;
}
.orb-a {
  width: 420px;
  height: 420px;
  background: radial-gradient(circle, rgba(201, 162, 110, 0.5), transparent 70%);
  top: -120px;
  right: -60px;
}
.orb-b {
  width: 380px;
  height: 380px;
  background: radial-gradient(circle, rgba(120, 90, 50, 0.4), transparent 70%);
  bottom: -140px;
  left: -80px;
}
.home-inner {
  position: relative;
  text-align: center;
  z-index: 1;
}
.home-brand {
  font-size: 15px;
  letter-spacing: 0.55em;
  color: var(--accent);
  opacity: 0.85;
}
.home-title {
  font-size: 88px;
  font-weight: 500;
  letter-spacing: 0.32em;
  margin: 10px 0 6px;
  padding-left: 0.32em;
  background: linear-gradient(180deg, #f5ead6, #c9a26e 60%, #8c7346);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  text-shadow: 0 0 40px rgba(201, 162, 110, 0.15);
}
.home-sub {
  color: var(--text-2);
  font-size: 14px;
  letter-spacing: 0.3em;
}
.home-line {
  width: 60px;
  height: 1px;
  margin: 28px auto;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
}
.home-actions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  margin-top: 8px;
}
.home-start {
  min-width: 180px;
  padding: 14px 40px;
  font-size: 15px;
  letter-spacing: 0.12em;
}
.home-settings {
  padding: 9px 26px;
  font-size: 13px;
}
</style>
