<template>
  <div class="status-bar">
    <div class="left">
      <span class="dot" :class="{ online: isConnected }"></span>
      <span class="char-name">{{ characterAvatar }} {{ characterName }}</span>
      <span class="sep">|</span>
      <span v-if="imageStatus === 'generating'" class="hint">📷 拍照中...</span>
      <span v-else class="hint">在线</span>
    </div>
    <div class="right">
      <select class="char-switch" :value="activeCharId" @change="onSwitch">
        <option v-for="c in characters" :key="c" :value="c">{{ c }}</option>
      </select>
      <button @click="$emit('refresh-memory')" class="btn" title="刷新记忆">🧠</button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  isConnected: Boolean,
  imageStatus: String,
  characterName: String,
  characterAvatar: String,
  characters: Array,
  activeCharId: String,
})
const emit = defineEmits(['refresh-memory', 'switch-character'])

const onSwitch = (e) => {
  emit('switch-character', e.target.value)
}
</script>

<style scoped>
.status-bar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 16px; background: #fff; border-bottom: 1px solid var(--border-light);
  box-shadow: 0 1px 4px rgba(0,0,0,0.03);
  font-size: 13px;
}
.left { display: flex; align-items: center; gap: 8px; color: #888; }
.right { display: flex; gap: 4px; align-items: center; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: #ccc; }
.dot.online { background: #4ade80; }
.char-name { font-weight: 600; color: #4a4a4a; }
.sep { color: #ddd; }
.hint { color: var(--primary); }
.char-switch {
  font-size: 12px; padding: 2px 6px;
  border: 1px solid var(--border-light); border-radius: 6px;
  background: #fff; color: #4a4a4a; cursor: pointer;
}
.btn {
  background: none; border: 1px solid var(--border-light); border-radius: 6px;
  padding: 4px 8px; cursor: pointer; font-size: 14px;
}
.btn:hover { background: var(--bg-lighter); }
</style>
