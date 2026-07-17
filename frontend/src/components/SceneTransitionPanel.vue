<template>
  <section class="scene-panel">
    <div class="panel-header">初始场景</div>
    <div class="panel-body">
      <textarea
        v-model="initialConcept"
        :disabled="disabled || saving"
        maxlength="4000"
        rows="3"
        placeholder="描述故事开始时希望成立的时间、地点、关系或穿着；留空则由角色自主构建"
      ></textarea>
      <select v-model="openingMode" :disabled="disabled || saving">
        <option value="character_first">角色主动打招呼</option>
        <option value="player_first">玩家先打招呼，只渲染背景</option>
      </select>
      <button class="manual-button" :disabled="disabled || saving" @click="saveInitialScene">
        {{ saving ? '保存中…' : '保存初始场景' }}
      </button>
      <button
        v-if="initialized === false"
        class="auto-button"
        :disabled="disabled || saving"
        @click="buildInitialScene"
      >
        按当前设置构建开场
      </button>
      <p class="hint">
        {{ initialized === false
          ? '当前故事尚未开始；也可以直接发送第一句话自动构建。'
          : '修改只会保存为下次重开的开场事实，不改变当前剧情。' }}
      </p>
    </div>
  </section>

  <section v-if="initialized !== false" class="scene-panel next-panel">
    <div class="panel-header">下一幕</div>
    <div class="panel-body">
      <button class="auto-button" :disabled="disabled" @click="startAuto">
        自动构建下一幕
      </button>
      <textarea
        v-model="concept"
        :disabled="disabled"
        maxlength="2000"
        rows="3"
        placeholder="描述你构想的时间、地点或情节……"
        @keydown.ctrl.enter.prevent="startManual"
      ></textarea>
      <button class="manual-button" :disabled="disabled || !concept.trim()" @click="startManual">
        按构想构建
      </button>
      <p class="hint">新场景会自动同步场景与穿着，不会强制生图。</p>
    </div>
  </section>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  disabled: Boolean,
  characterId: String,
  initialized: { type: Boolean, default: true },
})

const emit = defineEmits(['transition', 'initialize', 'saved'])
const concept = ref('')
const initialConcept = ref('')
const openingMode = ref('character_first')
const saving = ref(false)

const loadInitialScene = async () => {
  if (!props.characterId) return
  try {
    const r = await fetch(`/api/characters/${encodeURIComponent(props.characterId)}/profile`)
    if (!r.ok) return
    const profile = await r.json()
    initialConcept.value = profile.initial_scene?.concept || ''
    openingMode.value = profile.initial_scene?.opening_mode || 'character_first'
  } catch (e) {
    console.error('加载初始场景失败:', e)
  }
}

watch(() => props.characterId, loadInitialScene, { immediate: true })

const saveInitialScene = async () => {
  if (!props.characterId) return false
  saving.value = true
  try {
    const r = await fetch(`/api/characters/${encodeURIComponent(props.characterId)}/profile`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        initial_scene: {
          concept: initialConcept.value.trim(),
          opening_mode: openingMode.value,
        }
      })
    })
    if (r.ok) emit('saved')
    return r.ok
  } finally {
    saving.value = false
  }
}

const buildInitialScene = async () => {
  if (await saveInitialScene()) emit('initialize')
}

const startAuto = () => {
  emit('transition', { mode: 'auto', concept: '' })
}

const startManual = () => {
  const value = concept.value.trim()
  if (!value) return
  emit('transition', { mode: 'manual', concept: value })
  concept.value = ''
}
</script>

<style scoped>
.scene-panel {
  width: 100%; flex-shrink: 0; background: #fff;
  border-top: 1px solid var(--border-light);
}
.next-panel { border-top-color: #d9d2ef; }
.panel-header {
  padding: 9px 16px; font-size: 13px; font-weight: 600;
  color: #514675; background: #f0edff;
  border-bottom: 1px solid var(--border-light);
}
.panel-body { padding: 10px; display: grid; gap: 8px; }
textarea {
  width: 100%; min-height: 66px; resize: vertical;
  padding: 9px 10px; border: 1px solid #e4def8; border-radius: 8px;
  background: #faf9ff; color: #3b3450; font: inherit; font-size: 12px;
  line-height: 1.45; outline: none;
}
textarea:focus { border-color: #9b8ed0; box-shadow: 0 0 0 3px rgba(124, 111, 170, .1); }
select {
  width: 100%; min-height: 32px; padding: 6px 8px;
  border: 1px solid #e4def8; border-radius: 8px;
  background: #faf9ff; color: #3b3450; font: inherit; font-size: 12px;
}
button {
  min-height: 32px; border: 0; border-radius: 8px;
  font: inherit; font-size: 12px; cursor: pointer;
}
.auto-button { color: #fff; background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end)); }
.manual-button { color: #55477f; background: #eeeafd; border: 1px solid #dfd7f7; }
button:disabled, textarea:disabled { opacity: .5; cursor: not-allowed; }
.hint { margin: 0; color: #9a93ad; font-size: 10.5px; line-height: 1.4; }
</style>
