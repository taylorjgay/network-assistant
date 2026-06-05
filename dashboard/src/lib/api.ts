import type {
  Snapshot, WANHealth, QueryTrends, TopDomainsResult, PiholeStats,
  PiholeSystem, MeshHealth, DeviceList, UPnPResult, PortForwards,
} from './types'

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`/api${path}`)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
}

async function del<T>(path: string): Promise<T> {
  const resp = await fetch(`/api${path}`, { method: 'DELETE' })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
}

export const api = {
  getHosts: () => get<{ router: string | null; deco: string | null; pihole: string | null }>('/hosts'),
  getSnapshot: () => get<Snapshot>('/snapshot'),
  getWanHealth: () => get<WANHealth>('/wan'),
  compareWan: () => post<unknown>('/wan/compare'),
  setWanPriority: (primary_wan: string) => post<unknown>('/wan/priority', { primary_wan }),

  getPiholeStats: () => get<PiholeStats>('/pihole/stats'),
  getPiholeTrends: () => get<QueryTrends>('/pihole/trends'),
  getPiholeTopDomains: () => get<TopDomainsResult>('/pihole/top-domains'),
  getPiholeSystem: () => get<PiholeSystem>('/pihole/system'),
  setPiholeBlocking: (enabled: boolean) => post<unknown>('/pihole/blocking', { enabled }),

  getMeshHealth: () => get<MeshHealth>('/mesh'),

  getDevices: () => get<DeviceList>('/devices'),
  scanDevices: () => post<DeviceList>('/devices/scan'),
  labelDevice: (mac: string, label: string) =>
    post<unknown>(`/devices/${encodeURIComponent(mac)}/label`, { label }),
  removeDeviceLabel: (mac: string) =>
    del<unknown>(`/devices/${encodeURIComponent(mac)}/label`),

  getUpnp: () => get<UPnPResult>('/upnp'),

  getPortForwards: () => get<PortForwards>('/ports'),
  addPortForward: (data: {
    name: string; external_port: number; internal_ip: string;
    internal_port: number; protocol: string
  }) => post<unknown>('/ports', data),
  removePortForward: (ruleId: string) =>
    del<unknown>(`/ports/${encodeURIComponent(ruleId)}`),
}
