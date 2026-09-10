import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * A fenced code block with its language named and one-click copy.
 *
 * `source` is the raw text extracted before react-markdown's children are
 * rendered, so copying yields exactly what the model wrote — no highlight
 * markup, no lost newlines.
 */
export function CodeBlock({
  language,
  source,
  children,
}: {
  language?: string
  source: string
  children?: React.ReactNode
}) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | null>(null)

  useEffect(() => () => { if (timer.current != null) window.clearTimeout(timer.current) }, [])

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(source)
      setCopied(true)
      if (timer.current != null) window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard is permission-gated and unavailable over plain http on some
      // hosts; the block is still selectable by hand, so stay quiet.
    }
  }, [source])

  return (
    <div className={`code-block ${language || source ? 'has-head' : ''}`}>
      <div className="code-block-head">
        <span>{language || 'text'}</span>
        <button type="button" className="code-block-copy" onClick={copy} title="Copy this block">
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="bg-zinc-900 rounded p-3 overflow-x-auto text-xs">{children}</pre>
    </div>
  )
}
