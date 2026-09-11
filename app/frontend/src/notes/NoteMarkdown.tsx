import { Children, isValidElement, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import hljs from 'highlight.js/lib/common'
import { findNote, type NoteSummary } from './api'

interface Node { type: string; value?: string; url?: string; children?: Node[]; data?: { hName?: string; hProperties?: Record<string, string> } }
/** Transform Markdown text nodes only: links inside code fences stay literal. */
function remarkNoteSyntax() {
  return (tree: Node) => {
    function visit(node: Node) {
      if (['code', 'inlineCode', 'link', 'image', 'html'].includes(node.type)) return
      if (node.type === 'blockquote') {
        const first = node.children?.[0]?.children?.[0]
        const callout = first?.value?.match(/^\[!([A-Za-z]+)\][+-]?\s*/)
        if (first && callout) {
          node.data = { hProperties: { 'data-callout': callout[1].toLowerCase() } }
          first.value = first.value!.replace(callout[0], `${callout[1].toUpperCase()} — `)
        }
      }
      if (!node.children) return
      node.children = node.children.flatMap(child => {
        if (child.type !== 'text' || !child.value) { visit(child); return [child] }
        const text = child.value, result: Node[] = []
        const pattern = /(?<!!)\[\[([^\]\n]+)\]\]|==([^=\n]+)==/g
        let end = 0, match: RegExpExecArray | null
        while ((match = pattern.exec(text))) {
          if (match.index > end) result.push({ type: 'text', value: text.slice(end, match.index) })
          if (match[1]) {
            const [target, alias] = match[1].split('|', 2)
            result.push({ type: 'link', url: `#note:${encodeURIComponent(target.trim())}`, children: [{ type: 'text', value: alias || target }] })
          } else result.push({ type: 'strong', data: { hName: 'mark' }, children: [{ type: 'text', value: match[2] }] })
          end = pattern.lastIndex
        }
        if (end < text.length) result.push({ type: 'text', value: text.slice(end) })
        return result.length ? result : [child]
      })
    }
    visit(tree)
  }
}
const plainText = (children: ReactNode): string => Children.toArray(children).map(child => isValidElement<{ children?: ReactNode }>(child) ? plainText(child.props.children) : String(child)).join('')
export const headingId = (text: string) => text.toLocaleLowerCase().trim().replace(/[^\p{L}\p{N}\s_-]/gu, '').replace(/\s+/g, '-')

export function NoteMarkdown({ content, notes, onNavigate }: { content: string; notes: NoteSummary[]; onNavigate: (target: string) => void }) {
  const heading = (level: 1 | 2 | 3 | 4 | 5 | 6) => ({ children }: { children?: ReactNode }) => {
    const Tag = `h${level}` as const
    return <Tag id={`note-heading-${headingId(plainText(children))}`}>{children}</Tag>
  }
  return <article className="note-markdown" aria-label="Note preview">
    <ReactMarkdown remarkPlugins={[remarkGfm, remarkNoteSyntax]} components={{
      h1: heading(1), h2: heading(2), h3: heading(3), h4: heading(4), h5: heading(5), h6: heading(6),
      a: ({ href, children }) => {
        const wiki = href?.startsWith('#note:')
        const markdownNote = href && !/^(?:[a-z]+:|\/\/)/i.test(href) && /\.md(?:#.*)?$/i.test(href)
        if (wiki || markdownNote) {
          let target = href!
          try { target = decodeURIComponent(wiki ? href!.slice(6) : href!) } catch { /* use original invalid encoding */ }
          const exists = !target.split('#')[0] || Boolean(findNote(notes, target))
          return <button className={`note-wikilink ${exists ? '' : 'is-missing'}`} title={exists ? `Open ${target}` : `Create ${target}`}
            onClick={() => onNavigate(target)}>{children}</button>
        }
        if (href?.startsWith('#')) return <button className="note-wikilink" onClick={() => onNavigate(href)}>{children}</button>
        return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
      },
      code: ({ className, children }) => {
        const language = className?.match(/language-(\S+)/)?.[1]
        if (language && hljs.getLanguage(language)) return <code className={`${className} hljs`} dangerouslySetInnerHTML={{ __html: hljs.highlight(String(children), { language }).value }} />
        return <code className={className}>{children}</code>
      },
    }}>{content || '*This note is empty. Switch to Edit to start writing.*'}</ReactMarkdown>
  </article>
}
