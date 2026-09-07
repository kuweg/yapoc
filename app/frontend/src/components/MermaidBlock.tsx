import { useEffect, useId, useRef, useState } from 'react'

/**
 * Safely renders Mermaid source in a sandboxed iframe. The diagram renderer is
 * loaded inside the iframe, keeping Mermaid-generated SVG/DOM out of the chat
 * document. The backend validates source before it reaches this component; the
 * iframe also uses Mermaid's strict security mode as defense in depth.
 */
export default function MermaidBlock({ source }: { source: string }) {
  const frameRef = useRef<HTMLIFrameElement>(null)
  const [height, setHeight] = useState(160)
  const id = useId().replace(/:/g, '')

  useEffect(() => {
    const frame = frameRef.current
    if (!frame) return

    const onMessage = (event: MessageEvent) => {
      if (event.source !== frame.contentWindow) return
      const data = event.data as { type?: string; id?: string; height?: unknown }
      if (data?.type !== 'mermaid-height' || data.id !== id || typeof data.height !== 'number') return
      setHeight(Math.max(120, Math.min(2000, Math.ceil(data.height))))
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [id])

  const srcDoc = `<!doctype html>
<html><head><meta charset="utf-8"><style>
html,body{margin:0;background:transparent;color:#e4e4e7;font-family:ui-sans-serif,system-ui,sans-serif}
#diagram{padding:12px;overflow:auto;text-align:center}svg{max-width:100%;height:auto}
.error{color:#fca5a5;text-align:left;font:12px ui-monospace,monospace;white-space:pre-wrap}
</style></head><body><div id="diagram"></div><script type="module">
const source = ${JSON.stringify(source)};
const diagramId = ${JSON.stringify(`mermaid-${id}`)};
const report = () => parent.postMessage({type:'mermaid-height',id:${JSON.stringify(id)},height:document.documentElement.scrollHeight}, '*');
try {
  const mermaid = (await import('https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs')).default;
  mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:'dark'});
  const {svg} = await mermaid.render(diagramId, source);
  document.getElementById('diagram').innerHTML = svg;
} catch (error) {
  document.getElementById('diagram').textContent = 'Unable to render Mermaid diagram: ' + (error instanceof Error ? error.message : String(error));
  document.getElementById('diagram').className = 'error';
}
requestAnimationFrame(report);
new ResizeObserver(report).observe(document.body);
</script></body></html>`

  return (
    <div className="w-full my-1 overflow-hidden rounded-xl border border-zinc-700/70 bg-zinc-900/60">
      <iframe
        ref={frameRef}
        title="Mermaid diagram"
        sandbox="allow-scripts"
        srcDoc={srcDoc}
        className="block w-full border-0"
        style={{ height }}
      />
    </div>
  )
}
