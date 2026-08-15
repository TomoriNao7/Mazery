import { defineStore } from 'pinia'
import api, { type LlmSettings, type ModelPreset } from '../api'

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    settings: null as LlmSettings | null,
    models: [] as ModelPreset[],
    loading: false,
    saved: false,
  }),
  actions: {
    async load() {
      this.loading = true
      try {
        const [s, m] = await Promise.all([api.getSettings(), api.getModels()])
        this.settings = s
        this.models = m
      } finally {
        this.loading = false
      }
    },
    async save(payload: Record<string, unknown>) {
      await api.saveSettings(payload)
      this.saved = true
      await this.load()
    },
  },
})
