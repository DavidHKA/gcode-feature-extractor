import createPlotlyComponent from 'react-plotly.js/factory'
import Plotly from 'plotly.js-dist-min'
import type { LayerRow } from '../types'

const Plot = createPlotlyComponent(Plotly)

interface Props {
  rows: LayerRow[]
  globalFeatures: Record<string, unknown>
}

const LAYOUT_BASE = {
  paper_bgcolor: '#030712',
  plot_bgcolor:  '#111827',
  font:          { color: '#d1d5db', size: 11 },
  margin:        { t: 36, r: 16, b: 48, l: 56 },
  xaxis:         { gridcolor: '#1f2937', zerolinecolor: '#374151' },
  yaxis:         { gridcolor: '#1f2937', zerolinecolor: '#374151' },
}

const CONFIG = { displayModeBar: false, responsive: true }

export default function LayerChart({ rows, globalFeatures }: Props) {
  const layers = rows.map((r) => r.layer_id)
  const z      = rows.map((r) => r.z)

  // --- Chart 1: layer time ---
  const chartTime = (
    <Plot
      data={[{
        x: layers, y: rows.map((r) => r.layer_time_est_s),
        type: 'bar', name: 'Layer time',
        marker: { color: '#3b82f6' },
      }]}
      layout={{ ...LAYOUT_BASE, title: { text: 'Estimated Layer Time (s)', font: { color: '#9ca3af' } },
        xaxis: { ...LAYOUT_BASE.xaxis, title: { text: 'Layer ID' } },
        yaxis: { ...LAYOUT_BASE.yaxis, title: { text: 's' } } }}
      config={CONFIG}
      style={{ width: '100%', height: 280 }}
    />
  )

  // --- Chart 2: extrude vs travel stacked ---
  const chartPath = (
    <Plot
      data={[
        { x: layers, y: rows.map((r) => r.extrude_path_mm), type: 'bar', name: 'Extrude',
          marker: { color: '#22c55e' } },
        { x: layers, y: rows.map((r) => r.travel_mm), type: 'bar', name: 'Travel',
          marker: { color: '#f59e0b' } },
      ]}
      layout={{ ...LAYOUT_BASE, barmode: 'stack',
        title: { text: 'Extrude vs Travel Path (mm)', font: { color: '#9ca3af' } },
        xaxis: { ...LAYOUT_BASE.xaxis, title: { text: 'Layer ID' } },
        yaxis: { ...LAYOUT_BASE.yaxis, title: { text: 'mm' } } }}
      config={CONFIG}
      style={{ width: '100%', height: 280 }}
    />
  )

  // --- Chart 3: retracts per layer ---
  const chartRetract = (
    <Plot
      data={[{
        x: layers, y: rows.map((r) => r.retract_count),
        type: 'bar', name: 'Retracts',
        marker: { color: '#f43f5e' },
      }]}
      layout={{ ...LAYOUT_BASE,
        title: { text: 'Retractions per Layer', font: { color: '#9ca3af' } },
        xaxis: { ...LAYOUT_BASE.xaxis, title: { text: 'Layer ID' } },
        yaxis: { ...LAYOUT_BASE.yaxis, title: { text: 'count' } } }}
      config={CONFIG}
      style={{ width: '100%', height: 280 }}
    />
  )

  // --- Chart 4: mean extrude feedrate per layer ---
  const chartFeedrate = (
    <Plot
      data={[{
        x: layers, y: rows.map((r) => r.mean_F_extrude),
        type: 'scatter', mode: 'lines', name: 'Mean F extrude',
        line: { color: '#a855f7', width: 1.5 },
      }]}
      layout={{ ...LAYOUT_BASE,
        title: { text: 'Mean Extrusion Feedrate per Layer (mm/min)', font: { color: '#9ca3af' } },
        xaxis: { ...LAYOUT_BASE.xaxis, title: { text: 'Layer ID' } },
        yaxis: { ...LAYOUT_BASE.yaxis, title: { text: 'mm/min' } } }}
      config={CONFIG}
      style={{ width: '100%', height: 280 }}
    />
  )

  // --- Chart 5: Infill anisotropy ---
  const chartAni = (
    <Plot
      data={[{
        x: layers, y: rows.map((r) => r.anisotropy_score_infill),
        type: 'scatter', mode: 'lines+markers', name: 'Anisotropy',
        line: { color: '#06b6d4', width: 1.5 },
        marker: { size: 3 },
      }]}
      layout={{ ...LAYOUT_BASE,
        title: { text: 'Infill Anisotropy Score per Layer', font: { color: '#9ca3af' } },
        xaxis: { ...LAYOUT_BASE.xaxis, title: { text: 'Layer ID' } },
        yaxis: { ...LAYOUT_BASE.yaxis, title: { text: 'score (0–1)' }, range: [0, 1] } }}
      config={CONFIG}
      style={{ width: '100%', height: 280 }}
    />
  )

  // --- Chart 6: Infill angle histogram (global) ---
  const angleBins  = (globalFeatures.infill_angle_bins ?? {}) as Record<string, number>
  const angleKeys  = Object.keys(angleBins)
  const angleVals  = angleKeys.map((k) => angleBins[k])
  const chartAngle = angleKeys.length > 0 ? (
    <Plot
      data={[{
        x: angleKeys, y: angleVals,
        type: 'bar', name: 'Angle count',
        marker: { color: '#f97316' },
      }]}
      layout={{ ...LAYOUT_BASE,
        title: { text: 'Infill Angle Distribution (0–180°, global)', font: { color: '#9ca3af' } },
        xaxis: { ...LAYOUT_BASE.xaxis, title: { text: 'Angle bin' }, tickangle: -45 },
        yaxis: { ...LAYOUT_BASE.yaxis, title: { text: 'segment count' } } }}
      config={CONFIG}
      style={{ width: '100%', height: 280 }}
    />
  ) : <p className="text-gray-500 text-sm p-4">No infill segments detected.</p>

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {chartTime}
      {chartPath}
      {chartRetract}
      {chartFeedrate}
      {chartAni}
      {chartAngle}
    </div>
  )
}
