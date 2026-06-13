<template>
  <div class="state-panel">
    <div class="panel-header">💕 状态</div>
    <div class="panel-body">
      <div v-if="hasSections" class="state-list">
        <div v-for="(text, title) in visibleSections" :key="title" class="state-item">
          <h4 class="state-title">{{ sectionIcon(title) }} {{ title }}</h4>

          <!-- 键值对：每行 emoji + key + value -->
          <div v-if="textMode(text) === 'kv'" class="kv-rows">
            <div v-for="(val, key) in parseTags(text)" :key="key" class="kv-row">
              <span class="kv-emoji">{{ keyIcon(key) }}</span>
              <span class="kv-label">{{ key }}</span>
              <span class="kv-value">{{ formatVal(val) }}</span>
            </div>
          </div>

          <!-- 标签串：逗号分隔的英文 → 小 chips -->
          <div v-else-if="textMode(text) === 'chips'" class="chip-list">
            <span v-for="item in splitChips(text)" :key="item" class="chip">{{ formatVal(item) }}</span>
          </div>

          <!-- 普通文字：排版优化 -->
          <p v-else class="prose-text">{{ text }}</p>
        </div>
      </div>
      <div v-else class="state-empty">
        <span>🌸</span>
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

const SECTION_ORDER = ['穿着', '场景细节', '小桃的心情状态', '当前目标', '想做的事']

const visibleSections = computed(() => {
  const state = props.characterState
  if (!state) return {}
  const all = { ...(state.status || {}), ...(state.plans || {}) }
  const result = {}
  for (const key of SECTION_ORDER) {
    if (all[key] && all[key].trim()) result[key] = all[key]
  }
  for (const [key, val] of Object.entries(all)) {
    if (!result[key] && val && val.trim()) result[key] = val
  }
  return result
})

const hasSections = computed(() => Object.keys(visibleSections.value).length > 0)

// ── 文本分类 ──
const DICT_RE  = /^\{.+\}$/
const LIST_RE  = /^(?:-\s*[^\n：:]+\s*[：:][^\n]*\n?)+$/s
const CHIPS_RE = /^[a-z_]+(?:\s*,\s*[a-z_]+)+$/i   // 纯英文逗号串，如 "shy_expression, blushing"
const SHORT_RE = /^[a-z_]+$/i                        // 单个英文词，如 "standing"

const textMode = (text) => {
  const t = text.trim()
  if (DICT_RE.test(t) || LIST_RE.test(t)) return 'kv'
  if (CHIPS_RE.test(t)) return 'chips'
  return 'text'
}

// ── 解析 kv ──
const parseTags = (text) => {
  const t = text.trim()
  if (DICT_RE.test(t)) {
    try {
      const json = t.replace(/'/g, '"').replace(/,\s*}/g, '}')
      return JSON.parse(json)
    } catch { /* fall through */ }
  }
  const result = {}
  for (const line of t.split('\n')) {
    const m = line.match(/^-\s*([^：:\n]+)\s*[：:]\s*(.+)/)
    if (m) result[m[1].trim()] = m[2].trim()
  }
  return result
}

// ── 解析 chips ──
const splitChips = (text) => {
  return text.split(',').map(s => s.trim()).filter(Boolean)
}

// ── 格式化 ──
const formatVal = (val) => {
  return String(val)
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
}

// ── 图标映射（尽量全） ──
const ICON_MAP = {
  '外貌': '✨',   '穿着': '👗',   '姿势/动作': '🧍', '姿势': '🧍',
  '动作': '🏃',   '场景细节': '🌆', '场景': '🌆',
  '表情': '😊',   '心情': '💖',   '心情状态': '💖',
  '小桃的心情状态': '💖', '当前目标': '🎯', '想做的事': '📝',
  '计划': '📋',   '备注': '💬',
}
const sectionIcon = (t) => ICON_MAP[t] || '📌'

const KEY_ICONS = {
  '上衣': '👚', '下衣': '👗', '鞋子': '👠', '袜子': '🧦',
  '配饰': '💍', '项链': '📿', '项圈': '⛓️', '头饰': '👑',
  '发型': '💇', '发色': '🎨', '发长': '📏', '面容': '😊',
  '瞳色': '👁️', '肤色': '🤝', '体型': '📐',
  '房间': '🏠', '地点': '📍', '环境': '🌳', '光线': '☀️',
  '时间段': '🕐', '天气': '🌤️', '季节': '🍂', '温度': '🌡️',
  '其他': '📎', '特征': '🏷️',
}
const keyIcon = (k) => KEY_ICONS[k] || '▸'
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

/* ── 卡片 ── */
.state-list { display: flex; flex-direction: column; gap: 6px; }
.state-item {
  background: #fff; border-radius: 10px; padding: 10px 12px;
  border: 1px solid #eee; box-shadow: 0 1px 3px rgba(0,0,0,.03);
}
.state-title {
  font-size: 11.5px; font-weight: 600; color: #7c6faa;
  margin: 0 0 8px; text-transform: none; letter-spacing: 0.3px;
}

/* ── 键值行 ── */
.kv-rows {
  display: flex; flex-direction: column; gap: 4px;
}
.kv-row {
  display: flex; align-items: baseline; gap: 6px;
  padding: 3px 0;
}
.kv-emoji { font-size: 13px; flex-shrink: 0; width: 18px; text-align: center; }
.kv-label {
  font-size: 10.5px; font-weight: 500; color: #a094c0;
  flex-shrink: 0; min-width: 28px;
}
.kv-label::after { content: '·'; margin-left: 4px; color: #d0c8e8; }
.kv-value {
  font-size: 11px; line-height: 1.45; color: #3b3450;
}

/* ── Chips ── */
.chip-list { display: flex; flex-wrap: wrap; gap: 4px; }
.chip {
  display: inline-block; font-size: 10.5px;
  background: #f3f0ff; color: #5e5290; border-radius: 6px;
  padding: 2px 8px; line-height: 1.5;
}

/* ── 普通文字 ── */
.prose-text {
  font-size: 11px; line-height: 1.6; color: #3b3450;
  margin: 0; white-space: pre-line;
}

/* ── 空状态 ── */
.state-empty {
  text-align: center; color: #c0b8d8; font-size: 12px; padding: 24px 0;
}
.state-empty span { font-size: 24px; display: block; margin-bottom: 6px; }
</style>
