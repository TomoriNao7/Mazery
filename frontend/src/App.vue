<script setup lang="ts">
import ToastHost from './components/ToastHost.vue'
</script>

<template>
  <div class="app-bg" />
  <router-view />
  <ToastHost />
</template>

<style>
#app {
  height: 100%;
}
</style>
