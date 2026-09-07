import type { Attachment } from '../api/types'
import type { Artifact } from '../artifacts/types'

export interface ResolvedMentions {
  cleanedText: string
  attachmentIds: string[]
  repoRef: boolean
  artifactRefs: string[]
}

function findByName<T extends { name: string }>(items: T[], name: string): T | undefined {
  const query = name.trim().toLowerCase()
  if (!query) return undefined
  return items.find((item) => item.name.toLowerCase() === query)
    ?? items.find((item) => item.name.toLowerCase().startsWith(query))
}

export function resolveMentions(
  rawText: string,
  uploads: Attachment[],
  artifacts: Artifact[],
): ResolvedMentions {
  const attachmentIds: string[] = []
  const artifactRefs: string[] = []
  let cleanedText = rawText.replace(/@file(?::([a-f0-9]{32})|\s+([^\n@]+?))(?=\s+@(?:file|artifact|repo)\b|\n|$)/gi, (token, id: string | undefined, name: string | undefined) => {
    const upload = id
      ? uploads.find((item) => item.id === id)
      : findByName(uploads, name ?? '')
    if (!upload?.id) return token
    if (!attachmentIds.includes(upload.id)) attachmentIds.push(upload.id)
    return ''
  })

  cleanedText = cleanedText.replace(/@artifact\s+([^\n@]+?)(?=\s+@(?:file|artifact|repo)\b|\n|$)/gi, (token, name: string) => {
    const artifact = findByName(artifacts, name)
    if (!artifact) return token
    if (!artifactRefs.includes(artifact.path)) artifactRefs.push(artifact.path)
    return `@artifact:${artifact.path}`
  })

  const repoRef = /@repo\b/i.test(cleanedText)
  cleanedText = cleanedText.replace(/@repo\b/gi, '[repo: project root]')
  cleanedText = cleanedText.replace(/[ \t]{2,}/g, ' ').replace(/ *\n */g, '\n').trim()

  return { cleanedText, attachmentIds, repoRef, artifactRefs }
}
