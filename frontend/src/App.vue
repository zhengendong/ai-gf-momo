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
        @send="onSendMessage"
      />
      <div class="right-side">
        <StatePanel :character-state="characterState" />
        <SceneTransitionPanel
          :disabled="!isConnected || isLoading"
          @transition="onSceneTransition"
        />
        <ImageGallery
          :character-name="profile.name"
          :active-char-id="activeCharId"
          :image-status="imageStatus"
        />
      </div>
    </div>
    <SettingsPanel />
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
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

const { profile, characters, activeCharId, loadAll, switchCharacter } = useCharacter()

onMounted(async () => {
  await loadAll()
  await loadHistory(activeCharId.value)
  syncCharacter(activeCharId.value)
})

watch(() => profile.name, (name) => {
  if (name) document.title = `${name} ${profile.avatar}`
})

watch(isConnected, (connected) => {
  if (connected && activeCharId.value) syncCharacter(activeCharId.value)
})

const isLoading = ref(false)

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
    timestamp: new Date()
  })
  sendMessage({ type: 'text', character_id: characterId, content: text })
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
