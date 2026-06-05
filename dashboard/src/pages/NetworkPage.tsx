import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import type { Device } from '@/lib/types'
import { cn } from '@/lib/utils'

function LabelDialog({ device, onLabeled }: { device: Device; onLabeled: () => void }) {
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState(device.label ?? '')

  const handleSave = async () => {
    try {
      if (value.trim()) {
        await api.labelDevice(device.mac ?? device.ip, value.trim())
        toast.success(`Labeled ${device.ip}`)
      } else {
        await api.removeDeviceLabel(device.mac ?? device.ip)
        toast.success('Label removed')
      }
      onLabeled()
      setOpen(false)
    } catch {
      toast.error('Failed to update label')
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" className="h-7 px-2 text-xs">
          {device.label ? 'Edit' : 'Label'}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Label device — {device.ip}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-2">
          <div className="space-y-1">
            <Label>Label (leave blank to remove)</Label>
            <Input
              value={value}
              onChange={e => setValue(e.target.value)}
              placeholder="e.g. Xbox Series X"
              onKeyDown={e => e.key === 'Enter' && handleSave()}
            />
          </div>
          <Button onClick={handleSave} className="w-full">Save</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

const nodeName = (nickname: string | null, fallbackIndex: number) =>
  nickname ? nickname.charAt(0).toUpperCase() + nickname.slice(1) : `Node ${fallbackIndex + 1}`

const sortNodes = <T extends { is_primary: boolean; nickname: string | null }>(nodes: T[]) =>
  [...nodes].sort((a, b) => {
    if (a.is_primary !== b.is_primary) return a.is_primary ? -1 : 1
    return (a.nickname ?? '').localeCompare(b.nickname ?? '')
  })

function formatBackhaul(backhaul: string[] | null, isPrimary: boolean): string {
  if (isPrimary) return 'wired to router'
  if (!backhaul || backhaul.length === 0) return 'unknown backhaul'
  return backhaul
    .map(b => b === 'band2_4' ? '2.4 GHz' : b === 'band5' ? '5 GHz' : b === 'band6' ? '6 GHz' : b)
    .join(' + ')
}

function signalQuality(dbm: number | null): { label: string; className: string } | null {
  if (dbm == null) return null
  if (dbm >= -50) return { label: 'Excellent', className: 'text-green-500' }
  if (dbm >= -65) return { label: 'Good', className: 'text-green-400' }
  if (dbm >= -75) return { label: 'Fair', className: 'text-yellow-500' }
  return { label: 'Poor', className: 'text-red-400' }
}

export default function NetworkPage() {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [scanning, setScanning] = useState(false)

  const { data: mesh, isLoading: meshLoading } = useQuery({
    queryKey: ['mesh'],
    queryFn: api.getMeshHealth,
    refetchInterval: 30_000,
  })

  const { data: deviceData, isLoading: devicesLoading } = useQuery({
    queryKey: ['devices'],
    queryFn: api.getDevices,
    staleTime: 60_000,
    refetchOnMount: true,
  })

  const handleDeepScan = async () => {
    setScanning(true)
    try {
      const result = await api.scanDevices()
      queryClient.setQueryData(['devices'], result)
      toast.success('Deep scan complete')
    } catch {
      toast.error('Scan failed')
    } finally {
      setScanning(false)
    }
  }

  const filteredDevices = (deviceData?.devices ?? []).filter(d => {
    const q = search.toLowerCase()
    return (
      d.ip.includes(q) ||
      (d.hostname ?? '').toLowerCase().includes(q) ||
      (d.label ?? '').toLowerCase().includes(q) ||
      (d.vendor ?? '').toLowerCase().includes(q)
    )
  })

  return (
    <div className="space-y-6">
      {/* Mesh nodes */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium mb-3">Deco Mesh Nodes</h3>
        {meshLoading ? (
          <div className="text-sm text-muted-foreground">Loading...</div>
        ) : mesh?.success ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs w-8"></TableHead>
                <TableHead className="text-xs">Node</TableHead>
                <TableHead className="text-xs">Backhaul</TableHead>
                <TableHead className="text-xs">Signal</TableHead>
                <TableHead className="text-xs">IP</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortNodes(mesh.nodes).map((node, i) => {
                const sig = signalQuality(node.signal_level_dbm)
                return (
                  <TableRow key={i}>
                    <TableCell><StatusBadge online={node.mesh_status === 'connected'} /></TableCell>
                    <TableCell className="text-xs font-medium">
                      <span>{nodeName(node.nickname, i)}</span>
                      {node.is_primary && <Badge variant="secondary" className="ml-2 text-xs">Primary</Badge>}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatBackhaul(node.backhaul, node.is_primary)}
                    </TableCell>
                    <TableCell className="text-xs">
                      {node.signal_level_dbm != null ? (
                        <span>
                          {node.signal_level_dbm} dBm
                          {sig && !node.backhaul?.includes('wired') && (
                            <span className={cn('ml-1.5 font-medium', sig.className)}>({sig.label})</span>
                          )}
                        </span>
                      ) : '—'}
                    </TableCell>
                    <TableCell className="text-xs font-mono text-muted-foreground">{node.ip ?? '—'}</TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        ) : (
          <div className="text-sm text-muted-foreground">{mesh?.error ?? 'Could not reach Deco'}</div>
        )}
      </div>

      {/* Device inventory */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium">
            Device Inventory
            {deviceData?.device_count != null && (
              <span className="text-muted-foreground font-normal ml-2">
                · {deviceData.device_count} devices
              </span>
            )}
          </h3>
          <div className="flex items-center gap-2">
            <Input
              placeholder="Search..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="h-7 w-48 text-xs"
            />
            <Button
              size="sm"
              variant="outline"
              onClick={handleDeepScan}
              disabled={scanning}
              className="h-7 text-xs"
            >
              {scanning ? 'Scanning...' : '↻ Scan'}
            </Button>
          </div>
        </div>
        {devicesLoading ? (
          <div className="text-sm text-muted-foreground">Loading...</div>
        ) : deviceData?.success ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">IP</TableHead>
                <TableHead className="text-xs">Hostname / Label</TableHead>
                <TableHead className="text-xs">Vendor</TableHead>
                <TableHead className="text-xs">MAC</TableHead>
                <TableHead className="text-xs"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredDevices.map((device) => (
                <TableRow key={device.ip}>
                  <TableCell className="text-xs font-mono">{device.ip}</TableCell>
                  <TableCell className="text-xs">
                    <span>{device.label ?? device.hostname ?? '—'}</span>
                    {device.label && device.hostname && (
                      <span className="text-muted-foreground ml-1">({device.hostname})</span>
                    )}
                    {device.deco_node && (
                      <Badge variant="outline" className="ml-1 text-xs">Deco</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{device.vendor ?? '—'}</TableCell>
                  <TableCell className="text-xs font-mono text-muted-foreground">
                    {device.mac ? device.mac.slice(0, 8) + '…' : '—'}
                  </TableCell>
                  <TableCell>
                    <LabelDialog
                      device={device}
                      onLabeled={() => queryClient.invalidateQueries({ queryKey: ['devices'] })}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="text-sm text-muted-foreground">{deviceData?.error ?? 'Could not load devices'}</div>
        )}
      </div>
    </div>
  )
}
