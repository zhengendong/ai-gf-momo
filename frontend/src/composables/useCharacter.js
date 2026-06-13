import { ref, reactive } from 'vue'

const API = '/api'

// 模块级单例 — 所有调用者共享同一份数据
const characters = ref([])
const activeCharId = ref('')  // 目录名（API 标识），不是显示名
const profile = reactive({
  name: '',
  avatar: '',
  avatar_role: '',
  body_type: '',
  appearance: ''
})
const loading = ref(false)

export function useCharacter() {
  const loadAll = async () => {
    loading.value = true
    try {
      const res = await fetch(`${API}/characters`).then(r => r.json())
      characters.value = res.characters || []
      if (res.active) {
        activeCharId.value = res.active
        await loadProfile(res.active)
      }
    } catch (e) {
      console.error('加载角色列表失败:', e)
    } finally {
      loading.value = false
    }
  }

  const loadProfile = async (charId) => {
    try {
      const p = await fetch(`${API}/characters/${charId}/profile`).then(r => r.json())
      Object.assign(profile, { name: '', avatar: '', avatar_role: '', body_type: '', appearance: '' }, p)
    } catch (e) {
      console.error('加载角色资料失败:', e)
    }
  }

  const switchCharacter = async (name) => {
    await fetch(`${API}/characters/switch?name=${name}`, { method: 'POST' })
    window.location.reload()
  }

  const saveProfile = async () => {
    const charId = activeCharId.value
    if (!charId) {
      console.error('无法保存：未知角色 ID')
      return
    }
    const res = await fetch(`${API}/characters/${charId}/profile`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(profile)
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      console.error('保存失败:', res.status, err.detail || res.statusText)
    }
  }

  const createCharacter = async (name, fields = {}) => {
    const res = await fetch(`${API}/characters/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, ...fields })
    })
    if (res.ok) characters.value.push(name)
  }

  return {
    characters,
    profile,
    activeCharId,
    loading,
    loadAll,
    loadProfile,
    switchCharacter,
    saveProfile,
    createCharacter
  }
}
