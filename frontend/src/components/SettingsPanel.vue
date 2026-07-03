<template>
  <div class="settings-panel" :class="{ open: isOpen }">
    <div class="toggle" @click="isOpen = !isOpen">
      {{ isOpen ? '▼' : '▲' }} 设置
    </div>
    <div v-if="isOpen" class="content">
      <div class="tabs">
        <button v-for="t in tabs" :key="t" @click="activeTab = t" :class="{ active: activeTab === t }">{{ t }}</button>
      </div>

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

      <div v-if="activeTab === '角色'" class="tab-content">
        <div class="form-card">
          <div class="form-row">
            <div class="form-field">
              <label>角色 ID</label>
              <input :value="activeCharId" disabled />
            </div>
            <div class="form-field">
              <label>名称</label>
              <input v-model="profile.name" />
            </div>
            <div class="form-field">
              <label>性别</label>
              <select v-model="profile.gender">
                <option value="female">female</option>
                <option value="male">male</option>
                <option value="other">other</option>
              </select>
            </div>
          </div>
          <div class="form-field">
            <label>头像 emoji</label>
            <input v-model="profile.avatar" />
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
      </div>

      <div v-if="activeTab === '用户'" class="tab-content">
        <div class="form-card">
          <div class="form-field">
            <label>当前称呼</label>
            <input v-model="userProfile.user_pet_name" :placeholder="`${profile.name || activeCharId}当前对用户的称呼`" />
          </div>
          <div class="form-field">
            <label>用户身份描述</label>
            <textarea v-model="userProfile.identity" rows="4" placeholder="描述用户是谁、处在什么角色和关系位置"></textarea>
          </div>
          <div class="form-field">
            <label>沟通偏好</label>
            <textarea v-model="userProfile.communication_style" rows="2" placeholder="例如：喜欢直接一点、喜欢被温柔提醒"></textarea>
          </div>
          <div class="form-field">
            <label>备注</label>
            <textarea v-model="userProfile.notes" rows="3" placeholder="只写稳定的基础信息；喜欢、不喜欢和重要事件会沉淀到长期记忆"></textarea>
          </div>
          <button @click="saveUserProfile" class="save-btn">保存用户信息</button>
        </div>
      </div>

      <div v-if="activeTab === '皮肤'" class="tab-content">
        <div class="form-card">
          <div class="form-field">
            <label>皮肤名称</label>
            <input v-model="profile.visual_anchor.preset_name" placeholder="可选，例如：初音未来皮肤" />
          </div>
          <div class="form-field">
            <label>角色锚点标签</label>
            <textarea v-model="profile.avatar_role" rows="2" placeholder="danbooru 角色名或稳定识别标签，例如 hatsune_miku, solo"></textarea>
          </div>
          <div class="form-field">
            <label>体型标签</label>
            <textarea v-model="profile.body_type" rows="2" placeholder="petite, small breasts, slim"></textarea>
          </div>
          <div class="form-field">
            <label>外貌标签</label>
            <textarea v-model="profile.appearance" rows="3" placeholder="green hair, twintails, blue eyes"></textarea>
          </div>
          <button @click="saveSkin" class="save-btn">保存皮肤</button>
        </div>
      </div>

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
          <div class="form-field"><label>采样器</label><input v-model="settings.comfyui.sampler" /></div>
          <div class="form-field"><label>调度器</label><input v-model="settings.comfyui.scheduler" /></div>
        </div>
        <div class="form-row">
          <div class="form-field"><label>步数</label><input v-model.number="settings.comfyui.steps" type="number" /></div>
          <div class="form-field"><label>CFG</label><input v-model.number="settings.comfyui.cfg" type="number" step="0.5" /></div>
        </div>
        <div class="form-row">
          <div class="form-field"><label>宽度</label><input v-model.number="settings.comfyui.width" type="number" /></div>
          <div class="form-field"><label>高度</label><input v-model.number="settings.comfyui.height" type="number" /></div>
        </div>
      </div>

      <div v-if="activeTab === '记忆'" class="tab-content">
        <div class="form-field">
          <label>每几轮沉淀</label>
          <input v-model.number="settings.memory.turns_per_condense" type="number" min="0" />
        </div>
        <div class="form-row">
          <div class="form-field"><label>沉淀天数</label><input v-model.number="settings.memory.condensation_days" type="number" /></div>
          <div class="form-field"><label>保留天数</label><input v-model.number="settings.memory.retention_days" type="number" /></div>
        </div>
        <button @click="triggerCondense" class="save-btn">手动沉淀</button>
        <div class="form-card">
          <div class="form-field">
            <label>长期记忆 (long_term.md)</label>
            <textarea v-model="longTermContent" rows="12" style="font-family:monospace;font-size:13px;"></textarea>
          </div>
          <button @click="saveLongTerm" class="save-btn">保存长期记忆</button>
        </div>
      </div>

      <div v-if="activeTab === 'Heartbeat'" class="tab-content">
        <div class="form-field">
          <label>间隔（分钟）</label>
          <input v-model.number="settings.heartbeat.interval_minutes" type="number" />
        </div>
        <div class="form-row">
          <div class="form-field"><label>静默开始</label><input v-model="settings.heartbeat.quiet_start" /></div>
          <div class="form-field"><label>静默结束</label><input v-model="settings.heartbeat.quiet_end" /></div>
        </div>
      </div>

      <div v-if="activeTab === '模型'" class="tab-content">
        <div class="form-card">
          <div style="font-size:13px;font-weight:600;margin-bottom:8px;color:var(--text-dark);">供应商密钥</div>
          <div v-if="providers.length === 0" style="color:var(--text-light);font-size:12px;">暂无供应商，创建模型时会自动出现</div>
          <div v-for="pv in providers" :key="pv.name" style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
            <span style="font-size:13px;flex:1;">{{ pv.name }}</span>
            <span :style="{fontSize:'11px',color:pv.has_key?'#4ade80':'#f59e0b'}">{{ pv.has_key ? '已设置' : '未设置' }}</span>
            <button @click="editingProviderKey = (editingProviderKey === pv.name ? null : pv.name); newProviderKey = ''" class="cancel-btn" style="font-size:11px;padding:4px 10px;">
              {{ editingProviderKey === pv.name ? '取消' : pv.has_key ? '修改' : '设置' }}
            </button>
          </div>
          <div v-if="editingProviderKey" style="display:flex;gap:8px;margin-top:8px;">
            <input v-model="newProviderKey" type="password" :placeholder="editingProviderKey + ' 的 API Key'" style="flex:1;padding:6px 10px;border:1px solid var(--border-light);border-radius:var(--radius-sm);font-size:12px;" />
            <button @click="saveProviderKey(editingProviderKey)" class="save-btn" style="font-size:11px;padding:6px 14px;">保存密钥</button>
          </div>
        </div>

        <div class="form-field">
          <label>当前模型</label>
          <div style="display:flex;gap:8px;">
            <select v-model="activeProfileName" @change="onSwitchProfile" style="flex:1;">
              <option v-for="p in llmProfiles" :key="p.name" :value="p.name">{{ p.name }} - {{ p.model }}</option>
            </select>
            <button @click="editProfile(activeProfileName)" class="cancel-btn" style="white-space:nowrap;">编辑</button>
          </div>
        </div>
        <div v-if="editingProfile" class="form-card">
          <div class="form-row">
            <div class="form-field"><label>名称</label><input v-model="editingProfile.name" /></div>
            <div class="form-field"><label>Provider</label><input v-model="editingProfile.provider" /></div>
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
          <div class="form-field"><label>Base URL</label><input v-model="editingProfile.base_url" /></div>
          <div class="form-row">
            <div class="form-field"><label>Temperature</label><input v-model.number="editingProfile.temperature" type="number" step="0.1" /></div>
            <div class="form-field"><label>Max Tokens</label><input v-model.number="editingProfile.max_tokens" type="number" /></div>
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
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useCharacter } from '../composables/useCharacter.js'

