import { ref, reactive } from 'vue'

const API = '/api'

// 模块级单例 — 所有调用者共享同一份数据
const characters = ref([])
const activeCharId = ref('')
const profile = reactive({
  name: '',
  gender: 'female',
  avatar: '',
  initial_outfit_tags: '',
  visual_anchor: {
    role_tags: '',
    body_tags: '',
    appearance_tags: ''
  }
})
const loading = ref(false)

const emptyProfile = () => ({
  name: '',
  gender: 'female',
  avatar: '',
  initial_outfit_tags: '',
  visual_anchor: {
    role_tags: '',
    body_tags: '',
    appearance_tags: ''
  }
})

const normalizeVisual = (raw) => ({
  role_tags: '',
  body_tags: '',
  appearance_tags: '',
  ...(raw || {})
})

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
      // profile.json 只存 visual_anchor 嵌套结构；老数据若有遗留平铺字段也兜底读一次
      const visual = normalizeVisual(
        p.visual_anchor ||
          (p.avatar_role || p.body_type || p.appearance
            ? {
                role_tags: p.avatar_role || '',
                body_tags: p.body_type || '',
                appearance_tags: p.appearance || ''
              }
            : null)
      )
      Object.assign(profile, emptyProfile(), p, { visual_anchor: visual })
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
    const payload = {
      name: profile.name,
      gender: profile.gender,
      avatar: profile.avatar,
      initial_outfit_tags: profile.initial_outfit_tags || '',
      visual_anchor: {
        role_tags: profile.visual_anchor?.role_tags || '',
        body_tags: profile.visual_anchor?.body_tags || '',
        appearance_tags: profile.visual_anchor?.appearance_tags || ''
      }
    }
    const res = await fetch(`${API}/characters/${charId}/profile`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      console.error('保存失败:', res.status, err.detail || res.statusText)
    }
  }

  const createCharacter = async (name, fields = {}) => {
    const { name: displayName, ...rest } = fields
    const res = await fetch(`${API}/characters/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, display_name: displayName, ...rest })
    })
    if (res.ok) characters.value.push(name)
  }

  const deleteCharacter = async (name) => {
    const res = await fetch(`${API}/characters/${encodeURIComponent(name)}`, { method: 'DELETE' })
    if (res.ok) {
      characters.value = characters.value.filter(c => c !== name)
      if (activeCharId.value === name) await loadAll()
    }
    const err = res.ok ? {} : await res.json().catch(() => ({}))
    return { ok: res.ok, error: err.detail || res.statusText || '删除失败' }
  }

  const clearCharacterRecords = async (name) => {
    const res = await fetch(`${API}/characters/${encodeURIComponent(name)}/memory/reset`, { method: 'POST' })
    return res.ok
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
    createCharacter,
    deleteCharacter,
    clearCharacterRecords
  }
}
