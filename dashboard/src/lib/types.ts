// All API response shapes — field names match Python tool return values exactly.

export interface WANInterface {
  link: 'up' | 'down'
  ip: string | null
  gateway: string | null
}

export interface WANProbe {
  latency_ms: number | null
  packet_loss_pct: number
}

export interface WANHealth {
  success: boolean
  active_wan: 'WAN1' | 'WAN2' | null
  wan1: WANInterface | null
  wan2: WANInterface | null
  probe: WANProbe | null
  degraded: boolean
  error?: string
}

export interface PiholeStats {
  success: boolean
  queries_today: number
  blocked_today: number
  block_pct: number
  domains_blocked: number
  enabled: boolean
  error?: string
}

export interface MeshNode {
  mac: string | null
  ip: string | null
  nickname: string | null
  is_primary: boolean
  mesh_status: string
  inet_status: string | null
  inet_error: string | null
  backhaul: string | null
  signal_level_dbm: number | null
}

export interface MeshHealth {
  success: boolean
  nodes: MeshNode[]
  node_count: number
  error?: string
}

export interface RouterInfo {
  success: boolean
  model: string | null
  firmware: string | null
  uptime_seconds: number | null
  cpu_percent: number | null
  mem_percent: number | null
  error?: string
}

export interface Snapshot {
  wan: WANHealth
  pihole: PiholeStats
  mesh: MeshHealth
  router: RouterInfo
}

export interface TrendHour {
  hour: string
  total: number
  blocked: number
  block_pct: number
}

export interface QueryTrends {
  success: boolean
  hours: TrendHour[]
  summary: {
    total_24h: number
    blocked_24h: number
    block_pct_24h: number
    avg_per_hour: number
    spike_hours: number[]
  }
  error?: string
}

export interface DomainEntry {
  domain: string
  count: number
}

export interface TopDomainsResult {
  queried: { success: boolean; domains: DomainEntry[]; blocked_filter: boolean; error?: string }
  blocked: { success: boolean; domains: DomainEntry[]; blocked_filter: boolean; error?: string }
}

export interface PiholeSystem {
  success: boolean
  hostname: string
  uptime_seconds: number
  cpu_load_1m: number
  cpu_load_5m: number
  cpu_load_15m: number
  ram_total_mb: number
  ram_used_mb: number
  ram_free_mb: number
  error?: string
}

export interface Device {
  ip: string
  mac: string | null
  label: string | null
  hostname: string | null
  vendor: string | null
  deco_node: string | null
  deco_signal_dbm: number | null
  connection_type: string | null
  pihole_queries_today: number | null
  pihole_last_seen: string | null
}

export interface DeviceList {
  success: boolean
  deep_scan: boolean
  device_count: number
  devices: Device[]
  error?: string
}

export interface UPnPMapping {
  external_port: number
  protocol: string
  internal_host: string
  internal_port: number
  description: string
  enabled: boolean
  remote_host: string
  lease_seconds: number
}

export interface UPnPResult {
  status: { success: boolean; available?: boolean; external_ip?: string; connected?: boolean; error?: string }
  portmaps: { success: boolean; available?: boolean; count?: number; mappings: UPnPMapping[]; error?: string }
}

export interface PortForward {
  id: string | null
  name: string
  external_port: number
  internal_ip: string
  internal_port: number
  protocol: string
}

export interface PortForwards {
  success: boolean
  rules: PortForward[]
  error?: string
}
