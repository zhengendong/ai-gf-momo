<template>
  <div class="image-panel">
    <div class="panel-header">📷 照片</div>
    <div class="panel-body">
      <!-- 空闲 + 无历史 → 角色卡片 -->
      <div v-if="status === 'idle' && !displayImage" class="idle-state">
        <div class="idle-card">
          <div class="idle-avatar">{{ characterAvatar || '💕' }}</div>
          <h3 class="idle-name">{{ characterName }}</h3>
          <div class="idle-traits" v-if="avatarRole || bodyType">
            <span v-if="avatarRole" class="trait-tag">{{ avatarRole.split(',')[0].trim() }}</span>
            <span v-if="bodyType" class="trait-tag">{{ bodyType.split(',')[0].trim() }}</span>
          </div>
          <p class="idle-tip">💡 在聊天中让{{ characterName }}拍照吧～</p>
        </div>
        <div class="idle-pattern">
          <span>🌸</span><span>✨</span><span>💕</span>
        </div>
      </div>

      <!-- 生成中 -->
      <div v-else-if="status === 'generating'" class="generating">
        <div class="spinner"></div>
        <p>{{ characterName }}正在拍照...</p>
      </div>

      <!-- 失败 -->
      <div v-else-if="status === 'error'" class="placeholder">
        <span>😢</span>
        <p>拍照失败了</p>
      </div>

      <!-- 有图可显示 -->
      <div v-else-if="displayImage" class="image-area">
        <div class="image-container">
          <img
            :src="displayImage.image_url"
            :alt="characterName + '的照片'"
            class="image"
            :class="{ hidden: !isImageVisible }"
          />
          <button
            class="hide-btn"
            @click="isImageVisible = !isImageVisible"
            :title="isImageVisible ? '隐藏照片' : '显示照片'"
          >
            {{ isImageVisible ? '👁️' : '👁️‍🗨️' }}
          </button>
          <div v-if="!isImageVisible" class="hidden-overlay">
            <span>🔒</span>
            <p>已隐藏</p>
          </div>
        </div>

        <!-- 历史导航 -->
        <div v-if="hasMultiple" class="nav-bar">
          <button class="nav-btn" :disabled="!canGoPrev" @click="goToPrev" title="上一张">◀</button>
          <span class="nav-pos">{{ position }}</span>
          <button class="nav-btn" :disabled="!canGoNext" @click="goToNext" title="下一张">▶</button>
        </div>
      </div>
    </div>
    <div v-if="statusText" class="panel-footer" :class="footerClass">
      <span class="footer-dot"></span>
      <span class="footer-text">{{ statusText }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useImageHistory } from '../composables/useImageHistory.js'

const props = defineProps({
  status: { type: String, default: 'idle' },
  imageUrl: String,
  statusText: String,
  characterName: { type: String, default: '...' },
  characterAvatar: String,
  avatarRole: String,
  bodyType: String,
  appearance: String,
})

const { currentImage: displayImage, hasMultiple, position, canGoPrev, canGoNext, fetchHistory, addImage, goToPrev, goToNext } = useImageHistory()

const isImageVisible = ref(true)

onMounted(() => {
  fetchHistory(50)
})

// 新图到达时加入历史
watch([() => props.imageUrl, () => props.status], ([url, st]) => {
  if (url && st === 'done') {
    addImage(url)
  }
})

const footerClass = computed(() => {
  if (props.status === 'generating') return 'footer-active'
  if (props.status === 'done') return 'footer-done'
  if (props.status === 'error') return 'footer-error'
  return ''
})
</script>

