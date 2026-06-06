/**
 * spinner module — loading / typing indicators (chat animation spec §5).
 *
 * Each factory returns a {@link SpinnerHandle}; call `stop()` to clear the
 * underlying interval / RAF. The handle is also stashed on the target node
 * (`__spinnerHandle`) so a caller that loses the reference can still stop it.
 *
 * Hard rules honored:
 *  - #4: CSS color vars are read ONCE per instance (no per-frame getComputedStyle).
 *  - #5: every handle owns its interval/RAF and clears it on stop().
 */

export interface SpinnerHandle {
  stop: () => void
}

// ASCII wave frames cycled ~100–150ms.
export const ASCII_WAVE_FRAMES = [
  '▁▂▃', '▂▃▄', '▃▄▅', '▄▅▆', '▅▆▅', '▆▅▄', '▅▄▃', '▄▃▂', '▃▂▁',
]

/** Cache the accent color once (rule #4). Falls back to the YAPOC amber. */
function readAccent(): string {
  try {
    const s = getComputedStyle(document.documentElement)
    return (
      s.getPropertyValue('--color-accent').trim() ||
      s.getPropertyValue('--color-text-primary').trim() ||
      '#FFB633'
    )
  } catch {
    return '#FFB633'
  }
}

function attach(node: object, handle: SpinnerHandle): SpinnerHandle {
  ;(node as { __spinnerHandle?: SpinnerHandle }).__spinnerHandle = handle
  return handle
}

/** ASCII wave: writes frames into `el.textContent` on an interval. */
export function startAsciiWave(el: HTMLElement, intervalMs = 120): SpinnerHandle {
  let i = 0
  el.textContent = ASCII_WAVE_FRAMES[0]
  const id = window.setInterval(() => {
    i = (i + 1) % ASCII_WAVE_FRAMES.length
    el.textContent = ASCII_WAVE_FRAMES[i]
  }, intervalMs)
  return attach(el, {
    stop: () => {
      window.clearInterval(id)
      delete (el as { __spinnerHandle?: SpinnerHandle }).__spinnerHandle
    },
  })
}

/** Canvas sinewave (RAF). Stroke color cached once per instance. */
export function startSineWave(canvas: HTMLCanvasElement): SpinnerHandle {
  const ctx = canvas.getContext('2d')
  if (!ctx) return { stop: () => {} }
  const stroke = readAccent() // cached once (rule #4)
  let raf = 0
  let t = 0
  const draw = () => {
    const { width: w, height: h } = canvas
    ctx.clearRect(0, 0, w, h)
    ctx.beginPath()
    ctx.strokeStyle = stroke
    ctx.lineWidth = 2
    for (let x = 0; x <= w; x++) {
      const y = h / 2 + Math.sin((x / w) * Math.PI * 4 + t) * (h / 4)
      if (x === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.stroke()
    t += 0.15
    raf = requestAnimationFrame(draw)
  }
  raf = requestAnimationFrame(draw)
  return attach(canvas, {
    stop: () => {
      cancelAnimationFrame(raf)
      delete (canvas as { __spinnerHandle?: SpinnerHandle }).__spinnerHandle
    },
  })
}

/** Canvas whirlpool (RAF). Stroke color cached once per instance. */
export function startWhirlpool(canvas: HTMLCanvasElement): SpinnerHandle {
  const ctx = canvas.getContext('2d')
  if (!ctx) return { stop: () => {} }
  const stroke = readAccent() // cached once (rule #4)
  let raf = 0
  let t = 0
  const draw = () => {
    const { width: w, height: h } = canvas
    ctx.clearRect(0, 0, w, h)
    const cx = w / 2
    const cy = h / 2
    ctx.strokeStyle = stroke
    ctx.lineWidth = 1.5
    ctx.beginPath()
    for (let a = 0; a < Math.PI * 6; a += 0.1) {
      const r = (a / (Math.PI * 6)) * Math.min(w, h) * 0.45
      const x = cx + Math.cos(a + t) * r
      const y = cy + Math.sin(a + t) * r
      if (a === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.stroke()
    t += 0.08
    raf = requestAnimationFrame(draw)
  }
  raf = requestAnimationFrame(draw)
  return attach(canvas, {
    stop: () => {
      cancelAnimationFrame(raf)
      delete (canvas as { __spinnerHandle?: SpinnerHandle }).__spinnerHandle
    },
  })
}
