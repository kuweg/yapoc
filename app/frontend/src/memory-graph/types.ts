export interface GraphPoint {
  id: number
  agent: string
  source: string
  content: string
  timestamp: string
  x: number
  y: number
  cluster: number
}

export interface ClusterInfo {
  id: number
  label: string
  color: string
  count: number
}

export interface GraphResponse {
  points: GraphPoint[]
  clusters: ClusterInfo[]
  total: number
}
