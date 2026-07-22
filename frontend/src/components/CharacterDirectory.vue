<template>
  <aside class="character-directory">
    <div class="directory-header">
      <div>
        <h2>角色</h2>
        <p>{{ characters.length }} 个会话</p>
      </div>
      <button class="icon-btn" @click="openCreate" title="新建角色">+</button>
    </div>

    <div class="character-list">
      <div
        v-for="c in characters"
        :key="c"
        class="character-item"
        :class="{ active: c === activeCharId }"
      >
        <button class="character-main" @click="switchCharacter(c)">
          <span class="avatar">{{ profileCache[c]?.avatar || '💕' }}</span>
          <span class="meta">
            <strong>{{ profileCache[c]?.name || c }}</strong>
            <small>{{ c }}</small>
          </span>
        </button>
        <div class="item-menu-wrap">
          <button class="more-btn" @click.stop="toggleMenu(c)" title="角色操作">⋯</button>
          <div v-if="openMenuFor === c" class="item-menu">
            <button @click.stop="clearRecords(c)">清除记录</button>
            <button class="danger" @click.stop="deleteOne(c)">删除角色</button>
          </div>
        </div>
      </div>
    </div>
  </aside>

  <div v-if="creating" class="modal-mask">
    <div class="modal-card">
      <h3>新建角色</h3>
      <div class="form-row">
        <div class="form-field">
          <label>目录 ID</label>
          <input v-model.trim="form.id" placeholder="sakura" />
        </div>
        <div class="form-field">
          <label>显示名</label>
          <input v-model.trim="form.name" placeholder="小樱" />
        </div>
      </div>
      <div class="form-field">
        <label>头像 emoji</label>
        <input v-model="form.avatar" placeholder="💗" />
      </div>
      <div class="form-row">
        <div class="form-field">
          <label>角色性别</label>
          <select v-model="form.character_gender">
            <option value="" disabled>请选择</option>
            <option value="female">女性</option>
            <option value="male">男性</option>
          </select>
        </div>
        <div class="form-field">
          <label>玩家性别</label>
          <select v-model="form.player_gender">
            <option value="" disabled>请选择</option>
            <option value="female">女性</option>
            <option value="male">男性</option>
          </select>
        </div>
      </div>
      <SkinTagAssistant @apply="applySkinMapping" />
      <div class="form-field">
        <label>角色锚点标签</label>
        <textarea v-model="form.role_tags" rows="2"></textarea>
      </div>
      <div class="form-field">
        <label>体型标签</label>
        <textarea v-model="form.body_tags" rows="2"></textarea>
      </div>
      <div class="form-field">
        <label>外貌标签</label>
        <textarea v-model="form.appearance_tags" rows="3"></textarea>
      </div>
      <div class="form-field">
        <label>身份设定</label>
        <textarea v-model="form.identity" rows="6"></textarea>
      </div>
      <div class="form-field">
        <label>用户设定</label>
        <textarea v-model="form.user_identity" rows="4" placeholder="用户是谁、关系定位、称呼偏好等"></textarea>
      </div>
      <div class="form-row">
        <div class="form-field">
          <label>用户称呼</label>
          <input v-model.trim="form.user_pet_name" placeholder="主人" />
        </div>
        <div class="form-field">
          <label>沟通偏好</label>
          <input v-model.trim="form.communication_style" placeholder="温柔、直接、调皮..." />
        </div>
      </div>
      <div class="form-field">
        <label>用户备注</label>
        <textarea v-model="form.user_notes" rows="3"></textarea>
      </div>
      <div class="form-field">
        <label>初始场景构想</label>
        <textarea
          v-model="form.initial_scene_concept"
          rows="4"
          placeholder="描述故事开始时希望成立的时间、地点、人物关系或穿着；留空时由角色根据设定自主构建"
        ></textarea>
      </div>
      <div class="form-field">
        <label>谁先开口</label>
        <select v-model="form.initial_opening_mode">
          <option value="character_first">角色主动打招呼</option>
          <option value="player_first">玩家先打招呼（只渲染背景）</option>
        </select>
      </div>
      <div class="modal-actions">
        <button class="primary" @click="saveModal" :disabled="!form.id || !form.character_gender || !form.player_gender">创建</button>
        <button @click="closeModal">取消</button>
      </div>
    </div>
  </div>

  <div v-if="deleteTarget" class="modal-mask">
    <div class="confirm-card">
      <h3>删除角色</h3>
      <p>确认删除「{{ deleteDisplayName }}」？这会删除该角色的设定、记忆、聊天记录和图片数据。</p>
      <div v-if="deleteError" class="error-text">{{ deleteError }}</div>
      <div class="modal-actions">
        <button class="danger-btn" @click="confirmDelete" :disabled="deleting">
          {{ deleting ? '删除中...' : '删除角色' }}
        </button>
        <button @click="cancelDelete" :disabled="deleting">取消</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import { useCharacter } from '../composables/useCharacter.js'
