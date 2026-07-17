<template>
  <div class="chat-area">
    <div class="chat-header">
      <span class="name">{{ characterAvatar }} {{ characterName }}</span>
      <div class="header-actions">
        <button class="image-visibility-btn" @click="imagesVisible = !imagesVisible">
          {{ imagesVisible ? '隐藏图片' : '显示图片' }}
        </button>
        <span class="status" :class="{ online: isConnected }">
          {{ isConnected ? '在线' : '离线' }}
        </span>
      </div>
    </div>
    <div class="messages" ref="msgList">
      <div v-if="messages.length === 0" class="welcome">
        <div class="welcome-icon">🌸</div>
        <p>你好呀～有什么想和{{ characterName }}说的吗？</p>
      </div>
      <div v-for="msg in messages" :key="msg.id" class="msg" :class="msg.role">
        <div v-if="msg.type === 'scene_divider'" class="scene-divider">
          <span>{{ msg.content || '新场景' }}</span>
        </div>
        <template v-else>
          <div v-if="isImage(msg)" class="image-bubble">
            <template v-if="imagesVisible">
              <img :src="imageSrc(msg)" :alt="`${characterName}的照片`" />
            </template>
            <div v-else class="image-hidden">图片已隐藏</div>
            <button
              class="regenerate-btn"
              :disabled="regeneratingImageUrl === imageSrc(msg)"
              @click="emit('regenerate', imageSrc(msg))"
            >
              {{ regeneratingImageUrl === imageSrc(msg) ? '重新生成中…' : '重新生成' }}
            </button>
            <p v-if="regenerationError?.imageUrl === imageSrc(msg)" class="regenerate-error">
              {{ regenerationError.message }}
            </p>
            <p v-if="msg.content">{{ msg.content }}</p>
          </div>
          <div v-else-if="msg.type === 'image_pending'" class="image-pending">
            <div class="typing"><span></span><span></span><span></span></div>
            <p>{{ msg.content || '正在生成图片...' }}</p>
          </div>
          <div v-else-if="msg.type === 'image_error'" class="image-error">
            {{ msg.content || '图片生成失败' }}
          </div>
          <div class="bubble" v-else-if="msg.content">{{ msg.content }}</div>
          <div class="time">{{ formatTime(msg.timestamp) }}</div>
        </template>
      </div>
      <div v-if="isLoading" class="msg assistant">
        <div class="typing"><span></span><span></span><span></span></div>
      </div>
    </div>
    <div class="input-area">
      <textarea
        v-model="inputText"
        @keydown.enter.prevent="onSend"
        :placeholder="placeholder"
        rows="1"
        ref="inputRef"
      ></textarea>
      <button @click="onSend" :disabled="!inputText.trim()" class="send-btn">{{ characterAvatar || '💕' }}</button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'

const props = defineProps({
  messages: Array,
  isLoading: Boolean,
  isConnected: Boolean,
  characterName: { type: String, default: '...' },
  characterAvatar: String,
  regeneratingImageUrl: { type: String, default: '' },
  regenerationError: { type: Object, default: null },
})
const emit = defineEmits(['send', 'regenerate'])

const inputText = ref('')
const msgList = ref(null)
const inputRef = ref(null)
const imagesVisible = ref(true)

const placeholder = computed(() => `跟${props.characterName}说点什么吧～`)

const onSend = () => {
  const text = inputText.value.trim()
  if (!text) return
  emit('send', text)
  inputText.value = ''
}

