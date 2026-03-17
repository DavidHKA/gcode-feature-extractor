interface KPI {
  label: string
  value: string | number
  sub?: string
  color?: string
}

function Card({ label, value, sub, color = 'blue' }: KPI) {
  const colors: Record<string, string> = {
    blue:   'border-blue-600 text-blue-400',
    green:  'border-green-600 text-green-400',
    purple: 'border-purple-600 text-purple-400',
    amber:  'border-amber-600 text-amber-400',
    rose:   'border-rose-600 text-rose-400',
    teal:   'border-teal-600 text-teal-400',
  }
  return (
    <div className={`bg-gray-900 border-l-4 ${colors[color] ?? colors.blue} rounded-lg p-4`}>
      <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-2xl font-bold ${colors[color]?.split(' ')[1]}`}>{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-1">{sub}</p>}
    </div>
  )
}

interface Props {
  gf: Record<string, unknown>
  layerCount: number
  totalLines: number
}

function fmt(n: unknown, dec = 1): string {
  if (n == null) return '–'
  const v = Number(n)
  if (isNaN(v)) return String(n)
  return v.toLocaleString('de-DE', { maximumFractionDigits: dec })
}

function fmtTime(s: unknown): string {
  const sec = Number(s)
  if (isNaN(sec) || sec === 0) return '–'
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

export default function KPICards({ gf, layerCount, totalLines }: Props) {
  const kpis: KPI[] = [
    { label: 'Layers',          value: fmt(layerCount, 0),                       color: 'blue' },
    { label: 'G-code Lines',    value: fmt(totalLines, 0),                        color: 'teal' },
    { label: 'Est. Print Time', value: fmtTime(gf.estimated_print_time_s),        color: 'green',
      sub: `${fmt(gf.time_share_travel, 0)}% travel / ${fmt((Number(gf.time_share_extrude)*100).toFixed(0), 0)}% extrude` },
    { label: 'Total Extrusion', value: `${fmt(gf.total_extrude_path_mm, 0)} mm`,  color: 'purple',
      sub: `Travel ratio: ${fmt(gf.travel_to_extrude_ratio, 2)}` },
    { label: 'Retractions',     value: fmt(gf.retraction_count, 0),               color: 'rose',
      sub: `${fmt(gf.retracts_per_meter, 1)}/m · len ø ${fmt(gf.retraction_length_mean, 3)} mm` },
    { label: 'Wipe Blocks',     value: fmt(gf.num_wipe_blocks, 0),                color: 'amber',
      sub: `Path: ${fmt(gf.wipe_total_path_mm, 1)} mm` },
    { label: 'Segments',        value: fmt(gf.num_segments_total, 0),             color: 'teal',
      sub: `${fmt(gf.num_extrude_segments, 0)} extrude · ${fmt(gf.num_travel_segments, 0)} travel` },
    { label: 'Infill Anisotropy', value: fmt(Number(gf.infill_anisotropy_score ?? 0) * 100, 1) + ' %',
      color: 'purple', sub: '100% = one direction' },
    { label: 'Seam Dispersion', value: `${fmt(gf.seam_dispersion_mean_mm, 2)} mm`, color: 'blue',
      sub: `σ = ${fmt(gf.seam_dispersion_std_mm, 2)} mm` },
    { label: 'Nozzle Temp',     value: `${fmt(gf.first_layer_temp, 0)} °C`,       color: 'rose',
      sub: `Last: ${fmt(gf.last_nozzle_setpoint, 0)} °C` },
    { label: 'G92 E Resets',    value: fmt(gf.num_g92_resets, 0),                 color: 'amber' },
    { label: 'Speed CV',        value: fmt(Number(gf.feedrate_cv_extrude ?? 0) * 100, 1) + ' %',
      color: 'green', sub: 'Extrusion feedrate variation' },
  ]

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
      {kpis.map((k) => <Card key={k.label} {...k} />)}
    </div>
  )
}
