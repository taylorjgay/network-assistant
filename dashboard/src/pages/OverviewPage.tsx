import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts'
import { api } from '@/lib/api'
import { formatUptime } from '@/lib/utils'
import { StatusBadge } from '@/components/StatusBadge'
import { Switch } from '@/components/ui/switch'

const nodeName = (nickname: string | null, fallbackIndex: number) =>
  nickname ? nickname.charAt(0).toUpperCase() + nickname.slice(1) : `Node ${fallbackIndex + 1}`

export default function OverviewPage() {
  const queryClient = useQueryClient()

  const { data: hosts } = useQuery({
    queryKey: ['hosts'],
    queryFn: api.getHosts,
    staleTime: Infinity,
  })

  const { data: snap, isLoading } = useQuery({
    queryKey: ['snapshot'],
    queryFn: api.getSnapshot,
    refetchInterval: 30_000,
  })

  const { data: trends } = useQuery({
    queryKey: ['trends'],
    queryFn: api.getPiholeTrends,
    refetchInterval: 300_000,
  })

  const handleToggleBlocking = async (checked: boolean) => {
    if (!snap?.pihole?.success) return
    try {
      await api.setPiholeBlocking(checked)
      queryClient.invalidateQueries({ queryKey: ['snapshot'] })
      toast.success(checked ? 'Pi-hole blocking enabled' : 'Pi-hole blocking disabled')
    } catch {
      toast.error('Failed to toggle Pi-hole blocking')
    }
  }

  if (isLoading) {
    return <div className="text-muted-foreground text-sm">Loading...</div>
  }

  const wan1Up = snap?.wan?.wan1?.link === 'up'
  const wan2Up = snap?.wan?.wan2?.link === 'up'
  const activeWan = snap?.wan?.active_wan
  const probe = snap?.wan?.probe
  const pihole = snap?.pihole
  const mesh = snap?.mesh
  const router = snap?.router

  const wans = [
    { label: 'WAN1', up: wan1Up, data: snap?.wan?.wan1 },
    { label: 'WAN2', up: wan2Up, data: snap?.wan?.wan2 },
  ]

  const sortedNodes = [...(mesh?.nodes ?? [])].sort((a, b) => {
    if (a.is_primary !== b.is_primary) return a.is_primary ? -1 : 1
    return (a.nickname ?? '').localeCompare(b.nickname ?? '')
  })

  return (
    <div className="space-y-6">
      {/* Three summary cards */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:items-stretch">

        {/* Router + WAN */}
        <div className="rounded-lg border border-border bg-card p-4 flex flex-col gap-4">
          <div>
            <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Router</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              {router?.success
                ? [
                    router.model,
                    router.cpu_percent != null ? `CPU ${router.cpu_percent}%` : null,
                    router.mem_percent != null ? `Mem ${router.mem_percent}%` : null,
                    router.uptime_seconds != null ? `up ${formatUptime(router.uptime_seconds)}` : null,
                  ].filter(Boolean).join(' · ')
                : (router?.error ?? '')}
            </div>
          </div>
          <div className="space-y-2">
            {wans.map(({ label, up, data }) => {
              const isActive = activeWan === label
              return (
                <div key={label} className="flex items-center gap-3 text-sm">
                  <StatusBadge online={up} />
                  <span className="font-medium w-12 shrink-0">{label}</span>
                  <span className="text-xs text-muted-foreground flex-1 truncate">
                    {up ? (data?.ip ?? '—') : 'Down'}
                    {up && probe ? ` · ${probe.avg_latency_ms?.toFixed(0)}ms` : ''}
                  </span>
                  <div className="shrink-0">
                    {isActive
                      ? <span className="text-xs font-medium text-green-500">Active</span>
                      : up
                        ? <span className="text-xs text-muted-foreground">Standby</span>
                        : null}
                  </div>
                </div>
              )
            })}
          </div>
          <div className="mt-auto">
            {hosts?.router && (
              <a href={hosts.router} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center text-xs text-muted-foreground hover:text-foreground transition-colors">
                Open Router UI ↗
              </a>
            )}
          </div>
        </div>

        {/* Deco Mesh */}
        <div className="rounded-lg border border-border bg-card p-4 flex flex-col gap-4">
          <div>
            <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Deco Mesh</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              {mesh?.success
                ? [
                    'Deco X55',
                    mesh.cpu_percent != null ? `CPU ${mesh.cpu_percent}%` : null,
                    mesh.mem_percent != null ? `Mem ${mesh.mem_percent}%` : null,
                  ].filter(Boolean).join(' · ')
                : ''}
            </div>
          </div>
          {mesh?.success ? (
            <div className="space-y-2">
              {sortedNodes.map((node, i) => (
                <div key={i} className="flex items-center gap-2 text-sm">
                  <StatusBadge online={node.mesh_status === 'connected'} />
                  <span className="font-medium">{nodeName(node.nickname, i)}</span>
                  <span className="ml-auto">
                    {node.is_primary
                      ? <span className="text-xs font-medium text-green-500">Primary</span>
                      : node.backhaul?.includes('wired')
                        ? <span className="text-xs text-muted-foreground">Wired</span>
                        : node.signal_level_dbm != null
                          ? <span className="text-xs text-muted-foreground">{node.signal_level_dbm} dBm</span>
                          : null}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">{mesh?.error ?? 'Could not reach Deco'}</div>
          )}
          <div className="mt-auto">
            {hosts?.deco && (
              <a href={hosts.deco} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center text-xs text-muted-foreground hover:text-foreground transition-colors">
                Open Deco UI ↗
              </a>
            )}
          </div>
        </div>

        {/* Pi-hole */}
        <div className="rounded-lg border border-border bg-card p-4 flex flex-col gap-4">
          <div>
            <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Pi-hole</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              {pihole?.success
                ? [
                    'Raspberry Pi',
                    pihole.cpu_percent != null ? `CPU ${pihole.cpu_percent}%` : null,
                    pihole.mem_percent != null ? `Mem ${pihole.mem_percent}%` : null,
                    pihole.uptime_seconds != null ? `up ${formatUptime(pihole.uptime_seconds)}` : null,
                  ].filter(Boolean).join(' · ')
                : ''}
            </div>
          </div>
          {pihole?.success ? (
            <div className="space-y-2">
              <div className="flex items-center gap-3 text-sm">
                <span className="text-muted-foreground flex-1 text-xs">Queries today</span>
                <span className="font-medium text-xs">{pihole.queries_today.toLocaleString()}</span>
              </div>
              <div className="flex items-center gap-3 text-sm">
                <span className="text-muted-foreground flex-1 text-xs">Blocked</span>
                <span className="font-medium text-xs">{pihole.block_pct}%</span>
              </div>
              <div className="flex items-center gap-3 text-sm">
                <span className="text-muted-foreground flex-1 text-xs">Domains on blocklist</span>
                <span className="font-medium text-xs">{pihole.domains_blocked.toLocaleString()}</span>
              </div>
              <div className="flex items-center gap-3 text-sm">
                <span className="text-muted-foreground flex-1 text-xs">DNS blocking</span>
                <div className="flex items-center gap-1.5">
                  <Switch checked={pihole.enabled} onCheckedChange={handleToggleBlocking} />
                  {pihole.enabled && <span className="text-xs font-medium text-green-500">Active</span>}
                </div>
              </div>
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">{pihole?.error ?? 'Could not reach Pi-hole'}</div>
          )}
          <div className="mt-auto">
            {hosts?.pihole && (
              <a href={hosts.pihole} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center text-xs text-muted-foreground hover:text-foreground transition-colors">
                Open Pi-hole UI ↗
              </a>
            )}
          </div>
        </div>
      </div>

      {/* DNS Query Trends */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium text-muted-foreground mb-4">
          DNS Query Trends — Last 24 Hours
        </h3>
        {trends?.success && trends.hours.length > 0 ? (
          <ResponsiveContainer width="100%" height={160}>
            <AreaChart data={trends.hours} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="gradTotal" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#94a3b8" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#94a3b8" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gradBlocked" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#f87171" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#f87171" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="hour"
                tickFormatter={(v) => `${new Date(v).getHours()}h`}
                tick={{ fontSize: 10 }}
                interval="preserveStartEnd"
              />
              <YAxis tick={{ fontSize: 10 }} width={40} />
              <Tooltip
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                formatter={(v: any, name: any) => [typeof v === 'number' ? v.toLocaleString() : v, String(name ?? '')]}
                labelFormatter={(l) => new Date(l).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              />
              <Area type="monotone" dataKey="total" stroke="#94a3b8" fill="url(#gradTotal)" name="Total" />
              <Area type="monotone" dataKey="blocked" stroke="#f87171" fill="url(#gradBlocked)" name="Blocked" />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-40 flex items-center justify-center text-muted-foreground text-sm">
            {trends?.error ?? 'No trend data available'}
          </div>
        )}
        {trends?.summary && (
          <div className="flex gap-4 mt-2 text-xs text-muted-foreground">
            <span>Total 24h: <strong>{trends.summary.total_24h.toLocaleString()}</strong></span>
            <span>Blocked: <strong>{trends.summary.blocked_24h.toLocaleString()} ({trends.summary.block_pct_24h}%)</strong></span>
            {trends.summary.spike_hours.length > 0 && (
              <span className="text-amber-500">Spikes at: {trends.summary.spike_hours.map(h => `${h}h`).join(', ')}</span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