const { profile, activeCharId, saveProfile } = useCharacter()

const API = '/api'
const isOpen = ref(false)
const activeTab = ref('通用')
const tabs = ['通用', '角色', '用户', '皮肤', '生图', '记忆', 'Heartbeat', '模型']
const saved = ref(false)
const identityContent = ref('')
const longTermContent = ref('')
const userProfile = reactive({ user_pet_name: '', identity: '', communication_style: '', notes: '' })

const llmProfiles = ref([])
const activeProfileName = ref('')
const editingProfile = ref(null)
const fetchedModels = ref([])
const providers = ref([])
const editingProviderKey = ref(null)
const newProviderKey = ref('')

const settings = reactive({
  context: { max_tokens: 8000, compress_at: 0.7 },
  comfyui: {
    workflow: 'waiNSFWIllustrious_v140.json',
    negative_prompt: 'bad quality,worst quality,worst detail,sketch,censor',
    sampler: 'euler',
    scheduler: 'simple',
    steps: 20,
    cfg: 5.0,
    width: 1024,
    height: 1024
  },
  memory: {
    condensation_days: 1,
    retention_days: 30,
    turns_per_condense: 15,
    vector_recall_enabled: true,
    vector_top_k: 5,
    vector_max_distance: 0.55
  },
  heartbeat: { interval_minutes: 30, quiet_start: '23:00', quiet_end: '08:00' },
})

