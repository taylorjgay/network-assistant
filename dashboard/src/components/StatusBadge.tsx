import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

interface StatusBadgeProps {
  online: boolean
  label?: string
}

export function StatusBadge({ online, label }: StatusBadgeProps) {
  return (
    <Badge className={cn(online ? 'bg-green-600 hover:bg-green-600' : 'bg-red-600 hover:bg-red-600', 'text-white')}>
      ● {label ?? (online ? 'Online' : 'Offline')}
    </Badge>
  )
}
