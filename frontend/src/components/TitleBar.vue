<template>
  <header class="title-bar">
    <div class="tb-brand display">
      <span class="tb-en">MAZERY</span>
      <span class="tb-sep" />
      <span class="tb-zh">迷 城</span>
    </div>
  </header>
</template>

<style scoped>
.title-bar {
  height: 36px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  padding: 0 14px;
  background: var(--bg-soft);
  border-bottom: 1px solid var(--border);
  /* 整条标题栏可拖动窗口；按钮区为原生 overlay，不受影响 */
  -webkit-app-region: drag;
  user-select: none;
}
.tb-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  letter-spacing: 0.32em;
}
.tb-en {
  color: var(--accent);
  opacity: 0.9;
}
.tb-sep {
  width: 1px;
  height: 12px;
  align-self: center;
  background: var(--border-strong);
}
.tb-zh {
  color: var(--text-2);
  letter-spacing: 0.4em;
}
</style>
