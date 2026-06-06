import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { formatDistanceToNow } from 'date-fns'
import { api } from '@/lib/api'
import { formatUptime } from '@/lib/utils'
import type { TopClientsResult, PiholeClientsResult, DomainLists } from '@/lib/types'
import { Switch } from '@/components/ui/switch'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'

function AddDomainDialog({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false)
  const [domain, setDomain] = useState('')
  const [listType, setListType] = useState('block')
  const [kind, setKind] = useState('exact')

  const handleAdd = async () => {
    if (!domain.trim()) return
    try {
      await api.addDomain(domain.trim(), listType, kind)
      toast.success(`Added ${domain.trim()} to ${listType}list`)
      onAdded()
      setOpen(false)
      setDomain('')
    } catch {
      toast.error('Failed to add domain')
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" className="h-7 text-xs">+ Add Domain</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add Domain to Pi-hole List</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-2">
          <div className="space-y-1">
            <Label>Domain</Label>
            <Input
              value={domain}
              onChange={e => setDomain(e.target.value)}
              placeholder="ads.example.com"
              onKeyDown={e => e.key === 'Enter' && handleAdd()}
            />
          </div>
          <div className="space-y-1">
            <Label>List</Label>
            <select
              className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm"
              value={listType}
              onChange={e => setListType(e.target.value)}
            >
              <option value="block">Blocklist</option>
              <option value="allow">Allowlist</option>
            </select>
          </div>
          <div className="space-y-1">
            <Label>Type</Label>
            <select
              className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm"
              value={kind}
              onChange={e => setKind(e.target.value)}
            >
              <option value="exact">Exact</option>
              <option value="regex">Regex</option>
            </select>
          </div>
          <Button onClick={handleAdd} className="w-full">Add</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

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

  const { data: topClients, isLoading: topClientsLoading, refetch: refetchTopClients } = useQuery<TopClientsResult>({
    queryKey: ['pihole-top-clients'],
    queryFn: api.getPiholeTopClients,
  })

  const { data: allClients, isLoading: allClientsLoading, refetch: refetchAllClients } = useQuery<PiholeClientsResult>({
    queryKey: ['pihole-clients'],
    queryFn: api.getPiholeClients,
  })

  const { data: domainLists, isLoading: domainListsLoading, refetch: refetchDomains } = useQuery<DomainLists>({
    queryKey: ['pihole-domains'],
    queryFn: api.getDomainLists,
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
      {/* Pi-hole system */}
      {system?.success && (
        <div className="rounded-lg border border-border bg-card p-4">
          <h3 className="text-sm font-medium mb-3">Pi-hole System (Raspberry Pi)</h3>
          <div className="flex gap-6 text-sm">
            <div><span className="text-muted-foreground">CPU (1m):</span> {system.cpu_load_1m.toFixed(2)}</div>
            <div><span className="text-muted-foreground">CPU (5m):</span> {system.cpu_load_5m.toFixed(2)}</div>
            <div><span className="text-muted-foreground">RAM:</span> {ramPct}% ({system.ram_used_mb} / {system.ram_total_mb} MB)</div>
            <div><span className="text-muted-foreground">Uptime:</span> {formatUptime(system.uptime_seconds)}</div>
          </div>
        </div>
      )}

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

      {/* Top Pi-hole clients */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium">Top Clients Today</h3>
          <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => refetchTopClients()}>↻</Button>
        </div>
        {topClientsLoading ? (
          <div className="text-sm text-muted-foreground">Loading...</div>
        ) : topClients?.success ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">IP</TableHead>
                <TableHead className="text-xs">Hostname</TableHead>
                <TableHead className="text-xs text-right">Queries</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(topClients.clients ?? []).map((c, i) => (
                <TableRow key={i}>
                  <TableCell className="text-xs font-mono">{c.ip}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{c.name || '—'}</TableCell>
                  <TableCell className="text-xs text-right">{c.count.toLocaleString()}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="text-sm text-muted-foreground">{topClients?.error ?? 'Could not load clients'}</div>
        )}
      </div>

      {/* Pi-hole known clients (all-time) */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium">Known Clients</h3>
          <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => refetchAllClients()}>↻</Button>
        </div>
        {allClientsLoading ? (
          <div className="text-sm text-muted-foreground">Loading...</div>
        ) : allClients?.success ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">IP</TableHead>
                <TableHead className="text-xs">Hostname</TableHead>
                <TableHead className="text-xs text-right">Total Queries</TableHead>
                <TableHead className="text-xs text-right">Last Seen</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(allClients.clients ?? [])
                .sort((a, b) => b.query_count - a.query_count)
                .map((c, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-xs font-mono">{c.ip}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{c.hostname || '—'}</TableCell>
                    <TableCell className="text-xs text-right">{c.query_count.toLocaleString()}</TableCell>
                    <TableCell className="text-xs text-right text-muted-foreground">
                      {c.last_query ? formatDistanceToNow(new Date(c.last_query * 1000), { addSuffix: true }) : '—'}
                    </TableCell>
                  </TableRow>
                ))}
            </TableBody>
          </Table>
        ) : (
          <div className="text-sm text-muted-foreground">{allClients?.error ?? 'Could not load clients'}</div>
        )}
      </div>

      {/* Domain Allow/Block Manager */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium">Domain Lists</h3>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => refetchDomains()}>↻</Button>
            <AddDomainDialog onAdded={() => refetchDomains()} />
          </div>
        </div>
        {domainListsLoading ? (
          <div className="text-sm text-muted-foreground">Loading...</div>
        ) : domainLists?.success ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {(['allow', 'block'] as const).map(listType => (
              <div key={listType}>
                <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
                  {listType === 'allow' ? 'Allowlist' : 'Blocklist'} ({(domainLists[listType] ?? []).length})
                </div>
                {(domainLists[listType] ?? []).length === 0 ? (
                  <div className="text-xs text-muted-foreground">Empty</div>
                ) : (
                  <div className="space-y-1">
                    {(domainLists[listType] ?? []).map((entry, i) => (
                      <div key={i} className="flex items-center justify-between gap-2 rounded-md border border-border px-2 py-1">
                        <div className="min-w-0">
                          <span className="text-xs font-mono truncate block">{entry.domain}</span>
                          {entry.kind === 'regex' && <span className="text-xs text-muted-foreground">regex</span>}
                        </div>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 px-2 text-xs text-red-500 hover:text-red-600 shrink-0"
                          onClick={async () => {
                            try {
                              await api.removeDomain(listType, entry.kind, entry.domain)
                              toast.success(`Removed ${entry.domain}`)
                              refetchDomains()
                            } catch {
                              toast.error('Failed to remove domain')
                            }
                          }}
                        >
                          ✕
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">{domainLists?.error ?? 'Could not load domain lists'}</div>
        )}
      </div>

    </div>
  )
}
