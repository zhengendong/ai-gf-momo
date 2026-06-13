<template>
  <div class="chat-app">
    <div class="chat-window">
      <!-- 头部 -->
      <div class="chat-header">
        <div class="header-content">
          <div class="avatar-wrapper">
            <div class="avatar">
              <span class="avatar-emoji">💕</span>
            </div>
            <div class="status-dot" :class="{ online: isConnected }"></div>
          </div>
          <div class="info">
            <h1 class="name">小桃</h1>
            <span class="status-text">{{ isConnected ? '在线' : '离线中...' }}</span>
          </div>
        </div>
        <div class="header-decoration">♡</div>
      </div>

      <!-- 消息列表 -->
      <div class="message-list" ref="messageList">
        <!-- 欢迎消息 -->
        <div class="welcome-message" v-if="messages.length === 0">
          <div class="welcome-avatar">🌸</div>
          <div class="welcome-text">
            <p>哥哥好呀～</p>
            <p>有什么想和小桃说的吗？</p>
          </div>
        </div>

        <!-- 消息列表 -->
        <div
          v-for="message in messages"
          :key="message.id"
          class="message"
          :class="message.role"
        >
          <!-- 小桃头像 -->
          <div class="message-avatar" v-if="message.role === 'assistant'">
            💕
          </div>

          <div class="message-body">
            <!-- 文本内容 -->
            <div class="message-bubble" v-if="message.content">
              <div class="message-content">{{ message.content }}</div>
              <div class="message-time">{{ formatTime(message.timestamp) }}</div>
            </div>

            <!-- 图片内容 -->
            <div class="message-images" v-if="message.hasImage && message.images">
              <div
                v-for="(imgUrl, idx) in message.images"
                :key="idx"
                class="image-wrapper"
                :class="{ loading: isImageLoading(imgUrl) }"
              >
                <div class="image-loading-placeholder" v-if="isImageLoading(imgUrl)">
                  <div class="loading-spinner"></div>
                  <span>加载中...</span>
                </div>
                <img
                  :src="imgUrl"
                  :alt="'小桃的照片 ' + (idx + 1)"
                  @load="onImageLoaded(imgUrl)"
                  @error="onImageError(imgUrl)"
                  :class="{ loaded: !isImageLoading(imgUrl) }"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- 打字动画 -->
        <div v-if="isLoading" class="message assistant">
          <div class="message-avatar">💕</div>
          <div class="message-body">
            <div class="message-bubble">
              <div class="typing-indicator">
                <span class="dot"></span>
                <span class="dot"></span>
                <span class="dot"></span>
              </div>
            </div>
          </div>
        </div>

        <!-- 生图中的提示 -->
        <div v-if="isGeneratingImage" class="message assistant">
          <div class="message-avatar">📷</div>
          <div class="message-body">
            <div class="message-bubble generating-bubble">
              <div class="generating-indicator">
                <div class="loading-spinner pink"></div>
                <span>正在拍照中...</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区域 -->
      <div class="input-area">
        <div class="input-wrapper">
          <!-- 生图按钮 -->
          <button
            @click="requestPhoto"
            :disabled="isGeneratingImage || isLoading"
            class="photo-button"
            title="让小桃拍张照"
          >
            <span class="photo-icon">📷</span>
          </button>
          <textarea
            v-model="inputText"
            @keydown.enter.prevent="sendMessage"
            @input="autoResize"
            placeholder="跟小桃说点什么吧～"
            ref="textareaRef"
            rows="1"
          ></textarea>
          <button
            @click="sendMessage"
            :disabled="!inputText.trim()"
            class="send-button"
          >
            <span class="send-icon">💕</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch } from 'vue'
import { useWebSocket } from '../composables/useWebSocket'

const {
  isConnected,
  messages,
  sendMessage: sendWsMessage,
  lastMessage,
  imageStatus
} = useWebSocket()

const isGeneratingImage = computed(() => imageStatus.value === 'generating')

