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

  <div v-if="creating" class="modal-mask" @click.self="closeModal">
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
        <input v-model="form.avatar" />
      </div>
      <div class="form-field">
        <label>皮肤名称</label>
        <input v-model="form.preset_name" />
      </div>
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
      <div class="modal-actions">
        <button class="primary" @click="saveModal" :disabled="!form.id">创建</button>
        <button @click="closeModal">取消</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import { useCharacter } from '../composables/useCharacter.js'

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
const form = reactive(defaultForm())

watch(characters, refreshProfiles, { immediate: true, deep: true })

function defaultForm() {
  return {
    id: '',
    name: '',
    avatar: '💕',
    preset_name: '',
    role_tags: '',
    body_tags: '',
    appearance_tags: '',
    identity: '',
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

async function saveModal() {
  if (!form.id) return
  await createCharacter(form.id, {
    name: form.name || form.id,
    avatar: form.avatar,
    visual_anchor: {
      preset_name: form.preset_name,
      role_tags: form.role_tags,
      body_tags: form.body_tags,
      appearance_tags: form.appearance_tags,
    },
    identity: form.identity,
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
  const displayName = profileCache[id]?.name || id
  if (!confirm(`确认删除角色「${displayName}」？这会删除该角色的设定、记忆、聊天记录和图片数据。`)) return
  await deleteCharacter(id)
  delete profileCache[id]
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
.modal-card h3 { margin: 0 0 14px; font-size: 17px; }
.form-row { display: flex; gap: 12px; }
.form-field { display: flex; flex-direction: column; gap: 4px; flex: 1; margin-bottom: 10px; }
.form-field label { font-size: 12px; color: var(--text-light); }
.form-field input, .form-field textarea {
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
</style>