const formatTime = (d) => {
  if (!d) return ''
  return new Date(d).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

const imageSrc = (msg) => msg.imageUrl || msg.image_url || msg.url || ''
const isImage = (msg) => msg?.type === 'image' && imageSrc(msg)

watch(() => props.messages.length, async () => {
  await nextTick()
  if (msgList.value) msgList.value.scrollTop = msgList.value.scrollHeight
}, { deep: true })
</script>

<style scoped>
.chat-area {
  flex: 1; display: flex; flex-direction: column;
  background: var(--bg-lighter); border-right: 1px solid var(--border-light);
  min-width: 300px;
}
.chat-header {
  padding: 12px 16px; background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end));
  color: #fff; display: flex; justify-content: space-between; align-items: center;
  box-shadow: 0 2px 8px rgba(99,102,241,0.2);
}
.name { font-size: 16px; font-weight: 600; }
.header-actions { display: flex; align-items: center; gap: 10px; }
.image-visibility-btn {
  border: 1px solid rgba(255,255,255,.42); border-radius: 6px;
  padding: 4px 8px; background: rgba(255,255,255,.14); color: #fff;
  font: inherit; font-size: 11px; cursor: pointer;
}
.image-visibility-btn:hover { background: rgba(255,255,255,.25); }
.status { font-size: 12px; opacity: 0.8; }
.status.online { color: #4ade80; }
.messages { flex: 1; overflow-y: auto; padding: 16px; }
.welcome { text-align: center; padding: 40px 20px; color: #888; }
.welcome-icon { font-size: 48px; margin-bottom: 12px; }
.msg { margin-bottom: 12px; display: flex; flex-direction: column; }
.msg.user { align-items: flex-end; }
.msg.assistant { align-items: flex-start; }
.msg.system { align-items: stretch; }
.scene-divider {
  width: 100%; display: flex; align-items: center; gap: 10px;
  color: #9a93ad; font-size: 11px; letter-spacing: .5px;
  padding: 7px 0;
}
.scene-divider::before, .scene-divider::after {
  content: ''; height: 1px; flex: 1; background: #ded9eb;
}
.scene-divider span { white-space: nowrap; }
.bubble {
  max-width: 75%; padding: 10px 14px; border-radius: 18px;
  font-size: 14px; line-height: 1.5; word-break: break-word;
  white-space: pre-wrap;
}
.msg.user .bubble { background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end)); color: #fff; border-bottom-right-radius: 4px; }
.msg.assistant .bubble { background: #fff; color: #4a4a4a; border-bottom-left-radius: 4px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.image-bubble {
  max-width: min(75%, 360px); padding: 8px; border-radius: 18px;
  border-bottom-left-radius: 4px; background: #fff;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
.image-bubble img {
  display: block; width: 100%; max-height: 520px;
  object-fit: contain; border-radius: 12px;
}
.image-hidden {
  min-width: 150px; padding: 28px 18px; border-radius: 12px;
  background: #f4f2fa; color: #867e98; font-size: 12px; text-align: center;
}
.regenerate-btn {
  margin-top: 8px; padding: 5px 8px; border: 1px solid #ded6f2;
  border-radius: 6px; background: #f7f4ff; color: #665589;
  font: inherit; font-size: 11px; cursor: pointer;
}
.regenerate-btn:hover:not(:disabled) { background: #eee9ff; }
.regenerate-btn:disabled { opacity: .58; cursor: wait; }
.regenerate-error { margin-top: 6px; color: #b45309 !important; }
.image-bubble p {
  margin-top: 6px; font-size: 12px; color: var(--text-light);
  white-space: pre-wrap;
}
.image-pending, .image-error {
  max-width: 75%; padding: 10px 14px; border-radius: 18px;
  border-bottom-left-radius: 4px; background: #fff;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
.image-pending p { margin-top: 6px; font-size: 12px; color: #777; }
.image-error { color: #b91c1c; }
.time { font-size: 10px; color: #aaa; margin-top: 4px; padding: 0 4px; }
.typing { display: flex; gap: 4px; padding: 12px 16px; background: #fff; border-radius: 18px; }
.typing span { width: 7px; height: 7px; background: var(--primary); border-radius: 50%; animation: bounce 1.4s infinite ease-in-out both; }
.typing span:nth-child(1) { animation-delay: -0.32s; }
.typing span:nth-child(2) { animation-delay: -0.16s; }
@keyframes bounce {
  0%,80%,100% { transform: scale(0.6); opacity: 0.5; }
  40% { transform: scale(1); opacity: 1; }
}
.input-area {
  display: flex; gap: 8px; padding: 12px; background: #fff;
  border-top: 1px solid var(--border-light); align-items: flex-end;
}
.input-area textarea {
  flex: 1; border: none; background: var(--bg-lighter); border-radius: 20px;
  padding: 10px 16px; resize: none; font-size: 14px; outline: none;
  font-family: inherit; max-height: 100px;
  transition: box-shadow var(--transition-fast);
}
.input-area textarea:focus {
  box-shadow: 0 0 0 3px rgba(99,102,241,0.1);
}
.send-btn {
  width: 40px; height: 40px; border-radius: 50%; border: none;
  background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end)); color: #fff;
  cursor: pointer; font-size: 18px; flex-shrink: 0;
}
.send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