const contextWindowK = computed({
  get: () => Math.round(settings.context.max_tokens / 1000),
  set: (val) => { settings.context.max_tokens = Math.round(val * 1000) }
})

const showSaved = () => {
  saved.value = true
  setTimeout(() => saved.value = false, 2000)
}

const loadProviders = async () => {
  try {
    const r = await fetch(`${API}/llm/providers`).then(r => r.json())
    providers.value = r.providers || []
  } catch (e) { /* ignore */ }
}

const saveProviderKey = async (providerName) => {
  await fetch(`${API}/llm/providers/${encodeURIComponent(providerName)}/key`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key: newProviderKey.value })
  })
  newProviderKey.value = ''
  editingProviderKey.value = null
  await loadProviders()
}

const fetchModels = async () => {
  if (!editingProfile.value || !editingProfile.value.base_url) return
  const p = editingProfile.value
  const params = `base_url=${encodeURIComponent(p.base_url)}&provider=${encodeURIComponent(p.provider || '')}`
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
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: activeProfileName.value })
  })
  showSaved()
}

const editProfile = (name) => {
  const p = llmProfiles.value.find(p => p.name === name)
  if (p) editingProfile.value = { ...p }
}

const newProfile = () => {
  editingProfile.value = { name: '', provider: '', model: '', base_url: '', temperature: 0.8, max_tokens: 2048 }
}

const saveProfileEdit = async () => {
  if (!editingProfile.value || !editingProfile.value.name) return
  const clean = { ...editingProfile.value }
  delete clean.api_key
  const existing = llmProfiles.value.find(p => p.name === clean.name)
  if (!existing) llmProfiles.value.push({ ...clean })
  else Object.assign(existing, clean)
  if (!activeProfileName.value) activeProfileName.value = clean.name
  const profiles = llmProfiles.value.map(p => { const { api_key, ...rest } = p; return rest })
  await fetch(`${API}/llm/profiles`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ active: activeProfileName.value, profiles })
  })
  editingProfile.value = null
  await loadProfiles()
  await loadProviders()
  showSaved()
}

const deleteProfile = async () => {
  if (!editingProfile.value || llmProfiles.value.length <= 1) return
  llmProfiles.value = llmProfiles.value.filter(p => p.name !== editingProfile.value.name)
  if (activeProfileName.value === editingProfile.value.name) activeProfileName.value = llmProfiles.value[0]?.name || ''
  editingProfile.value = null
  await fetch(`${API}/llm/profiles`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ active: activeProfileName.value, profiles: llmProfiles.value })
  })
  await loadProfiles()
}

const loadCharacterDocs = async () => {
  const char = activeCharId.value
  if (!char) return
  try {
    const r = await fetch(`${API}/characters/${char}/identity`)
    if (r.ok) identityContent.value = (await r.json()).content
  } catch (e) { /* ignore */ }
  try {
    const r = await fetch(`${API}/characters/${char}/user-profile`)
    if (r.ok) Object.assign(userProfile, { user_pet_name: '', identity: '', communication_style: '', notes: '' }, await r.json())
  } catch (e) { /* ignore */ }
  try {
    const r = await fetch(`${API}/characters/${char}/long-term`)
    if (r.ok) longTermContent.value = (await r.json()).content
  } catch (e) { /* ignore */ }
}