// 拍照请求消息池：随机选择一条发给 LLM，让小桃在对话中自然决定拍照
const photoRequestMessages = [
  '帮我拍张照吧～',
  '让我看看你今天的样子',
  '拍一张照片给我看看',
  '小桃，拍张照给我',
  '来张自拍嘛～',
  '给我一张你的照片',
  '拍个照好不好',
  '想看看你现在的样子',
]

const inputText = ref('')
const isLoading = ref(false)
const messageList = ref(null)
const textareaRef = ref(null)
const loadingImages = ref(new Set())

// 监听新消息
watch(lastMessage, (newMessage) => {
  if (newMessage) {
    isLoading.value = false
    scrollToBottom()
  }
})

// 监听用户消息发送后显示加载
watch(messages, () => {
  const lastMsg = messages.value[messages.value.length - 1]
  if (lastMsg && lastMsg.role === 'user') {
    isLoading.value = true
  }
  scrollToBottom()
}, { deep: true })

// 发送消息
const sendMessage = () => {
  const text = inputText.value.trim()
  if (!text) return

  // 添加用户消息到列表
  messages.value.push({
    id: Date.now(),
    role: 'user',
    content: text,
    timestamp: new Date()
  })

  // 发送到服务器
  sendWsMessage({
    type: 'text',
    content: text
  })

  // 清空输入框
  inputText.value = ''

  // 重置textarea高度
  if (textareaRef.value) {
    textareaRef.value.style.height = 'auto'
  }

  scrollToBottom()
}

// 📷 拍照按钮：发送对话消息，让小桃在上下文中自然决定拍照
// 而不是直接调 ComfyUI——这样 LLM 会先回复有沉浸感的文字 + [图片] 标记
const requestPhoto = () => {
  const text = photoRequestMessages[Math.floor(Math.random() * photoRequestMessages.length)]

  // 添加用户消息到列表
  messages.value.push({
    id: Date.now(),
    role: 'user',
    content: text,
    timestamp: new Date()
  })

  // 通过正常聊天流程发送，LLM 会在回复中带 [图片]
  sendWsMessage({ type: 'text', content: text })
  scrollToBottom()
}

// 自动调整输入框高度
const autoResize = () => {
  const textarea = textareaRef.value
  if (textarea) {
    textarea.style.height = 'auto'
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px'
  }
}

// 滚动到底部
const scrollToBottom = async () => {
  await nextTick()
  if (messageList.value) {
    messageList.value.scrollTop = messageList.value.scrollHeight
  }
}

// 图片加载状态
const isImageLoading = (url) => loadingImages.value.has(url)

const onImageLoaded = (url) => {
  loadingImages.value.delete(url)
  scrollToBottom()
}

const onImageError = (url) => {
  loadingImages.value.delete(url)
  console.error('图片加载失败:', url)
}

// 跟踪新图片进入加载状态
watch(() => {
  messages.value.forEach(msg => {
    if (msg.images) {
      msg.images.forEach(url => {
        loadingImages.value.add(url)
      })
    }
  })
}, { deep: true })

// 格式化时间
const formatTime = (date) => {
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit'
  })
}

// 组件挂载时滚动到底部
onMounted(() => {
  scrollToBottom()
})
</script>

<style scoped>
/* CSS 变量 */
.chat-app {
  --primary-pink: #ff6b9d;
  --secondary-pink: #ff8fab;
  --light-pink: #ffe5ec;
  --very-light-pink: #fff5f7;
  --gradient-start: #ff6b9d;
  --gradient-end: #ff8fab;
  --text-dark: #4a4a4a;
  --text-light: #888;
  --white: #ffffff;
  --shadow-soft: 0 4px 20px rgba(255, 107, 157, 0.15);
  --shadow-medium: 0 8px 30px rgba(255, 107, 157, 0.2);
}

/* 全局容器 */
.chat-app {
  height: 100vh;
  height: 100dvh;
  display: flex;
  justify-content: center;
  align-items: center;
  background: linear-gradient(135deg, var(--very-light-pink) 0%, var(--light-pink) 100%);
  padding: 20px;
}

