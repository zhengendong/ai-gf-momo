<template>
  <div class="app">
    <StatusBar
      :is-connected="isConnected"
      :image-status="imageStatus"
      :status-update="statusUpdate"
      :character-name="profile.name"
      :character-avatar="profile.avatar"
      :characters="characters"
      :active-char-id="activeCharId"
      @refresh-memory="onRefreshMemory"
      @switch-character="switchCharacter"
    />
    <div class="main-area">
      <CharacterDirectory />
      <ChatArea
        :messages="messages"
        :is-loading="isLoading"
        :is-connected="isConnected"
        :character-name="profile.name"
        :character-avatar="profile.avatar"
        :regenerating-image-url="regeneratingImageUrl"
        :regeneration-error="regenerationError"
        @send="onSendMessage"
        @regenerate="onRegenerateImage"
      />
      <div class="right-side">
        <StatePanel :character-state="characterState" />
        <SceneTransitionPanel
          :disabled="!isConnected || isLoading"
          :character-id="activeCharId"
          :initialized="characterState?.initialized"
          @transition="onSceneTransition"
          @initialize="onInitialScene"
          @saved="onInitialSceneSaved"
        />
        <ImageGallery
          :character-name="profile.name"
          :active-char-id="activeCharId"
          :image-status="imageStatus"
          :refresh-token="imageHistoryRefreshToken"
        />
      </div>
    </div>
    <SettingsPanel />
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useWebSocket } from './composables/useWebSocket'
import { useCharacter } from './composables/useCharacter.js'
import ChatArea from './components/ChatArea.vue'
import ImageGallery from './components/ImageGallery.vue'
import CharacterDirectory from './components/CharacterDirectory.vue'
import StatusBar from './components/StatusBar.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import StatePanel from './components/StatePanel.vue'
import SceneTransitionPanel from './components/SceneTransitionPanel.vue'

const {
  isConnected, messages, lastMessage,
  imageStatus, statusUpdate, characterState,
  sendMessage, refreshMemory, syncCharacter, loadHistory,
} = useWebSocket()

const { profile, characters, activeCharId, loadAll, loadProfile, switchCharacter } = useCharacter()

onMounted(async () => {
  await loadAll()
  await loadHistory(activeCharId.value)
  syncCharacter(activeCharId.value)
  window.addEventListener('character-records-cleared', onCharacterRecordsCleared)
})

onUnmounted(() => {
  window.removeEventListener('character-records-cleared', onCharacterRecordsCleared)
})

watch(() => profile.name, (name) => {
  if (name) document.title = `${name} ${profile.avatar}`
})

watch(isConnected, (connected) => {
  if (connected && activeCharId.value) syncCharacter(activeCharId.value)
})

const isLoading = ref(false)
const regeneratingImageUrl = ref('')
const regenerationError = ref(null)
const imageHistoryRefreshToken = ref(0)

watch(lastMessage, (msg) => {
  if (msg) isLoading.value = false
})

watch(messages, () => {
  const last = messages.value[messages.value.length - 1]
  if (last && last.role === 'user') isLoading.value = true
}, { deep: true })

const onSendMessage = (text) => {
  const characterId = activeCharId.value
  messages.value.push({
    id: Date.now(),
    role: 'user',
    content: text,
    timestamp: new Date(),
    pendingInitial: characterState.value?.initialized === false,
  })
  sendMessage({ type: 'text', character_id: characterId, content: text })
}

const onInitialScene = () => {
  if (!isConnected.value || isLoading.value) return
  isLoading.value = true
  sendMessage({
    type: 'initial_scene',
    character_id: activeCharId.value,
  })
}

const onInitialSceneSaved = async () => {
  if (activeCharId.value) await loadProfile(activeCharId.value)
}

const onRegenerateImage = async (imageUrl) => {
  if (!imageUrl || regeneratingImageUrl.value) return
  regenerationError.value = null
  regeneratingImageUrl.value = imageUrl
  try {
    const response = await fetch('/api/image/regenerate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_url: imageUrl, character: activeCharId.value }),
    })
    const result = await response.json().catch(() => ({}))
    if (!response.ok || !result.image_url) {
      throw new Error(result.detail || '重新生成失败')
    }
    for (const message of messages.value) {
      if ((message.imageUrl || message.image_url) === imageUrl) {
        message.imageUrl = result.image_url
        delete message.image_url
      }
    }
    imageHistoryRefreshToken.value += 1
    statusUpdate.value = '图片已重新生成 ✓'
  } catch (error) {
    const message = error.message || '请稍后重试'
    regenerationError.value = { imageUrl, message }
    statusUpdate.value = `重新生成失败：${message}`
  } finally {
    regeneratingImageUrl.value = ''
  }
}

async function onCharacterRecordsCleared(event) {
  if (event.detail?.character !== activeCharId.value) return
  isLoading.value = false
  await loadHistory(activeCharId.value)
  syncCharacter(activeCharId.value)
}

const onSceneTransition = ({ mode, concept }) => {
  if (!isConnected.value || isLoading.value) return
  isLoading.value = true
  sendMessage({
    type: 'scene_transition',
    character_id: activeCharId.value,
    mode,
    concept,
  })
}

const onRefreshMemory = () => {
  refreshMemory(activeCharId.value)
}
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg-lighter); }
.app { height: 100vh; height: 100dvh; display: flex; flex-direction: column; max-width: 1320px; margin: 0 auto; }
.main-area { flex: 1; display: flex; overflow: hidden; min-height: 0; }
.right-side {
  width: 320px; display: flex; flex-direction: column;
  overflow: hidden; flex-shrink: 0;
}
</style>
