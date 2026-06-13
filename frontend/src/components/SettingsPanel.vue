<template>
  <div class="settings-panel" :class="{ open: isOpen }">
    <div class="toggle" @click="isOpen = !isOpen">
      {{ isOpen ? '▼' : '▲' }} 设置
    </div>
    <div v-if="isOpen" class="content">
      <div class="tabs">
        <button v-for="t in tabs" :key="t" @click="activeTab = t"
          :class="{ active: activeTab === t }">{{ t }}</button>
      </div>

      <!-- 通用 -->
      <div v-if="activeTab === '通用'" class="tab-content">
        <div class="form-field">
          <label>上下文窗口 (K)</label>
          <input v-model.number="contextWindowK" type="number" min="1" max="128" />
        </div>
        <div class="form-field">
          <label>压缩阈值</label>
          <input v-model.number="settings.context.compress_at" type="number" step="0.1" min="0.5" max="0.95" />
        </div>
      </div>

      <!-- 角色 -->
      <div v-if="activeTab === '角色'" class="tab-content">
        <div class="form-card">
          <div class="form-row">
            <div class="form-field">
              <label>名称</label>
              <input v-model="profile.name" />
            </div>
            <div class="form-field">
              <label>头像 emoji</label>
              <input v-model="profile.avatar" />
            </div>
          </div>
          <div class="form-field">
            <label>视觉锚点 (avatar_role)</label>
            <textarea v-model="profile.avatar_role" rows="2"></textarea>
          </div>
          <div class="form-field">
            <label>体型标签 (body_type)</label>
            <textarea v-model="profile.body_type" rows="2"></textarea>
          </div>
          <div class="form-field">
            <label>外貌标签 (appearance)</label>
            <textarea v-model="profile.appearance" rows="3"></textarea>
          </div>
          <button @click="onSaveProfile" class="save-btn">保存角色</button>
        </div>
        <div class="form-card" v-if="identityContent !== undefined">
          <div class="form-field">
            <label>身份设定 (identity.md)</label>
            <textarea v-model="identityContent" rows="15" style="font-family:monospace;font-size:13px;"></textarea>
          </div>
          <button @click="saveIdentity" class="save-btn">保存身份设定</button>
        </div>
        <button @click="showNewCharModal = true" class="save-btn">+ 新增角色</button>
      </div>

      <!-- 生图 -->
      <div v-if="activeTab === '生图'" class="tab-content">
        <div class="form-field">
          <label>工作流</label>
          <input v-model="settings.comfyui.workflow" />
        </div>
        <div class="form-field">
          <label>负面提示词</label>
          <textarea v-model="settings.comfyui.negative_prompt" rows="2"></textarea>
        </div>
        <div class="form-row">
          <div class="form-field">
            <label>采样器</label>
            <input v-model="settings.comfyui.sampler" />
          </div>
          <div class="form-field">
            <label>调度器</label>
            <input v-model="settings.comfyui.scheduler" />
          </div>
        </div>
        <div class="form-row">
          <div class="form-field">
            <label>步数</label>
            <input v-model.number="settings.comfyui.steps" type="number" />
          </div>
          <div class="form-field">
            <label>CFG</label>
            <input v-model.number="settings.comfyui.cfg" type="number" step="0.5" />
          </div>
        </div>
        <div class="form-row">
          <div class="form-field">
            <label>宽度</label>
            <input v-model.number="settings.comfyui.width" type="number" />
          </div>
          <div class="form-field">
            <label>高度</label>
            <input v-model.number="settings.comfyui.height" type="number" />
          </div>
        </div>
      </div>

      <!-- 记忆 -->
      <div v-if="activeTab === '记忆'" class="tab-content">
        <div class="form-field">
          <label>沉淀时间</label>
          <input v-model="settings.memory.condensation_time" />
        </div>
        <div class="form-row">
          <div class="form-field">
            <label>沉淀天数</label>
            <input v-model.number="settings.memory.condensation_days" type="number" />
          </div>
          <div class="form-field">
            <label>保留天数</label>
            <input v-model.number="settings.memory.retention_days" type="number" />
          </div>
        </div>
        <button @click="triggerCondense" class="save-btn">手动沉淀</button>
      </div>

      <!-- Heartbeat -->
      <div v-if="activeTab === 'Heartbeat'" class="tab-content">
        <div class="form-field">
          <label>间隔（分钟）</label>
          <input v-model.number="settings.heartbeat.interval_minutes" type="number" />
        </div>
        <div class="form-row">
          <div class="form-field">
            <label>静默开始</label>
            <input v-model="settings.heartbeat.quiet_start" />
          </div>
          <div class="form-field">
            <label>静默结束</label>
            <input v-model="settings.heartbeat.quiet_end" />
          </div>
        </div>
      </div>

      <!-- 模型 -->
      <div v-if="activeTab === '模型'" class="tab-content">
        <div class="form-field">
          <label>当前模型</label>
          <div style="display:flex;gap:8px;">
            <select v-model="activeProfileName" @change="onSwitchProfile" style="flex:1;">
              <option v-for="p in llmProfiles" :key="p.name" :value="p.name">{{ p.name }} — {{ p.model }}</option>
            </select>
            <button @click="editProfile(activeProfileName)" class="cancel-btn" style="white-space:nowrap;">编辑</button>
          </div>
        </div>
        <div v-if="editingProfile" class="form-card">
          <div class="form-row">
            <div class="form-field">
              <label>名称</label>
              <input v-model="editingProfile.name" />
            </div>
            <div class="form-field">
              <label>Provider</label>
              <input v-model="editingProfile.provider" />
            </div>
          </div>
          <div class="form-field">
            <label>Model</label>
            <div style="display:flex;gap:8px;">
              <input v-model="editingProfile.model" list="model-list" style="flex:1;" />
              <datalist id="model-list">
                <option v-for="m in fetchedModels" :key="m" :value="m" />
              </datalist>
              <button @click="fetchModels" class="cancel-btn" style="white-space:nowrap;">获取模型</button>
            </div>
          </div>
          <div class="form-field">
            <label>Base URL</label>
            <input v-model="editingProfile.base_url" />
          </div>
          <div class="form-field">
            <label>API Key</label>
            <input v-model="editingProfile.api_key" type="password" placeholder="留空不修改" />
          </div>
          <div class="form-row">
            <div class="form-field">
              <label>Temperature</label>
              <input v-model.number="editingProfile.temperature" type="number" step="0.1" />
            </div>
            <div class="form-field">
              <label>Max Tokens</label>
              <input v-model.number="editingProfile.max_tokens" type="number" />
            </div>
          </div>
          <div style="display:flex;gap:12px;">
            <button @click="saveProfileEdit" class="save-btn">保存模型</button>
            <button @click="deleteProfile" class="cancel-btn">删除</button>
          </div>
        </div>
        <button @click="newProfile" class="save-btn">+ 新增模型</button>
      </div>

      <div class="actions">
        <button @click="saveAll" class="save-btn">保存所有设置</button>
        <span v-if="saved" class="saved">✓ 已保存</span>
      </div>
    </div>
  </div>

  <!-- 新增角色弹窗 -->
  <div v-if="showNewCharModal" class="modal-mask" @click.self="showNewCharModal = false">
    <div class="modal-card">
      <h3>新增角色</h3>
      <div class="form-row">
        <div class="form-field">
          <label>目录名（英文）*</label>
          <input v-model="newChar.name" placeholder="sakura" />
        </div>
        <div class="form-field">
          <label>显示名</label>
          <input v-model="newChar.displayName" placeholder="小樱" />
        </div>
      </div>
      <div class="form-field">
        <label>头像 emoji</label>
        <input v-model="newChar.avatar" />
      </div>
      <div class="form-field">
        <label>视觉锚点 (avatar_role)</label>
        <textarea v-model="newChar.avatar_role" rows="2" placeholder="sakura_miku, solo"></textarea>
      </div>
      <div class="form-field">
        <label>体型标签 (body_type)</label>
        <textarea v-model="newChar.body_type" rows="2" placeholder="petite, small breasts, slim"></textarea>
      </div>
      <div class="form-field">
        <label>外貌标签 (appearance)</label>
        <textarea v-model="newChar.appearance" rows="3" placeholder="pink hair, long hair, blue eyes, twintails"></textarea>
      </div>
      <div class="form-field">
        <label>身份设定 (identity.md)</label>
        <textarea v-model="newChar.identity" rows="10" style="font-family:monospace;font-size:12px;"></textarea>
      </div>
      <div class="modal-actions">
        <button @click="createNewChar" class="save-btn" :disabled="!newChar.name">创建</button>
        <button @click="showNewCharModal = false" class="cancel-btn">取消</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useCharacter } from '../composables/useCharacter.js'

