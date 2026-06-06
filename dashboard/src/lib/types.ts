// All API response shapes — field names match Python tool return values exactly.

export interface WANInterface {
  link: 'up' | 'down'
  ip: string | null
  gateway: string | null
}

export interface WANProbe {
  avg_latency_ms: number | null
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
  hostname?: string
  cpu_percent?: number
  mem_percent?: number
  uptime_seconds?: number
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
  backhaul: string[] | null
  signal_level_dbm: number | null
}

export interface MeshHealth {
  success: boolean
  nodes: MeshNode[]
  node_count: number
  cpu_percent?: number
  mem_percent?: number
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

export interface PingResult {
  success: boolean
  host: string
  packets_sent?: number
  packet_loss_pct?: number
  avg_ms?: number | null
  reachable?: boolean
  error?: string
  suggestion?: string
}

export interface TracerouteHop {
  hop: number
  ip: string | null
  ms: number | null
  timeout?: boolean
}

export interface TracerouteResult {
  success: boolean
  host: string
  hops: TracerouteHop[]
  raw?: string
  error?: string
  suggestion?: string
}

export interface SpeedtestResult {
  success: boolean
  download_mbps?: number
  upload_mbps?: number
  ping_ms?: number
  server?: string
  server_location?: string
  error?: string
  suggestion?: string
}

export interface DnsLookupResult {
  success: boolean
  hostname: string
  dns_server?: string
  addresses?: string[]
  elapsed_ms?: number
  error?: string
  suggestion?: string
}

export interface WANProbeResult {
  avg_latency_ms: number | null
  packet_loss_pct: number
  degraded: boolean
}

export interface WANHealthCompare {
  success: boolean
  wan1_probe?: WANProbeResult | null
  wan2_probe?: WANProbeResult | null
  recommendation?: string
  restored?: boolean
  error?: string
}

export interface WANSpeedMeasure {
  latency_ms?: number | null
  packet_loss_pct?: number
  download_mbps?: number
  upload_mbps?: number
  server?: string
}

export interface WANSpeedCompare {
  success: boolean
  quick: boolean
  wan1?: WANSpeedMeasure | null
  wan2?: WANSpeedMeasure | null
  recommendation?: string
  restored?: boolean
  error?: string
}

export interface GravityResult {
  success: boolean
  message?: string
  error?: string
}

export interface TopClient {
  ip: string
  name: string
  count: number
}

export interface TopClientsResult {
  success: boolean
  clients: TopClient[]
  error?: string
}

export interface PiholeClientEntry {
  ip: string
  hostname: string
  query_count: number
  last_query: number
}

export interface PiholeClientsResult {
  success: boolean
  clients: PiholeClientEntry[]
  error?: string
}

export interface PiholeDomainListEntry {
  domain: string
  kind: 'exact' | 'regex'
  enabled: boolean
  comment: string
}

export interface DomainLists {
  success: boolean
  allow: PiholeDomainListEntry[]
  block: PiholeDomainListEntry[]
  error?: string
}
