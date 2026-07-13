<template>
  <div class="gallery-shell">
    <button class="gallery-toggle" @click="openGallery">
      <span>历史图库</span>
      <strong>{{ totalLabel }}</strong>
    </button>

    <Teleport to="body">
      <div v-if="open" class="gallery-mask" @click.self="closeGallery">
        <section class="gallery-modal">
          <header class="gallery-header">
            <div>
              <h3>历史图库</h3>
              <p>{{ characterName }} 的照片记录</p>
            </div>
            <button class="close-btn" @click="closeGallery" title="关闭">×</button>
          </header>

          <div v-if="loading" class="gallery-empty">加载中...</div>
          <div v-else-if="images.length === 0" class="gallery-empty">还没有历史照片</div>
          <div v-else class="gallery-grid">
            <button
              v-for="(img, index) in images"
              :key="img.image_url || index"
              class="gallery-item"
              @click="selected = img"
            >
              <img :src="img.image_url" :alt="`${characterName} 的历史照片 ${index + 1}`" />
            </button>
          </div>

          <div v-if="selected" class="viewer">
            <button class="viewer-close" @click="selected = null" title="返回图库">×</button>
            <img :src="selected.image_url" :alt="`${characterName} 的历史照片`" />
            <p v-if="selected.prompt">{{ selected.prompt }}</p>
          </div>
        </section>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useImageHistory } from '../composables/useImageHistory.js'

const props = defineProps({
  characterName: { type: String, default: '...' },
  activeCharId: String,
  imageStatus: String,
})

const open = ref(false)
const selected = ref(null)
const { images, loading, fetchHistory } = useImageHistory()

const totalLabel = computed(() => images.value.length ? `${images.value.length} 张` : '空')

async function openGallery() {
  open.value = true
  await fetchHistory(100, props.activeCharId)
}

function closeGallery() {
  open.value = false
  selected.value = null
}

watch(() => props.activeCharId, async () => {
  selected.value = null
  if (open.value) await fetchHistory(100, props.activeCharId)
})

watch(() => props.imageStatus, async (status) => {
  if (status === 'done') await fetchHistory(100, props.activeCharId)
})

fetchHistory(20, props.activeCharId)
</script>

<style scoped>
.gallery-shell {
  flex-shrink: 0;
  padding: 10px;
  background: linear-gradient(180deg, #f5f0ff 0%, #fafbff 100%);
  border-top: 1px solid var(--border-light);
}

.gallery-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid #e6e2f5;
  border-radius: 8px;
  background: #fff;
  color: #4a405f;
  padding: 9px 11px;
  font-size: 13px;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(0,0,0,.03);
}

.gallery-toggle:hover {
  background: #fbfaff;
}

.gallery-toggle strong {
  font-size: 11px;
  color: #7c6faa;
  font-weight: 600;
}

.gallery-mask {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: rgba(18, 16, 28, .42);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 28px;
}

.gallery-modal {
  position: relative;
  width: min(960px, 96vw);
  height: min(760px, 90vh);
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 20px 60px rgba(0,0,0,.22);
  overflow: hidden;
}

.gallery-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border-light);
  background: #fafbff;
}

.gallery-header h3 {
  margin: 0;
  font-size: 16px;
  color: #2f293d;
}

.gallery-header p {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-light);
}

.close-btn,
.viewer-close {
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-light);
  border-radius: 50%;
  background: #fff;
  color: #6b617d;
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
}

.gallery-grid {
  flex: 1;
  overflow: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 10px;
  padding: 14px;
  background: #fbfbfe;
}

.gallery-item {
  aspect-ratio: 1;
  border: 1px solid #eee;
  border-radius: 8px;
  overflow: hidden;
  padding: 0;
  background: #fff;
  cursor: pointer;
}

.gallery-item img {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
}

.gallery-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-light);
  font-size: 13px;
}

.viewer {
  position: absolute;
  inset: 0;
  background: rgba(12, 10, 18, .88);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 24px;
}

.viewer img {
  max-width: 100%;
  max-height: calc(100% - 80px);
  object-fit: contain;
  border-radius: 8px;
}

.viewer p {
  max-width: 760px;
  color: #fff;
  font-size: 12px;
  line-height: 1.5;
  margin: 0;
  opacity: .85;
}

.viewer-close {
  position: absolute;
  top: 14px;
  right: 14px;
}
</style>
