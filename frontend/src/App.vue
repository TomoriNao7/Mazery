<script setup lang="ts">
import TitleBar from './components/TitleBar.vue'
import ToastHost from './components/ToastHost.vue'
</script>

<template>
  <div class="app-bg" />
  <div class="app-frame">
    <TitleBar />
    <div class="app-body">
      <router-view />
    </div>
  </div>
  <ToastHost />
</template>

<style>
#app {
  height: 100%;
}
.app-frame {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.app-body {
  flex: 1;
  min-height: 0;
}
</style>
