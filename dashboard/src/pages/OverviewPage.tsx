import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts'
import { api } from '@/lib/api'
import { formatUptime } from '@/lib/utils'
import { StatCard } from '@/components/StatCard'
import { StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'

export default function OverviewPage() {
  const queryClient = useQueryClient()

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

  const handleToggleBlocking = async () => {
    if (!snap?.pihole?.success) return
    try {
      await api.setPiholeBlocking(!snap.pihole.enabled)
      queryClient.invalidateQueries({ queryKey: ['snapshot'] })
      toast.success(snap.pihole.enabled ? 'Pi-hole blocking disabled' : 'Pi-hole blocking enabled')
    } catch {
      toast.error('Failed to toggle Pi-hole blocking')
    }
  }

  const handleSwitchWan = async (wan: string) => {
    try {
      await api.setWanPriority(wan)
      queryClient.invalidateQueries({ queryKey: ['snapshot'] })
      toast.success(`Switched active WAN to ${wan}`)
    } catch {
      toast.error('Failed to switch WAN')
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

  return (
    <div className="space-y-6">
      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <StatCard
          title="WAN1"
          value={<StatusBadge online={wan1Up} />}
          subtitle={probe && wan1Up ? `${probe.latency_ms?.toFixed(0) ?? '—'}ms · ${probe.packet_loss_pct}% loss` : undefined}
          action={activeWan !== 'WAN1' && wan1Up ? (
            <Button size="sm" variant="outline" onClick={() => handleSwitchWan('WAN1')}>
              Set Active
            </Button>
          ) : activeWan === 'WAN1' ? (
            <Badge variant="secondary">Active</Badge>
          ) : undefined}
        />
        <StatCard
          title="WAN2"
          value={<StatusBadge online={wan2Up} />}
          subtitle={probe && wan2Up ? `${probe.latency_ms?.toFixed(0) ?? '—'}ms · ${probe.packet_loss_pct}% loss` : undefined}
          action={activeWan !== 'WAN2' && wan2Up ? (
            <Button size="sm" variant="outline" onClick={() => handleSwitchWan('WAN2')}>
              Set Active
            </Button>
          ) : activeWan === 'WAN2' ? (
            <Badge variant="secondary">Active</Badge>
          ) : undefined}
        />
        <StatCard
          title="Pi-hole"
          value={pihole?.success ? `${pihole.block_pct}% blocked` : '—'}
          subtitle={pihole?.success ? `${pihole.queries_today.toLocaleString()} queries today` : pihole?.error}
          action={pihole?.success ? (
            <div className="flex items-center gap-2">
              <Switch
                checked={pihole.enabled}
                onCheckedChange={handleToggleBlocking}
              />
              <span className="text-xs text-muted-foreground">
                {pihole.enabled ? 'Blocking on' : 'Blocking off'}
              </span>
            </div>
          ) : undefined}
        />
        <StatCard
          title="Mesh"
          value={mesh?.success ? `${mesh.node_count} / ${mesh.nodes.length} online` : '—'}
          subtitle={mesh?.success ? (mesh.node_count === mesh.nodes.length ? 'All nodes healthy' : 'Some nodes offline') : mesh?.error}
        />
        <StatCard
          title="Router"
          value={router?.success ? (router.model ?? 'ER605') : '—'}
          subtitle={router?.success ? `Uptime: ${formatUptime(router.uptime_seconds)}` : router?.error}
        />
      </div>

      {/* Query trends chart */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium text-muted-foreground mb-4">
          DNS Query Trends — Last 24 Hours
        </h3>
        {trends?.success && trends.hours.length > 0 ? (
          <ResponsiveContainer width="100%" height={160}>
            <AreaChart data={trends.hours} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="gradTotal" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
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
              <Area type="monotone" dataKey="total" stroke="#6366f1" fill="url(#gradTotal)" name="Total" />
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
