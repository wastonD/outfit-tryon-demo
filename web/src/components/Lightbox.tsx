import { useEffect, useRef, useState } from 'react'
import './Lightbox.css'

export function Lightbox({ src, alt, onClose }: { src: string; alt?: string; onClose: () => void }) {
  const [scale, setScale] = useState(1)
  const imgRef = useRef<HTMLImageElement>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // React 的 onWheel / onTouchMove 默认是被动监听（无法 preventDefault），
  // 所以这里手动挂原生的非被动监听器，避免缩放的同时页面也跟着滚动/缩放。
  useEffect(() => {
    const img = imgRef.current
    if (!img) return

    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      setScale((s) => Math.min(5, Math.max(1, s * (e.deltaY < 0 ? 1.15 : 0.87))))
    }

    let pinchStart: number | null = null
    const distance = (touches: TouchList) => {
      const a = touches[0]
      const b = touches[1]
      return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY)
    }
    const onTouchMove = (e: TouchEvent) => {
      if (e.touches.length !== 2) return
      e.preventDefault()
      const d = distance(e.touches)
      if (pinchStart != null) {
        const prev = pinchStart
        setScale((s) => Math.min(5, Math.max(1, s * (d / prev))))
      }
      pinchStart = d
    }
    const onTouchEnd = () => {
      pinchStart = null
    }

    img.addEventListener('wheel', onWheel, { passive: false })
    img.addEventListener('touchmove', onTouchMove, { passive: false })
    img.addEventListener('touchend', onTouchEnd)
    return () => {
      img.removeEventListener('wheel', onWheel)
      img.removeEventListener('touchmove', onTouchMove)
      img.removeEventListener('touchend', onTouchEnd)
    }
  }, [])

  return (
    <div className="lightbox" onClick={onClose}>
      <img
        ref={imgRef}
        src={src}
        alt={alt ?? ''}
        style={{ transform: `scale(${scale})` }}
        onClick={(e) => e.stopPropagation()}
      />
      <button type="button" className="lightbox-close" onClick={onClose} aria-label="close">
        ×
      </button>
    </div>
  )
}
