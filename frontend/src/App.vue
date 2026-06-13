<template>
  <div class="app">
    <StatusBar
      :is-connected="isConnected"
      :image-status="imageStatus"
      :character-name="profile.name"
      :character-avatar="profile.avatar"
      :characters="characters"
      :active-char-id="activeCharId"
      @refresh-memory="refreshMemory"
      @switch-character="switchCharacter"
    />
    <div class="main-area">
      <ChatArea
        :messages="messages"
        :is-loading="isLoading"
        :is-connected="isConnected"
        :character-name="profile.name"
        :character-avatar="profile.avatar"
        @send="onSendMessage"
      />
      <div class="right-side">
        <ImagePanel
          :status="imageStatus"
          :image-url="currentImage"
          :status-text="statusUpdate"
          :character-name="profile.name"
          :character-avatar="profile.avatar"
          :avatar-role="profile.avatar_role"
          :body-type="profile.body_type"
          :appearance="profile.appearance"
        />
        <StatePanel :character-state="characterState" />
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
import ImagePanel from './components/ImagePanel.vue'
import StatusBar from './components/StatusBar.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import StatePanel from './components/StatePanel.vue'

const {
  isConnected, messages, lastMessage,
  imageStatus, currentImage, statusUpdate, characterState,
  sendMessage, refreshMemory,
} = useWebSocket()

const { profile, characters, activeCharId, loadAll, switchCharacter } = useCharacter()

onMounted(() => {
  loadAll()
})

watch(() => profile.name, (name) => {
  if (name) document.title = `${name} ${profile.avatar}`
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
  messages.value.push({
    id: Date.now(),
    role: 'user',
    content: text,
    timestamp: new Date()
  })
  sendMessage({ type: 'text', content: text })
}
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg-lighter); }
.app { height: 100vh; height: 100dvh; display: flex; flex-direction: column; max-width: 1100px; margin: 0 auto; }
.main-area { flex: 1; display: flex; overflow: hidden; min-height: 0; }
.right-side {
  width: 320px; display: flex; flex-direction: column;
  overflow: hidden; flex-shrink: 0;
}
</style>
