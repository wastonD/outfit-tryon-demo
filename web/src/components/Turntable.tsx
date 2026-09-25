import { useEffect, useRef } from 'react'
import { fileUrl, type FileRef } from '../api'
import { useT } from '../i18n/context'
import './Turntable.css'

// 逻辑照搬 server/bench/report.py 里的 JS 拖动查看器：左右拖动切换视频帧（当作 360° 转盘），
// 滚轮缩放（CSS transform scale，1～4 倍），双击在 1 倍和 2 倍之间切换。
export function Turntable({ video }: { video: FileRef }) {
  const { t } = useT()
  const videoRef = useRef<HTMLVideoElement>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  const lastX = useRef(0)
  const scale = useRef(1)

  const setZoom = (n: number) => {
    scale.current = Math.min(4, Math.max(1, n))
    if (videoRef.current) videoRef.current.style.transform = `scale(${scale.current})`
  }

  const onPointerDown = (e: React.PointerEvent) => {
    dragging.current = true
    lastX.current = e.clientX
    boxRef.current?.setPointerCapture(e.pointerId)
    videoRef.current?.pause()
  }

  const onPointerMove = (e: React.PointerEvent) => {
    const v = videoRef.current
    if (!dragging.current || !v || !v.duration) return
    const width = boxRef.current?.clientWidth || 1
    const delta = ((e.clientX - lastX.current) / width) * v.duration
    lastX.current = e.clientX
    v.currentTime = (((v.currentTime + delta) % v.duration) + v.duration) % v.duration
  }

  const onPointerUp = () => {
    dragging.current = false
  }

  const onDoubleClick = () => {
    setZoom(scale.current > 1 ? 1 : 2)
  }

  // React 的 onWheel 默认是被动监听（无法 preventDefault），滚轮缩放时页面会跟着滚动，
  // 所以这里手动挂一个非被动的原生监听器。
  useEffect(() => {
    const box = boxRef.current
    if (!box) return
    const handler = (e: WheelEvent) => {
      e.preventDefault()
      setZoom(scale.current * (e.deltaY < 0 ? 1.15 : 0.87))
    }
    box.addEventListener('wheel', handler, { passive: false })
    return () => box.removeEventListener('wheel', handler)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div
      ref={boxRef}
      className="turntable"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onDoubleClick={onDoubleClick}
    >
      <video ref={videoRef} src={fileUrl(video)} muted playsInline preload="auto" />
      <span className="turntable-hint">{t('look.turntableHint')}</span>
    </div>
  )
}