const { profile, activeCharId, saveProfile, createCharacter } = useCharacter()

const isOpen = ref(false)
const activeTab = ref('通用')
const tabs = ['通用', '角色', '生图', '记忆', 'Heartbeat', '模型']
const saved = ref(false)
const identityContent = ref('')
const identityLoaded = ref(false)
const showNewCharModal = ref(false)
const newChar = reactive({
  name: '', displayName: '', avatar: '💕',
  avatar_role: '', body_type: '', appearance: '',
  identity: ''
})

// --- 模型管理 ---
const llmProfiles = ref([])
const activeProfileName = ref('')
const editingProfile = ref(null)
const fetchedModels = ref([])

const fetchModels = async () => {
  if (!editingProfile.value || !editingProfile.value.base_url) return
  const p = editingProfile.value
  const params = `base_url=${encodeURIComponent(p.base_url)}&api_key=${encodeURIComponent(p.api_key || '')}`
  try {
    const r = await fetch(`${API}/llm/models?${params}`)
    if (r.ok) fetchedModels.value = (await r.json()).models || []
  } catch (e) { fetchedModels.value = [] }
}

const loadProfiles = async () => {
  try {
    const r = await fetch(`${API}/llm/profiles`).then(r => r.json())
    llmProfiles.value = r.profiles || []
    activeProfileName.value = r.active || ''
  } catch (e) { /* ignore */ }
}
const onSwitchProfile = async () => {
  await fetch(`${API}/llm/profiles/active`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: activeProfileName.value })
  })
  saved.value = true; setTimeout(() => saved.value = false, 2000)
}
const editProfile = (name) => {
  const p = llmProfiles.value.find(p => p.name === name)
  if (p) editingProfile.value = { ...p }
}
const newProfile = () => {
  editingProfile.value = { name: '', provider: '', model: '', base_url: '', api_key: '', temperature: 0.8, max_tokens: 2048 }
}
const saveProfileEdit = async () => {
  if (!editingProfile.value || !editingProfile.value.name) return
  const existing = llmProfiles.value.find(p => p.name === editingProfile.value.name)
  if (!existing) llmProfiles.value.push({ ...editingProfile.value })
  else Object.assign(existing, editingProfile.value)
  if (!activeProfileName.value) activeProfileName.value = editingProfile.value.name
  const body = { active: activeProfileName.value, profiles: llmProfiles.value }
  await fetch(`${API}/llm/profiles`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  editingProfile.value = null
  await loadProfiles()
  saved.value = true; setTimeout(() => saved.value = false, 2000)
}
const deleteProfile = async () => {
  if (!editingProfile.value || llmProfiles.value.length <= 1) return
  llmProfiles.value = llmProfiles.value.filter(p => p.name !== editingProfile.value.name)
  if (activeProfileName.value === editingProfile.value.name) activeProfileName.value = llmProfiles.value[0]?.name || ''
  editingProfile.value = null
  const body = { active: activeProfileName.value, profiles: llmProfiles.value }
  await fetch(`${API}/llm/profiles`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  await loadProfiles()
}

const contextWindowK = computed({
  get: () => Math.round(settings.context.max_tokens / 1000),
  set: (val) => { settings.context.max_tokens = Math.round(val * 1000) }
})

const settings = reactive({
  context: { max_tokens: 8000, compress_at: 0.7 },
  comfyui: {
    workflow: 'waiNSFWIllustrious_v140.json',
    negative_prompt: 'bad quality,worst quality,worst detail,sketch,censor',
    sampler: 'euler', scheduler: 'simple',
    steps: 20, cfg: 5.0, width: 1024, height: 1024
  },
  memory: { condensation_time: '02:00', condensation_days: 1, retention_days: 30 },
  heartbeat: { interval_minutes: 30, quiet_start: '23:00', quiet_end: '08:00' },
})

const API = '/api'

onMounted(async () => {
  try {
    const s = await fetch(`${API}/settings`).then(r => r.json())
    Object.assign(settings, s)
  } catch (e) { console.error('加载设置失败:', e) }
  try {
    const r = await fetch(`${API}/characters/${activeCharId.value}/identity`)
    if (r.ok) identityContent.value = (await r.json()).content
  } catch (e) { /* ignore */ }
  identityLoaded.value = true
  loadProfiles()
})

const onSaveProfile = async () => {
  await saveProfile()
  saved.value = true
  setTimeout(() => saved.value = false, 2000)
}

const saveIdentity = async () => {
  await fetch(`${API}/characters/${activeCharId.value}/identity`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: identityContent.value })
  })
  saved.value = true
  setTimeout(() => saved.value = false, 2000)
}

