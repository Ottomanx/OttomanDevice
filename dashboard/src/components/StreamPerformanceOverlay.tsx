import type { StreamPerformanceSnapshot } from '../utils/remoteDesktopStreamMetrics'
import { getStreamHealthIndicatorClass } from '../utils/remoteDesktopStreamMetrics'

interface StreamPerformanceOverlayProps {
  performance: StreamPerformanceSnapshot
  showDebugTimings?: boolean
}

export function StreamPerformanceOverlay({
  performance,
  showDebugTimings = false,
}: StreamPerformanceOverlayProps) {
  const { frameTiming } = performance

  return (
    <div className="pointer-events-none absolute bottom-3 left-3 z-20 max-w-[240px] rounded-lg border border-slate-800/80 bg-slate-950/85 px-3 py-2 text-[11px] text-slate-300 shadow-lg backdrop-blur">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="font-semibold uppercase tracking-wide text-slate-400">Live Stats</span>
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ring-1 ring-inset ${getStreamHealthIndicatorClass(performance.health)}`}
        >
          {performance.health}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-x-3 gap-y-1">
        <span className="text-slate-500">FPS</span>
        <span className="text-right font-mono text-slate-200">{performance.fps.toFixed(1)}</span>
        <span className="text-slate-500">Latency</span>
        <span className="text-right font-mono text-slate-200">{performance.averageLatencyMs} ms</span>
        <span className="text-slate-500">Resolution</span>
        <span className="text-right font-mono text-slate-200">{performance.resolution}</span>
        <span className="text-slate-500">Bitrate</span>
        <span className="text-right font-mono text-slate-200">{performance.bitrateKbps} KB/s</span>
        <span className="text-slate-500">Drops</span>
        <span className="text-right font-mono text-slate-200">{performance.droppedFrames}</span>
      </div>

      {showDebugTimings && (
        <div className="mt-2 border-t border-slate-800 pt-2 text-[10px] text-slate-500">
          <p>Capture/encode: {frameTiming.captureEncodeMs ?? '—'} ms</p>
          <p>Network: {frameTiming.networkMs ?? '—'} ms</p>
          <p>Decode/render: {frameTiming.decodeRenderMs ?? '—'} ms</p>
          <p>
            Adaptive: {performance.adaptiveQualityPercent}%
            {performance.adaptiveFpsCap ? ` @ ${performance.adaptiveFpsCap} FPS cap` : ''}
          </p>
        </div>
      )}
    </div>
  )
}
