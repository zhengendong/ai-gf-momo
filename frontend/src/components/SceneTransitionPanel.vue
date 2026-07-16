<template>
  <section class="scene-panel">
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
import { ref } from 'vue'

defineProps({
  disabled: Boolean,
})

const emit = defineEmits(['transition'])
const concept = ref('')

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
button {
  min-height: 32px; border: 0; border-radius: 8px;
  font: inherit; font-size: 12px; cursor: pointer;
}
.auto-button { color: #fff; background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end)); }
.manual-button { color: #55477f; background: #eeeafd; border: 1px solid #dfd7f7; }
button:disabled, textarea:disabled { opacity: .5; cursor: not-allowed; }
.hint { margin: 0; color: #9a93ad; font-size: 10.5px; line-height: 1.4; }
</style>
