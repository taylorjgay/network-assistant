import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Coarse age for "Last updated 3w ago": the largest whole unit. */
export function formatAge(seconds: number): string {
  const units: [number, string][] = [[604800, 'w'], [86400, 'd'], [3600, 'h'], [60, 'm']]
  for (const [size, unit] of units) {
    if (seconds >= size) return `${Math.floor(seconds / size)}${unit}`
  }
  return `${Math.max(0, Math.floor(seconds))}s`
}

export function formatUptime(seconds?: number | null): string {
  if (!seconds) return '—'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  return d > 0 ? `${d}d ${h}h` : `${h}h`
}
