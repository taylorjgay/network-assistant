import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

interface StatusBadgeProps {
  online: boolean
  label?: string
  /** Status comes from an old snapshot: show neither green nor red until it is confirmed. */
  unknown?: boolean
}

export function StatusBadge({ online, label, unknown }: StatusBadgeProps) {
  if (unknown) {
    return (
      <Badge className="bg-muted text-muted-foreground hover:bg-muted">
        ● Checking
      </Badge>
    )
  }
  return (
    <Badge className={cn(online ? 'bg-green-600 hover:bg-green-600' : 'bg-red-600 hover:bg-red-600', 'text-white')}>
      ● {label ?? (online ? 'Online' : 'Offline')}
    </Badge>
  )
}