import SkinTagAssistant from './SkinTagAssistant.vue'

const {
  characters,
  activeCharId,
  switchCharacter,
  createCharacter,
  deleteCharacter,
  clearCharacterRecords,
} = useCharacter()

const profileCache = reactive({})
const creating = ref(false)
const openMenuFor = ref('')
const deleteTarget = ref('')
const deleteDisplayName = ref('')
const deleteError = ref('')
const deleting = ref(false)
const form = reactive(defaultForm())

watch(characters, refreshProfiles, { immediate: true, deep: true })

function defaultForm() {
  return {
    id: '',
    name: '',
    avatar: '💕',
    character_gender: '',
    player_gender: '',
    role_tags: '',
    body_tags: '',
    appearance_tags: '',
    identity: '',
    user_identity: '',
    user_pet_name: '',
    communication_style: '',
    user_notes: '',
    initial_scene_concept: '',
    initial_opening_mode: 'character_first',
  }
}

function resetForm() {
  Object.assign(form, defaultForm())
}

async function refreshProfiles() {
  for (const c of characters.value) {
    if (profileCache[c]) continue
    try {
      profileCache[c] = await fetch(`/api/characters/${c}/profile`).then(r => r.json())
    } catch (e) { /* ignore */ }
  }
}

function openCreate() {
  resetForm()
  creating.value = true
}

function closeModal() {
  creating.value = false
}

function toggleMenu(id) {
  openMenuFor.value = openMenuFor.value === id ? '' : id
}

function applySkinMapping(item) {
  form.role_tags = item.role_tags || ''
  form.body_tags = item.body_tags || ''
  form.appearance_tags = item.appearance_tags || ''
}

async function saveModal() {
  if (!form.id || !form.character_gender || !form.player_gender) return
  await createCharacter(form.id, {
    name: form.name || form.id,
    gender: form.character_gender,
    avatar: form.avatar,
    visual_anchor: {
      role_tags: form.role_tags,
      body_tags: form.body_tags,
      appearance_tags: form.appearance_tags,
    },
    identity: form.identity,
    user_profile: {
      gender: form.player_gender,
      user_pet_name: form.user_pet_name,
      identity: form.user_identity,
      communication_style: form.communication_style,
      notes: form.user_notes,
    },
    initial_scene: {
      concept: form.initial_scene_concept,
      opening_mode: form.initial_opening_mode,
    },
  })
  closeModal()
  await switchCharacter(form.id)
}

async function clearRecords(id) {
  openMenuFor.value = ''
  const displayName = profileCache[id]?.name || id
  if (!confirm(`确认清除「${displayName}」的聊天记录、记忆摘要和图片记录？角色设定和皮肤会保留。`)) return
  await clearCharacterRecords(id)
  window.dispatchEvent(new CustomEvent('character-records-cleared', { detail: { character: id } }))
}

async function deleteOne(id) {
  openMenuFor.value = ''
  deleteTarget.value = id
  deleteDisplayName.value = profileCache[id]?.name || id
  deleteError.value = ''
}

function cancelDelete() {
  if (deleting.value) return
  deleteTarget.value = ''
  deleteDisplayName.value = ''
  deleteError.value = ''
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  deleteError.value = ''
  const id = deleteTarget.value
  try {
    const result = await deleteCharacter(id)
    if (!result.ok) {
      deleteError.value = result.error || '删除失败，请稍后重试。'
      return
    }
    delete profileCache[id]
    deleteTarget.value = ''
    deleteDisplayName.value = ''
  } finally {
    deleting.value = false
  }
}
</script>

