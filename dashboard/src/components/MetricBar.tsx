interface MetricBarProps {
  label: string
  value: number | null
}

function getBarColor(value: number): string {
  if (value >= 85) {
    return 'bg-rose-500'
  }

  if (value >= 65) {
    return 'bg-amber-400'
  }

  return 'bg-indigo-400'
}

export function MetricBar({ label, value }: MetricBarProps) {
  const displayValue = value == null || Number.isNaN(value) ? null : Math.min(100, Math.max(0, value))

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-400">{label}</span>
        <span className="font-medium text-slate-200">
          {displayValue == null ? '—' : `${displayValue.toFixed(1)}%`}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-800">
        <div
          className={`h-full rounded-full transition-all duration-500 ${displayValue == null ? 'w-0 bg-slate-600' : getBarColor(displayValue)}`}
          style={{ width: displayValue == null ? '0%' : `${displayValue}%` }}
        />
      </div>
    </div>
  )
}
