import { defineStore } from 'pinia'
import api, { type ScriptCard, type CharL1 } from '../api'

export const useScriptStore = defineStore('script', {
  state: () => ({
    script: null as ScriptCard | null,
    characters: [] as CharL1[],
    loading: false,
  }),
  actions: {
    async loadInfo(id: string) {
      this.script = await api.getScriptInfo(id)
    },
    async loadCharacters(id: string) {
      this.loading = true
      try {
        const res = await api.getScriptCharacters(id)
        this.characters = res.characters
        if (!this.script) {
          this.script = {
            id,
            title: res.title,
            category: '',
            scene: '',
            player_count: res.characters.length,
            text_size: 0,
            is_saved: 0,
            created_at: '',
          }
        }
      } finally {
        this.loading = false
      }
    },
    reset() {
      this.script = null
      this.characters = []
    },
  },
})
