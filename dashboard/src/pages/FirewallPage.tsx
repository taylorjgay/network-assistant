import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'

function AddPortForwardDialog({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({
    name: '', external_port: '', internal_ip: '', internal_port: '', protocol: 'tcp',
  })

  const handleAdd = async () => {
    if (!form.name || !form.external_port || !form.internal_ip || !form.internal_port) {
      toast.error('All fields required')
      return
    }
    try {
      await api.addPortForward({
        name: form.name,
        external_port: parseInt(form.external_port),
        internal_ip: form.internal_ip,
        internal_port: parseInt(form.internal_port),
        protocol: form.protocol,
      })
      toast.success(`Port forward "${form.name}" added`)
      onAdded()
      setOpen(false)
      setForm({ name: '', external_port: '', internal_ip: '', internal_port: '', protocol: 'tcp' })
    } catch {
      toast.error('Failed to add port forward')
    }
  }

  const fields: { id: keyof typeof form; label: string; placeholder: string }[] = [
    { id: 'name', label: 'Name', placeholder: 'e.g. Minecraft' },
    { id: 'external_port', label: 'External Port', placeholder: '25565' },
    { id: 'internal_ip', label: 'Internal IP', placeholder: '192.168.0.50' },
    { id: 'internal_port', label: 'Internal Port', placeholder: '25565' },
  ]

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" className="h-7 text-xs">+ Add Rule</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add Port Forward</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-2">
          {fields.map(({ id, label, placeholder }) => (
            <div key={id} className="space-y-1">
              <Label>{label}</Label>
              <Input
                value={form[id]}
                onChange={e => setForm(f => ({ ...f, [id]: e.target.value }))}
                placeholder={placeholder}
              />
            </div>
          ))}
          <div className="space-y-1">
            <Label>Protocol</Label>
            <select
              className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm"
              value={form.protocol}
              onChange={e => setForm(f => ({ ...f, protocol: e.target.value }))}
            >
              <option value="tcp">TCP</option>
              <option value="udp">UDP</option>
              <option value="both">Both</option>
            </select>
          </div>
          <Button onClick={handleAdd} className="w-full">Add Rule</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default function FirewallPage() {
  const queryClient = useQueryClient()
  const [removing, setRemoving] = useState<string | null>(null)

  const { data: ports, isLoading: portsLoading, refetch: refetchPorts } = useQuery({
    queryKey: ['ports'],
    queryFn: api.getPortForwards,
  })

  const { data: upnp, isLoading: upnpLoading, refetch: refetchUpnp } = useQuery({
    queryKey: ['upnp'],
    queryFn: api.getUpnp,
  })

  const handleRemove = async (ruleId: string, name: string) => {
    if (!confirm(`Remove port forward "${name}"?`)) return
    setRemoving(ruleId)
    try {
      await api.removePortForward(ruleId)
      toast.success(`Removed "${name}"`)
      queryClient.invalidateQueries({ queryKey: ['ports'] })
    } catch {
      toast.error('Failed to remove rule')
    } finally {
      setRemoving(null)
    }
  }

  return (
    <div className="space-y-6">
      {/* Port forwards */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium">Port Forwards</h3>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => refetchPorts()}>↻</Button>
            <AddPortForwardDialog onAdded={() => queryClient.invalidateQueries({ queryKey: ['ports'] })} />
          </div>
        </div>
        {portsLoading ? (
          <div className="text-sm text-muted-foreground">Loading...</div>
        ) : ports?.success ? (
          ports.rules.length === 0 ? (
            <div className="text-sm text-muted-foreground">No port forward rules configured.</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs">Name</TableHead>
                  <TableHead className="text-xs">Ext Port</TableHead>
                  <TableHead className="text-xs">Internal</TableHead>
                  <TableHead className="text-xs">Protocol</TableHead>
                  <TableHead className="text-xs"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {ports.rules.map((rule) => (
                  <TableRow key={rule.id ?? rule.name}>
                    <TableCell className="text-xs">{rule.name}</TableCell>
                    <TableCell className="text-xs font-mono">{rule.external_port}</TableCell>
                    <TableCell className="text-xs font-mono">{rule.internal_ip}:{rule.internal_port}</TableCell>
                    <TableCell className="text-xs uppercase">{rule.protocol}</TableCell>
                    <TableCell>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 px-2 text-xs text-red-500 hover:text-red-600"
                        disabled={!rule.id || removing === rule.id}
                        onClick={() => rule.id && handleRemove(rule.id, rule.name)}
                      >
                        Remove
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )
        ) : (
          <div className="text-sm text-muted-foreground">{ports?.error ?? 'Could not load rules'}</div>
        )}
      </div>

      {/* UPnP port maps */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium">UPnP Port Mappings</h3>
          <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => refetchUpnp()}>↻</Button>
        </div>
        {upnpLoading ? (
          <div className="text-sm text-muted-foreground">Loading...</div>
        ) : upnp?.portmaps?.mappings?.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">Description</TableHead>
                <TableHead className="text-xs">Ext Port</TableHead>
                <TableHead className="text-xs">Internal</TableHead>
                <TableHead className="text-xs">Protocol</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {upnp.portmaps.mappings.map((m, i) => (
                <TableRow key={i}>
                  <TableCell className="text-xs">{m.description || '—'}</TableCell>
                  <TableCell className="text-xs font-mono">{m.external_port}</TableCell>
                  <TableCell className="text-xs font-mono">{m.internal_host}:{m.internal_port}</TableCell>
                  <TableCell className="text-xs uppercase">{m.protocol}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="text-sm text-muted-foreground">
            {upnp?.portmaps?.error ?? (upnp?.portmaps?.available === false ? 'No UPnP gateway found' : 'No active UPnP mappings')}
          </div>
        )}
      </div>
    </div>
  )
}
