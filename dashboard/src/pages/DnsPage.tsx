import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { formatUptime } from '@/lib/utils'
import { Switch } from '@/components/ui/switch'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Button } from '@/components/ui/button'

export default function DnsPage() {
  const queryClient = useQueryClient()

  const { data: stats } = useQuery({
    queryKey: ['pihole-stats'],
    queryFn: api.getPiholeStats,
    refetchInterval: 30_000,
  })

  const { data: system } = useQuery({
    queryKey: ['pihole-system'],
    queryFn: api.getPiholeSystem,
    refetchInterval: 30_000,
  })

  const { data: topDomains, refetch: refetchTop, isLoading: topLoading } = useQuery({
    queryKey: ['top-domains'],
    queryFn: api.getPiholeTopDomains,
  })

  const handleToggleBlocking = async (checked: boolean) => {
    if (!stats?.success) return
    try {
      await api.setPiholeBlocking(checked)
      queryClient.invalidateQueries({ queryKey: ['pihole-stats'] })
      queryClient.invalidateQueries({ queryKey: ['snapshot'] })
      toast.success(checked ? 'Blocking enabled' : 'Blocking disabled')
    } catch {
      toast.error('Failed to toggle Pi-hole blocking')
    }
  }

  const ramPct = system?.success && system.ram_total_mb
    ? Math.round((system.ram_used_mb / system.ram_total_mb) * 100)
    : null

  return (
    <div className="space-y-6">
      {/* Pi-hole stats bar */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Queries Today</div>
          <div className="text-2xl font-bold">{stats?.queries_today?.toLocaleString() ?? '—'}</div>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Blocked</div>
          <div className="text-2xl font-bold text-violet-500">{stats?.block_pct ?? '—'}%</div>
          <div className="text-xs text-muted-foreground">{stats?.blocked_today?.toLocaleString()} queries</div>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Blocklist</div>
          <div className="text-2xl font-bold">{stats?.domains_blocked?.toLocaleString() ?? '—'}</div>
          <div className="text-xs text-muted-foreground">domains</div>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Blocking</div>
          <div className="flex items-center gap-2 mt-1">
            <Switch
              checked={stats?.enabled ?? false}
              onCheckedChange={handleToggleBlocking}
              disabled={!stats?.success}
            />
            <span className="text-sm font-medium">{stats?.enabled ? 'On' : 'Off'}</span>
          </div>
        </div>
      </div>

      {/* Top domains */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium">Top Queried Domains</h3>
            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => refetchTop()}>↻</Button>
          </div>
          {topLoading ? (
            <div className="text-sm text-muted-foreground">Loading...</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs">Domain</TableHead>
                  <TableHead className="text-xs text-right">Queries</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(topDomains?.queried?.domains ?? []).slice(0, 10).map((d, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-xs font-mono truncate max-w-xs">{d.domain}</TableCell>
                    <TableCell className="text-xs text-right">{d.count.toLocaleString()}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium">Top Blocked Domains</h3>
            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => refetchTop()}>↻</Button>
          </div>
          {topLoading ? (
            <div className="text-sm text-muted-foreground">Loading...</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs">Domain</TableHead>
                  <TableHead className="text-xs text-right">Blocked</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(topDomains?.blocked?.domains ?? []).slice(0, 10).map((d, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-xs font-mono text-red-400 truncate max-w-xs">{d.domain}</TableCell>
                    <TableCell className="text-xs text-right">{d.count.toLocaleString()}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      </div>

      {/* Pi-hole system */}
      {system?.success && (
        <div className="rounded-lg border border-border bg-card p-4">
          <h3 className="text-sm font-medium mb-3">Pi-hole System ({system.hostname})</h3>
          <div className="flex gap-6 text-sm">
            <div><span className="text-muted-foreground">CPU (1m):</span> {system.cpu_load_1m.toFixed(2)}</div>
            <div><span className="text-muted-foreground">CPU (5m):</span> {system.cpu_load_5m.toFixed(2)}</div>
            <div><span className="text-muted-foreground">RAM:</span> {ramPct}% ({system.ram_used_mb} / {system.ram_total_mb} MB)</div>
            <div><span className="text-muted-foreground">Uptime:</span> {formatUptime(system.uptime_seconds)}</div>
          </div>
        </div>
      )}
    </div>
  )
}
