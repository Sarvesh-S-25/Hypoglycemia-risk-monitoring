import { useEffect, useRef, useState } from 'react'
import { LiveSocket } from '../lib/ws.js'

/**
 * Low-level subscription to /ws/live (SRD 5.2: hooks/useWebSocket.js). Calls
 * `onFrame` for every frame received and exposes the connection state.
 * Components that need structured live data should use `useLiveState`
 * instead; this hook is the plumbing underneath it.
 */
export function useWebSocket(onFrame) {
  const [connected, setConnected] = useState(false)
  const onFrameRef = useRef(onFrame)
  onFrameRef.current = onFrame

  useEffect(() => {
    const socket = new LiveSocket({
      onFrame: (frame) => onFrameRef.current?.(frame),
      onConnectionChange: setConnected,
    })
    socket.connect()
    return () => socket.close()
  }, [])

  return { connected }
}