<style scoped>
.character-directory {
  width: 220px;
  flex-shrink: 0;
  background: #fff;
  border-right: 1px solid var(--border-light);
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.directory-header {
  padding: 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border-light);
}
.directory-header h2 { font-size: 15px; margin: 0; color: var(--text-dark); }
.directory-header p { font-size: 11px; color: var(--text-light); margin-top: 2px; }
.icon-btn {
  width: 30px;
  height: 30px;
  border-radius: 6px;
  border: 1px solid var(--border-light);
  background: var(--bg-lighter);
  cursor: pointer;
  font-size: 18px;
}
.character-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.character-item {
  position: relative;
  display: flex;
  align-items: center;
  width: 100%;
  border-radius: 8px;
  border: 1px solid transparent;
  background: transparent;
}
.character-item.active {
  background: #f3f0ff;
  border-color: #ded6ff;
}
.character-main {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  text-align: left;
  padding: 9px;
  border: none;
  background: transparent;
  cursor: pointer;
}
.avatar {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: var(--bg-lighter);
  font-size: 18px;
  flex-shrink: 0;
}
.meta { display: flex; flex-direction: column; min-width: 0; }
.meta strong {
  font-size: 13px;
  color: var(--text-dark);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.meta small { font-size: 11px; color: var(--text-light); }
.item-menu-wrap { position: relative; padding-right: 7px; flex-shrink: 0; }
.more-btn {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-light);
  cursor: pointer;
  font-size: 20px;
  line-height: 1;
}
.more-btn:hover { background: rgba(99,102,241,0.08); color: var(--primary); }
.item-menu {
  position: absolute;
  right: 6px;
  top: 32px;
  z-index: 20;
  min-width: 112px;
  background: #fff;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  box-shadow: 0 10px 28px rgba(0,0,0,0.14);
  padding: 6px;
}
.item-menu button {
  width: 100%;
  border: none;
  background: transparent;
  border-radius: 6px;
  padding: 8px 10px;
  cursor: pointer;
  font-size: 12px;
  text-align: left;
  color: var(--text-dark);
}
.item-menu button:hover { background: var(--bg-lighter); }
.item-menu .danger { color: #b91c1c; }
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.42);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.modal-card {
  width: 520px;
  max-height: 86vh;
  overflow-y: auto;
  background: #fff;
  border-radius: 10px;
  padding: 20px;
  box-shadow: 0 12px 36px rgba(0,0,0,0.16);
}
.confirm-card {
  width: 360px;
  background: #fff;
  border-radius: 10px;
  padding: 20px;
  box-shadow: 0 12px 36px rgba(0,0,0,0.16);
}
.modal-card h3 { margin: 0 0 14px; font-size: 17px; }
.confirm-card h3 { margin: 0 0 10px; font-size: 17px; color: #991b1b; }
.confirm-card p { margin: 0 0 14px; font-size: 13px; line-height: 1.6; color: var(--text-dark); }
.error-text { margin-bottom: 10px; font-size: 12px; color: #b91c1c; }
.form-row { display: flex; gap: 12px; }
.form-field { display: flex; flex-direction: column; gap: 4px; flex: 1; margin-bottom: 10px; }
.form-field label { font-size: 12px; color: var(--text-light); }
.form-field input, .form-field textarea, .form-field select {
  width: 100%;
  border: 1px solid var(--border-light);
  background: var(--bg-lighter);
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 13px;
  font-family: inherit;
}
.modal-actions { display: flex; gap: 8px; margin-top: 8px; }
.modal-actions button {
  border: 1px solid var(--border-light);
  background: var(--bg-lighter);
  border-radius: 6px;
  padding: 7px 10px;
  cursor: pointer;
  font-size: 12px;
}
.modal-actions .primary {
  color: #fff;
  border: none;
  background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end));
}
.modal-actions .danger-btn {
  color: #fff;
  border: none;
  background: #dc2626;
}
.secondary-action {
  border: 1px solid var(--border-light);
  background: var(--bg-lighter);
  border-radius: 6px;
  padding: 8px 10px;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-dark);
  margin-bottom: 8px;
}
.secondary-action:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
</style>