const saveAll = async () => {
  await fetch(`${API}/settings`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings)
  })
  saved.value = true
  setTimeout(() => saved.value = false, 2000)
}

const createNewChar = async () => {
  if (!newChar.name) return
  await createCharacter(newChar.name, {
    name: newChar.displayName || newChar.name,
    avatar: newChar.avatar,
    avatar_role: newChar.avatar_role,
    body_type: newChar.body_type,
    appearance: newChar.appearance,
    identity: newChar.identity,
  })
  showNewCharModal.value = false
  ;['name','displayName','avatar','avatar_role','body_type','appearance','identity'].forEach(k => newChar[k] = '')
  newChar.avatar = '💕'
}

const triggerCondense = () => {
  fetch(`${API}/memory/condense?character=${activeCharId.value}&days=${settings.memory.condensation_days}`, { method: 'POST' })
    .then(() => alert('沉淀完成'))
}
</script>

<style scoped>
.settings-panel {
  background: var(--white); border-top: 1px solid var(--border-light);
  box-shadow: 0 -2px 12px rgba(0,0,0,0.04);
}
.toggle {
  padding: 10px 16px; cursor: pointer; font-size: 13px;
  color: var(--text-light); user-select: none; text-align: center;
  font-weight: 500; transition: background var(--transition-fast);
}
.toggle:hover { background: var(--bg-lighter); color: var(--primary); }
.content { padding: 16px; max-height: 380px; overflow-y: auto; }

