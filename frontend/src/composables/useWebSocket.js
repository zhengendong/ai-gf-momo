/**
 * WebSocket 组合式函数
 */
import { ref, onMounted, onUnmounted } from 'vue'

export function useWebSocket() {
  const isConnected = ref(false)
  const messages = ref([])
  const lastMessage = ref(null)
  const imageStatus = ref('idle')  // idle | generating | done | error
  const currentImage = ref(null)    // 当前图片URL
  const statusUpdate = ref(null)    // 状态栏数据
  const characterState = ref(null)  // 角色状态 { status: {...}, plans: {...} }

  let socket = null
  let reconnectTimer = null
  let heartbeatTimer = null

  const generateSessionId = () => {
    return `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  }

  const sessionId = generateSessionId()

  const connect = () => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const url = `${protocol}//${host}/ws/${sessionId}`

    console.log(`WebSocket 连接: ${url}`)
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
          if (lastMsg && lastMsg.role === 'assistant' && !lastMsg.completed) {
            lastMsg.content += data.content
          } else {
            messages.value.push({
              id: Date.now(),
              role: 'assistant',
              content: data.content,
              timestamp: new Date(),
              completed: false
            })
          }
          lastMessage.value = data

        } else if (data.type === 'image' && data.url) {
          currentImage.value = data.url
          imageStatus.value = 'done'

        } else if (data.type === 'image_status') {
          if (data.content === 'generating') {
            imageStatus.value = 'generating'
          } else if (data.content === 'error') {
            imageStatus.value = 'error'
          } else if (data.content === 'done') {
            if (imageStatus.value !== 'done') imageStatus.value = 'idle'
          }

        } else if (data.type === 'status_update') {
          statusUpdate.value = data.content

        } else if (data.type === 'done') {
          const lastMsg = messages.value[messages.value.length - 1]
          if (lastMsg && lastMsg.role === 'assistant') {
            lastMsg.completed = true
          }
          lastMessage.value = data

        } else if (data.type === 'state_update') {
          try {
            characterState.value = JSON.parse(data.content)
          } catch (e) {
            console.error('解析状态数据失败:', e)
          }

        } else if (data.type === 'pong') {
          // heartbeat
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

  const refreshMemory = () => {
    sendMessage({ type: 'refresh_memory' })
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
    sendMessage, refreshMemory,
    disconnect, reconnect: connect
  }
}
