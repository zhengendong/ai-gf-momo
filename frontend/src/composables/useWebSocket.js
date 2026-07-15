import { ref, onMounted, onUnmounted } from 'vue'

export function useWebSocket() {
  const isConnected = ref(false)
  const messages = ref([])
  const lastMessage = ref(null)
  const imageStatus = ref('idle')
  const currentImage = ref(null)
  const statusUpdate = ref(null)
  const characterState = ref(null)

  let socket = null
  let reconnectTimer = null
  let heartbeatTimer = null
  let pendingImageId = null

  const sessionId = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`

  const connect = () => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}/ws/${sessionId}`

    socket = new WebSocket(url)

    socket.onopen = () => {
      isConnected.value = true
      startHeartbeat()
    }

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)

        if (data.type === 'text' && data.content) {
          const lastMsg = messages.value[messages.value.length - 1]
          if (lastMsg && lastMsg.role === 'assistant' && lastMsg.type !== 'image' && !lastMsg.completed) {
            lastMsg.content += data.content
          } else {
            messages.value.push({
              id: Date.now(),
              role: 'assistant',
              type: 'text',
              content: data.content,
              timestamp: new Date(),
              completed: false
            })
          }
          lastMessage.value = data

        } else if (data.type === 'image' && data.url) {
          const imageMessage = {
            id: pendingImageId || `image_${Date.now()}`,
            role: 'assistant',
            type: 'image',
            imageUrl: data.url,
            content: data.content || '',
            timestamp: new Date(),
            completed: true
          }
          const pending = messages.value.find(m => m.id === pendingImageId)
          if (pending) Object.assign(pending, imageMessage)
          else messages.value.push(imageMessage)
          pendingImageId = null
          currentImage.value = null
          imageStatus.value = 'done'

        } else if (data.type === 'image_status') {
          if (data.content === 'directing' || data.content === 'generating') {
            imageStatus.value = 'generating'
            const progressText = data.content === 'directing' ? '正在设计画面...' : '正在生成图片...'
            if (!pendingImageId) {
              pendingImageId = `image_pending_${Date.now()}`
              messages.value.push({
                id: pendingImageId,
                role: 'assistant',
                type: 'image_pending',
                content: progressText,
                timestamp: new Date(),
                completed: false
              })
            } else {
              const pending = messages.value.find(m => m.id === pendingImageId)
              if (pending) pending.content = progressText
            }
          } else if (data.content === 'error') {
            imageStatus.value = 'error'
            const pending = messages.value.find(m => m.id === pendingImageId)
            if (pending) {
              pending.type = 'image_error'
              pending.content = data.message || '图片生成失败'
              pending.completed = true
            }
            pendingImageId = null
          } else if (data.content === 'done') {
            if (imageStatus.value !== 'done') imageStatus.value = 'idle'
          }

        } else if (data.type === 'status_update') {
          statusUpdate.value = data.content
          const content = String(data.content || '')
          if (typeof window !== 'undefined' && (content.includes('记忆') || content.includes('灵魂'))) {
            window.dispatchEvent(new CustomEvent('memory-status-update', { detail: data.content }))
          }

        } else if (data.type === 'memory_updated') {
          if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('memory-updated', {
              detail: {
                character: data.character || '',
                targets: String(data.content || '').split(',').filter(Boolean)
              }
            }))
          }

        } else if (data.type === 'done') {
          const lastMsg = messages.value[messages.value.length - 1]
          if (lastMsg && lastMsg.role === 'assistant' && lastMsg.type !== 'image_pending') {
            lastMsg.completed = true
          }
          lastMessage.value = data

        } else if (data.type === 'state_update') {
          try {
            characterState.value = JSON.parse(data.content)
          } catch (e) {
            console.error('解析状态数据失败:', e)
          }
        }
      } catch (error) {
        console.error('解析消息失败:', error)
      }
    }

    socket.onclose = (event) => {
      isConnected.value = false
      stopHeartbeat()
      if (event.code !== 1000) scheduleReconnect()
    }

    socket.onerror = (error) => {
      console.error('WebSocket 错误:', error)
    }
  }

  const sendMessage = (message) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(message))
    }
  }

  const refreshMemory = (characterId = '', target = 'all') => {
    sendMessage({ type: 'refresh_memory', character_id: characterId, target })
  }

  const syncCharacter = (characterId = '') => {
    sendMessage({ type: 'sync_character', character_id: characterId })
  }

  const loadHistory = async (character, limit = 500) => {
    if (!character) return
    try {
      const r = await fetch(`/api/characters/${character}/chat-history?limit=${limit}`)
      if (!r.ok) return
      const data = await r.json()
      messages.value = (data.messages || []).map((msg, index) => ({
        id: msg.id || `${character}_${index}`,
        role: msg.role || 'assistant',
        type: msg.type || 'text',
        content: msg.content || '',
        imageUrl: msg.imageUrl || msg.image_url || '',
        timestamp: msg.timestamp ? new Date(msg.timestamp) : new Date(),
        completed: msg.completed !== false
      }))
      pendingImageId = null
      imageStatus.value = 'idle'
      currentImage.value = null
    } catch (e) {
      console.error('加载聊天历史失败:', e)
    }
  }

  const startHeartbeat = () => {
    stopHeartbeat()
    heartbeatTimer = setInterval(() => {
      sendMessage({ type: 'ping' })
    }, 30000)
  }

  const stopHeartbeat = () => {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  const scheduleReconnect = () => {
    if (reconnectTimer) return
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      connect()
    }, 3000)
  }

  const disconnect = () => {
    if (socket) {
      socket.close(1000)
      socket = null
    }
    stopHeartbeat()
    if (reconnectTimer) clearInterval(reconnectTimer)
  }

  onMounted(() => connect())
  onUnmounted(() => disconnect())

  return {
    isConnected, messages, lastMessage,
    imageStatus, currentImage, statusUpdate, characterState,
    sendMessage, refreshMemory, syncCharacter, loadHistory,
    disconnect, reconnect: connect
  }
}