/* 聊天窗口 */
.chat-window {
  width: 100%;
  max-width: 500px;
  height: calc(100vh - 40px);
  height: calc(100dvh - 40px);
  max-height: 700px;
  display: flex;
  flex-direction: column;
  background: var(--white);
  border-radius: 24px;
  box-shadow: var(--shadow-medium);
  overflow: hidden;
}

/* 头部 */
.chat-header {
  background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end));
  color: var(--white);
  padding: 16px 20px;
  position: relative;
  overflow: hidden;
}

.header-content {
  display: flex;
  align-items: center;
  gap: 12px;
  position: relative;
  z-index: 1;
}

.header-decoration {
  position: absolute;
  right: 20px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 40px;
  opacity: 0.3;
}

.avatar-wrapper {
  position: relative;
}

.avatar {
  width: 48px;
  height: 48px;
  background: var(--white);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);
}

.avatar-emoji {
  font-size: 24px;
}

.status-dot {
  position: absolute;
  bottom: 2px;
  right: 2px;
  width: 12px;
  height: 12px;
  background: #ccc;
  border-radius: 50%;
  border: 2px solid var(--white);
  transition: background 0.3s;
}

.status-dot.online {
  background: #4ade80;
}

.info {
  flex: 1;
}

.name {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.status-text {
  font-size: 12px;
  opacity: 0.9;
}

/* 消息列表 */
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  background: var(--very-light-pink);
  scroll-behavior: smooth;
}

/* 欢迎消息 */
.welcome-message {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  text-align: center;
}

.welcome-avatar {
  font-size: 48px;
  margin-bottom: 16px;
  animation: float 3s ease-in-out infinite;
}

@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-10px); }
}

.welcome-text {
  color: var(--text-light);
  font-size: 14px;
  line-height: 1.8;
}

/* 消息 */
.message {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  margin-bottom: 16px;
  animation: messageIn 0.3s ease-out;
}

@keyframes messageIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.message.user {
  flex-direction: row-reverse;
}

.message-avatar {
  width: 36px;
  height: 36px;
  background: var(--white);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  flex-shrink: 0;
}

.message-body {
  max-width: 75%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.message-bubble {
  max-width: 100%;
  position: relative;
}

.message-content {
  padding: 12px 16px;
  border-radius: 18px;
  line-height: 1.5;
  word-break: break-word;
  font-size: 14px;
  white-space: pre-wrap;
}

.message.user .message-content {
  background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end));
  color: var(--white);
  border-bottom-right-radius: 4px;
  box-shadow: 0 4px 15px rgba(255, 107, 157, 0.3);
}

.message.assistant .message-content {
  background: var(--white);
  color: var(--text-dark);
  border-bottom-left-radius: 4px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
}

.message-time {
  font-size: 10px;
  color: var(--text-light);
  margin-top: 4px;
  padding: 0 4px;
}

.message.user .message-time {
  text-align: right;
}

