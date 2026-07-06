<template>
  <div class="state-panel">
    <div class="panel-header">状态</div>
    <div class="panel-body">
      <div v-if="hasSections" class="state-list">
        <div v-for="section in visibleSections" :key="section.key" class="state-item">
          <h4 class="state-title">{{ section.label }}</h4>
          <div v-if="section.key === 'outfit'" class="tag-list">
            <span v-for="item in section.items" :key="item" class="tag-pill">{{ formatTag(item) }}</span>
          </div>
          <div v-else class="line-list">
            <div v-for="item in section.items" :key="item" class="line-pill">{{ stripBullet(item) }}</div>
          </div>
        </div>
      </div>
      <div v-else class="state-empty">
        <p>连接中...</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  characterState: Object,
})

const DISPLAY_SECTIONS = [
  { key: 'outfit', label: '穿着' },
  { key: 'scene', label: '场景细节' },
  { key: 'mood', label: '心情状态' },
]

const visibleSections = computed(() => {
  const state = props.characterState
  if (!state) return []

  const all = state.status || {}
  const normalized = {
    outfit: all['穿着'],
    scene: all['场景细节'],
    mood: findMood(all),
  }

  return DISPLAY_SECTIONS
    .map(section => ({
      ...section,
      items: cleanupItems(normalized[section.key])
    }))
    .filter(section => section.items.length)
})

const hasSections = computed(() => visibleSections.value.length > 0)

const findMood = (sections) => {
  for (const [key, value] of Object.entries(sections)) {
    if ((key === '心情状态' || key.endsWith('的心情状态')) && value?.trim()) {
      return value
    }
  }
  return ''
}

const cleanupItems = (text) => {
  return String(text || '')
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
}

const stripBullet = (text) => {
  return String(text || '').replace(/^-\s*/, '')
}

const formatTag = (text) => {
  return stripBullet(text).replace(/_/g, ' ')
}
</script>

<style scoped>
.state-panel {
  width: 100%; flex: 1; min-height: 0; display: flex; flex-direction: column;
  background: linear-gradient(180deg, #fafbff 0%, #f5f0ff 100%);
}
.panel-header {
  padding: 10px 16px; font-size: 13px; font-weight: 600;
  background: #f0edff; border-bottom: 1px solid var(--border-light);
  flex-shrink: 0; letter-spacing: 0.5px;
}
.panel-body {
  flex: 1; overflow-y: auto; padding: 10px;
  display: flex; flex-direction: column; gap: 8px;
}
.state-list { display: flex; flex-direction: column; gap: 6px; }
.state-item {
  background: #fff; border-radius: 10px; padding: 10px 12px;
  border: 1px solid #eee; box-shadow: 0 1px 3px rgba(0,0,0,.03);
}
.state-title {
  font-size: 11.5px; font-weight: 600; color: #7c6faa;
  margin: 0 0 8px; text-transform: none; letter-spacing: 0.3px;
}
.tag-list {
  display: flex; flex-wrap: wrap; gap: 6px;
}
.tag-pill {
  display: inline-flex; align-items: center;
  min-height: 24px; max-width: 100%;
  padding: 4px 8px; border-radius: 6px;
  background: #f5f3ff; border: 1px solid #e7e1ff;
  color: #403957; font-size: 11px; line-height: 1.35;
  word-break: break-word;
}
.line-list {
  display: flex; flex-direction: column; gap: 5px;
}
.line-pill {
  padding: 6px 8px; border-radius: 6px;
  background: #faf9ff; border: 1px solid #eeeafd;
  color: #3b3450; font-size: 11px; line-height: 1.45;
  white-space: pre-wrap; word-break: break-word;
}
.state-empty {
  text-align: center; color: #c0b8d8; font-size: 12px; padding: 24px 0;
}
</style>
