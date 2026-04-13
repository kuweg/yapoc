export interface VaultNode {
  name: string
  path: string
  is_dir: boolean
  size?: number
  children?: VaultNode[]
}

export type VaultFileType = 'text' | 'image' | 'svg' | 'pdf'

export interface VaultTextFile {
  path: string
  type: 'text'
  content: string
  truncated: boolean
  size: number
  lang: string
}

export interface VaultImageFile {
  path: string
  type: 'image'
  mime: string
  data: string   // base64
  size: number
}

export interface VaultSvgFile {
  path: string
  type: 'svg'
  content: string
  size: number
}

export interface VaultPdfFile {
  path: string
  type: 'pdf'
  data: string   // base64
  size: number
}

export type VaultFile = VaultTextFile | VaultImageFile | VaultSvgFile | VaultPdfFile
