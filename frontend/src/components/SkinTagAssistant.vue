<template>
  <div class="skin-assistant">
    <div class="lookup-row">
      <div class="lookup-field">
        <label>{{ label }}</label>
        <input
          v-model.trim="query"
          :placeholder="placeholder"
          @input="scheduleSearch"
          @focus="scheduleSearch"
        />
      </div>
      <button type="button" class="secondary-btn" @click="searchNow" :disabled="loading || !query">
        {{ loading ? '搜索中' : '搜索' }}
      </button>
    </div>

    <div v-if="results.length" class="result-list">
      <button
        v-for="item in results"
        :key="`${item.series}-${item.name_en}-${item.name_cn}`"
        type="button"
        class="result-item"
        @click="apply(item)"
      >
        <span class="result-title">
          <strong>{{ item.name_cn || item.name_en }}</strong>
          <small>{{ item.name_en }}</small>
        </span>
        <span class="series">{{ item.series }}</span>
      </button>
    </div>

    <div v-if="selected" class="selected-line">
      已套用 {{ selected.name_cn || selected.name_en }}
      <span v-if="selected.series"> · {{ selected.series }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  label: { type: String, default: '角色标签检索' },
  placeholder: { type: String, default: '输入中文名 / 英文名 / IP 名' },
})

const emit = defineEmits(['apply'])

const query = ref('')
const results = ref([])
const selected = ref(null)
const loading = ref(false)
let timer = null

function scheduleSearch() {
  window.clearTimeout(timer)
  timer = window.setTimeout(searchNow, 220)
}

async function searchNow() {
  if (!query.value) {
    results.value = []
    return
  }
  loading.value = true
  try {
    const r = await fetch(`/api/skin-mapping/search?q=${encodeURIComponent(query.value)}&limit=12`)
    const data = await r.json()
    results.value = data.results || []
  } catch (e) {
    results.value = []
  } finally {
    loading.value = false
  }
}

function apply(item) {
  selected.value = item
  results.value = []
  query.value = item.name_cn || item.name_en || ''
  emit('apply', item)
}
</script>

<style scoped>
.skin-assistant {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 10px;
}
.lookup-row {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
.lookup-field {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}
.lookup-field label {
  font-size: 12px;
  color: var(--text-light);
}
.lookup-field input {
  width: 100%;
  border: 1px solid var(--border-light);
  background: var(--bg-lighter);
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 13px;
  font-family: inherit;
}
.secondary-btn {
  border: 1px solid var(--border-light);
  background: var(--bg-lighter);
  border-radius: 6px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-dark);
}
.secondary-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.result-list {
  max-height: 176px;
  overflow-y: auto;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 8px 24px rgba(0,0,0,0.08);
}
.result-item {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border: none;
  border-bottom: 1px solid var(--border-light);
  background: transparent;
  cursor: pointer;
  text-align: left;
}
.result-item:last-child {
  border-bottom: none;
}
.result-item:hover {
  background: var(--bg-lighter);
}
.result-title {
  display: flex;
  min-width: 0;
  flex-direction: column;
}
.result-title strong,
.result-title small,
.series {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.result-title strong {
  font-size: 13px;
  color: var(--text-dark);
}
.result-title small,
.series,
.selected-line {
  font-size: 11px;
  color: var(--text-light);
}
.series {
  flex-shrink: 0;
  max-width: 42%;
}
</style>
