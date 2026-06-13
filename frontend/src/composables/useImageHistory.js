import { ref, computed } from 'vue'

const API_BASE = '/api'

export function useImageHistory() {
  const images = ref([])        // { image_url, prompt, image_path }
  const currentIndex = ref(-1)  // -1 = 无历史
  const loading = ref(false)

  const currentImage = computed(() => {
    if (currentIndex.value < 0 || currentIndex.value >= images.value.length) return null
    return images.value[currentIndex.value]
  })

  const hasMultiple = computed(() => images.value.length > 1)

  const position = computed(() => {
    const total = images.value.length
    if (total === 0) return ''
    return `${currentIndex.value + 1}/${total}`
  })

  const canGoPrev = computed(() => currentIndex.value < images.value.length - 1)
  const canGoNext = computed(() => currentIndex.value > 0)

  async function fetchHistory(limit = 50) {
    loading.value = true
    try {
      const res = await fetch(`${API_BASE}/image/history?limit=${limit}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      images.value = data.items || []
      currentIndex.value = images.value.length > 0 ? 0 : -1
    } catch (e) {
      console.warn('获取生成历史失败:', e)
    } finally {
      loading.value = false
    }
  }

  function addImage(url) {
    // 避免重复
    if (images.value.length > 0 && images.value[0].image_url === url) return
    images.value.unshift({ image_url: url, prompt: '', image_path: '' })
    currentIndex.value = 0
  }

  function goToPrev() {
    if (canGoPrev.value) currentIndex.value++
  }

  function goToNext() {
    if (canGoNext.value) currentIndex.value--
  }

  return {
    images,
    currentIndex,
    loading,
    currentImage,
    hasMultiple,
    position,
    canGoPrev,
    canGoNext,
    fetchHistory,
    addImage,
    goToPrev,
    goToNext,
  }
}