<style scoped>
.image-panel {
  width: 100%; flex: 0 0 auto; display: flex; flex-direction: column;
  max-height: 360px;
  background: linear-gradient(180deg, #ffffff 0%, var(--bg-lighter) 100%);
  border-bottom: 1px solid var(--border-light);
}
.panel-header {
  padding: 12px 16px; font-size: 14px; font-weight: 600;
  background: var(--bg-lighter); border-bottom: 1px solid var(--border-light);
}
.panel-body {
  flex: 1; display: flex; align-items: center; justify-content: center;
  padding: 16px; overflow: auto;
}

/* 空闲态 */
.idle-state {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 20px;
  text-align: center; width: 100%;
}
.idle-card {
  background: linear-gradient(135deg, #f0f4ff 0%, #faf5ff 50%, #fff5f5 100%);
  border-radius: var(--radius-md); padding: 24px 16px;
  box-shadow: var(--shadow-sm); width: 100%;
}
.idle-avatar { font-size: 40px; margin-bottom: 8px; }
.idle-name { font-size: 16px; font-weight: 600; color: var(--text-dark); margin: 0 0 8px; }
.idle-traits { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; margin-bottom: 12px; }
.trait-tag {
  background: var(--accent-soft); color: var(--primary);
  padding: 2px 10px; border-radius: 12px; font-size: 12px;
}
.idle-tip { font-size: 12px; color: var(--text-light); margin: 0; }
.idle-pattern { display: flex; gap: 16px; font-size: 20px; opacity: 0.25; }

/* 生成中 */
.generating { text-align: center; color: var(--primary); font-size: 13px; }
.spinner {
  width: 32px; height: 32px; border: 3px solid var(--border-light);
  border-top-color: var(--primary); border-radius: 50%; margin: 0 auto 12px;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* 失败 */
.placeholder { text-align: center; color: #ccc; font-size: 13px; }
.placeholder span { font-size: 36px; display: block; margin-bottom: 8px; }

/* 图片区域 */
.image-area { display: flex; flex-direction: column; flex: 1; min-height: 0; }

/* 图片容器 */
.image-container {
  position: relative; flex: 1; min-height: 0;
  display: flex; align-items: center; justify-content: center;
}
.image {
  max-width: 100%; max-height: 100%; object-fit: contain;
  border-radius: var(--radius-md); box-shadow: var(--shadow-md);
  transition: filter var(--transition-normal), opacity var(--transition-normal);
}
.image.hidden { filter: blur(24px); opacity: 0.2; }

/* 隐藏按钮 */
.hide-btn {
  position: absolute; top: 8px; right: 8px;
  width: 36px; height: 36px; border-radius: 50%;
  border: none; background: rgba(0,0,0,0.45); color: #fff;
  font-size: 16px; cursor: pointer; display: flex;
  align-items: center; justify-content: center;
  transition: background var(--transition-fast);
}
.hide-btn:hover { background: rgba(0,0,0,0.65); }

/* 隐藏遮罩 */
.hidden-overlay {
  position: absolute; inset: 0; display: flex;
  flex-direction: column; align-items: center; justify-content: center;
  color: var(--text-light); font-size: 13px; pointer-events: none;
}
.hidden-overlay span { font-size: 28px; margin-bottom: 4px; }

/* 历史导航 */
.nav-bar {
  display: flex; align-items: center; justify-content: center; gap: 12px;
  padding: 6px 0;
}
.nav-btn {
  width: 28px; height: 28px; border-radius: 50%;
  border: 1px solid var(--border-light); background: var(--white); color: var(--text-dark);
  font-size: 12px; cursor: pointer; display: flex;
  align-items: center; justify-content: center;
  transition: background var(--transition-fast);
}
.nav-btn:hover:not(:disabled) { background: var(--bg-lighter); }
.nav-btn:disabled { opacity: 0.3; cursor: default; }
.nav-pos {
  font-size: 12px; color: var(--text-light); min-width: 40px; text-align: center;
}

/* 状态栏 */
.panel-footer {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 12px; font-size: 12px;
  border-top: 1px solid var(--border-light);
  background: var(--bg-lighter); color: var(--text-light);
  transition: background var(--transition-normal), color var(--transition-normal);
}
.footer-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--border-light); flex-shrink: 0;
  transition: background var(--transition-normal);
}
.footer-active {
  color: var(--primary);
}
.footer-active .footer-dot {
  background: var(--primary);
  animation: pulse-dot 1s ease-in-out infinite;
}
.footer-done {
  color: #22c55e;
}
.footer-done .footer-dot {
  background: #22c55e;
}
.footer-error {
  color: #ef4444;
}
.footer-error .footer-dot {
  background: #ef4444;
}
@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
</style>