onMounted(async () => {
  try {
    const s = await fetch(`${API}/settings`).then(r => r.json())
    Object.assign(settings, s)
  } catch (e) { console.error('加载设置失败:', e) }
  await loadCharacterDocs()
  await loadProfiles()
  await loadProviders()
})

watch(activeCharId, loadCharacterDocs)

const onSaveProfile = async () => {
  await saveProfile()
  showSaved()
}

const saveSkin = async () => {
  profile.visual_anchor = {
    preset_name: profile.visual_anchor?.preset_name || '',
    role_tags: profile.avatar_role || '',
    body_tags: profile.body_type || '',
    appearance_tags: profile.appearance || '',
  }
  await saveProfile()
  showSaved()
}

const saveIdentity = async () => {
  await fetch(`${API}/characters/${activeCharId.value}/identity`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: identityContent.value })
  })
  showSaved()
}

const saveUserProfile = async () => {
  await fetch(`${API}/characters/${activeCharId.value}/user-profile`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(userProfile)
  })
  showSaved()
}

const saveLongTerm = async () => {
  await fetch(`${API}/characters/${activeCharId.value}/long-term`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: longTermContent.value })
  })
  showSaved()
}

const saveAll = async () => {
  await fetch(`${API}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings)
  })
  showSaved()
}

const triggerCondense = () => {
  fetch(`${API}/memory/condense?character=${activeCharId.value}&days=${settings.memory.condensation_days}`, { method: 'POST' })
    .then(() => alert('沉淀完成'))
}
</script>

<style scoped>
.settings-panel {
  background: var(--white);
  border-top: 1px solid var(--border-light);
  box-shadow: 0 -2px 12px rgba(0,0,0,0.04);
}
.toggle {
  padding: 10px 16px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-light);
  user-select: none;
  text-align: center;
  font-weight: 500;
  transition: background var(--transition-fast);
}
.toggle:hover { background: var(--bg-lighter); color: var(--primary); }
.content { padding: 16px; max-height: 380px; overflow-y: auto; }
.tabs {
  display: flex;
  gap: 0;
  border-bottom: 2px solid var(--border-light);
  margin-bottom: 16px;
}
.tabs button {
  border: none;
  background: none;
  padding: 8px 16px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-light);
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  transition: all var(--transition-fast);
}
.tabs button.active {
  color: var(--primary);
  border-bottom-color: var(--primary);
  font-weight: 600;
}
.tabs button:not(.active):hover { color: var(--text-dark); }
.tab-content { display: flex; flex-direction: column; gap: 12px; }
.form-field { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 0; }
.form-field label { font-size: 12px; font-weight: 500; color: var(--text-light); }
.form-field input, .form-field textarea, .form-field select {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--text-dark);
  background: var(--bg-lighter);
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
  font-family: inherit;
}
.form-field input:focus, .form-field textarea:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(99,102,241,0.1);
  background: var(--white);
}
.form-field textarea { resize: vertical; min-height: 38px; }
.form-card { background: var(--bg-lighter); border-radius: var(--radius-sm); padding: 12px; }
.form-row { display: flex; gap: 12px; }
.actions {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  gap: 12px;
}
.save-btn {
  background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end));
  color: #fff;
  border: none;
  padding: 8px 20px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  align-self: flex-start;
  box-shadow: var(--shadow-sm);
  transition: transform var(--transition-fast), box-shadow var(--transition-fast);
}
.save-btn:hover { transform: translateY(-1px); box-shadow: var(--shadow-md); }
.save-btn:active { transform: translateY(0); }
.save-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.saved { color: #4ade80; font-size: 13px; font-weight: 500; }
.cancel-btn {
  background: var(--bg-lighter);
  border: 1px solid var(--border-light);
  padding: 8px 20px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 13px;
  color: var(--text-light);
}
</style>