/* 标签页：下划线式 */
.tabs {
  display: flex; gap: 0; border-bottom: 2px solid var(--border-light);
  margin-bottom: 16px;
}
.tabs button {
  border: none; background: none; padding: 8px 16px;
  cursor: pointer; font-size: 13px; color: var(--text-light);
  border-bottom: 2px solid transparent; margin-bottom: -2px;
  transition: all var(--transition-fast);
}
.tabs button.active {
  color: var(--primary); border-bottom-color: var(--primary); font-weight: 600;
}
.tabs button:not(.active):hover { color: var(--text-dark); }

/* 表单 */
.tab-content { display: flex; flex-direction: column; gap: 12px; }

.form-field { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 0; }
.form-field label {
  font-size: 12px; font-weight: 500; color: var(--text-light);
}
.form-field input, .form-field textarea, .form-field select {
  width: 100%; padding: 8px 12px;
  border: 1px solid var(--border-light); border-radius: var(--radius-sm);
  font-size: 13px; color: var(--text-dark);
  background: var(--bg-lighter);
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
  font-family: inherit;
}
.form-field input:focus, .form-field textarea:focus {
  outline: none; border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(99,102,241,0.1);
  background: var(--white);
}
.form-field textarea { resize: vertical; min-height: 38px; }

.form-card {
  background: var(--bg-lighter); border-radius: var(--radius-sm);
  padding: 12px;
}
.form-row { display: flex; gap: 12px; }

/* 操作区 */
.actions {
  margin-top: 12px; padding-top: 12px;
  border-top: 1px solid var(--border-light);
  display: flex; align-items: center; gap: 12px;
}

.save-btn {
  background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end));
  color: #fff; border: none; padding: 8px 20px;
  border-radius: var(--radius-sm); cursor: pointer; font-size: 13px;
  font-weight: 500; align-self: flex-start;
  box-shadow: var(--shadow-sm);
  transition: transform var(--transition-fast), box-shadow var(--transition-fast);
}
.save-btn:hover { transform: translateY(-1px); box-shadow: var(--shadow-md); }
.save-btn:active { transform: translateY(0); }

.saved { color: #4ade80; font-size: 13px; font-weight: 500; }

/* 新增角色弹窗 */
.modal-mask {
  position: fixed; inset: 0; background: rgba(0,0,0,0.4);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.modal-card {
  background: #fff; border-radius: 12px; padding: 24px;
  width: 520px; max-height: 80vh; overflow-y: auto;
  box-shadow: 0 8px 32px rgba(0,0,0,0.12);
}
.modal-card h3 { margin: 0 0 16px; font-size: 18px; }
.modal-card .form-field { margin-bottom: 12px; }
.modal-actions { display: flex; gap: 12px; margin-top: 16px; }
.cancel-btn {
  background: var(--bg-lighter); border: 1px solid var(--border-light);
  padding: 8px 20px; border-radius: var(--radius-sm); cursor: pointer;
  font-size: 13px; color: var(--text-light);
}
</style>