/* 图片展示 */
.message-images {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.image-wrapper {
  position: relative;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
  background: var(--very-light-pink);
  min-height: 150px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.image-wrapper img {
  width: 100%;
  max-width: 280px;
  height: auto;
  display: block;
  border-radius: 16px;
  transition: opacity 0.4s ease;
}

.image-wrapper img.loaded {
  opacity: 1;
}

.image-wrapper.loading img {
  opacity: 0;
  position: absolute;
}

.image-loading-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: var(--text-light);
  font-size: 12px;
  padding: 30px 0;
}

.loading-spinner {
  width: 28px;
  height: 28px;
  border: 3px solid var(--light-pink);
  border-top-color: var(--primary-pink);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.loading-spinner.pink {
  width: 20px;
  height: 20px;
  border-width: 2px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 生图提示 */
.generating-bubble {
  background: var(--white) !important;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
}

.generating-indicator {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
  font-size: 13px;
  color: var(--primary-pink);
}

/* 打字动画 */
.typing-indicator {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 12px 16px;
  background: var(--white);
  border-radius: 18px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
}

.typing-indicator .dot {
  width: 8px;
  height: 8px;
  background: var(--primary-pink);
  border-radius: 50%;
  animation: typingBounce 1.4s infinite ease-in-out both;
}

.typing-indicator .dot:nth-child(1) {
  animation-delay: -0.32s;
}

.typing-indicator .dot:nth-child(2) {
  animation-delay: -0.16s;
}

@keyframes typingBounce {
  0%, 80%, 100% {
    transform: scale(0.6);
    opacity: 0.5;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}

/* 输入区域 */
.input-area {
  padding: 16px;
  background: var(--white);
  border-top: 1px solid var(--light-pink);
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  background: var(--very-light-pink);
  border-radius: 24px;
  padding: 8px 8px 8px 12px;
  transition: box-shadow 0.3s;
}

.input-wrapper:focus-within {
  box-shadow: 0 0 0 2px var(--primary-pink);
}

/* 拍照按钮 */
.photo-button {
  width: 40px;
  height: 40px;
  background: var(--white);
  border: 1.5px solid var(--light-pink);
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.2s, box-shadow 0.2s, background 0.2s;
  flex-shrink: 0;
}

.photo-button:hover:not(:disabled) {
  transform: scale(1.1);
  background: var(--very-light-pink);
  box-shadow: 0 4px 12px rgba(255, 107, 157, 0.25);
}

.photo-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.photo-icon {
  font-size: 18px;
}

.input-wrapper textarea {
  flex: 1;
  border: none;
  background: transparent;
  resize: none;
  font-size: 14px;
  font-family: inherit;
  line-height: 1.5;
  padding: 8px 0;
  outline: none;
  color: var(--text-dark);
  max-height: 120px;
}

.input-wrapper textarea::placeholder {
  color: var(--text-light);
}

.send-button {
  width: 44px;
  height: 44px;
  background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end));
  border: none;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.2s, box-shadow 0.2s;
  flex-shrink: 0;
}

.send-button:hover:not(:disabled) {
  transform: scale(1.1);
  box-shadow: 0 4px 15px rgba(255, 107, 157, 0.4);
}

.send-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.send-icon {
  font-size: 20px;
}

/* 响应式：移动端 */
@media (max-width: 768px) {
  .chat-app {
    padding: 0;
  }

  .chat-window {
    max-width: 100%;
    height: 100vh;
    height: 100dvh;
    max-height: none;
    border-radius: 0;
  }

  .chat-header {
    padding-top: calc(16px + env(safe-area-inset-top, 0px));
  }

  .input-area {
    padding-bottom: calc(16px + env(safe-area-inset-bottom, 0px));
  }

  .message-body {
    max-width: 80%;
  }

  .image-wrapper img {
    max-width: 240px;
  }
}

/* 响应式：小屏幕手机 */
@media (max-width: 375px) {
  .avatar {
    width: 40px;
    height: 40px;
  }

  .avatar-emoji {
    font-size: 20px;
  }

  .name {
    font-size: 16px;
  }

  .message-content {
    font-size: 13px;
    padding: 10px 14px;
  }

  .message-avatar {
    width: 32px;
    height: 32px;
    font-size: 16px;
  }

  .image-wrapper img {
    max-width: 200px;
  }

  .photo-button {
    width: 36px;
    height: 36px;
  }

  .photo-icon {
    font-size: 16px;
  }
}

/* 响应式：大屏幕PC */
@media (min-width: 1200px) {
  .chat-window {
    max-width: 520px;
    box-shadow: 0 20px 60px rgba(255, 107, 157, 0.25);
  }
}

/* 滚动条美化 */
.message-list::-webkit-scrollbar {
  width: 6px;
}

.message-list::-webkit-scrollbar-track {
  background: transparent;
}

.message-list::-webkit-scrollbar-thumb {
  background: var(--light-pink);
  border-radius: 3px;
}

.message-list::-webkit-scrollbar-thumb:hover {
  background: var(--primary-pink);
}
</style>
