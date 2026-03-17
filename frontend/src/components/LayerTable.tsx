import type { LayerRow } from '../types'

interface Props { rows: LayerRow[] }

const COLS: { key: keyof LayerRow; label: string; dec?: number }[] = [
  { key: 'layer_id',              label: 'Layer',       dec: 0 },
  { key: 'z',                     label: 'Z (mm)',      dec: 3 },
  { key: 'height',                label: 'H (mm)',      dec: 3 },
  { key: 'layer_time_est_s',      label: 'Time (s)',    dec: 1 },
  { key: 'extrude_path_mm',       label: 'Extrude (mm)',dec: 1 },
  { key: 'travel_mm',             label: 'Travel (mm)', dec: 1 },
  { key: 'retract_count',         label: 'Retracts',    dec: 0 },
  { key: 'wipe_blocks_count',     label: 'Wipes',       dec: 0 },
  { key: 'mean_F_extrude',        label: 'F ext',       dec: 0 },
  { key: 'mean_F_travel',         label: 'F trav',      dec: 0 },
  { key: 'anisotropy_score_infill',label: 'Anisotropy', dec: 3 },
  { key: 'startpoint_dispersion', label: 'Seam disp.',  dec: 2 },
]

function fmt(v: number, dec?: number): string {
  if (v == null) return '–'
  return v.toFixed(dec ?? 2)
}

export default function LayerTable({ rows }: Props) {
  return (
    <div className="overflow-auto rounded-lg border border-gray-800">
      <table className="w-full text-sm text-left">
        <thead className="bg-gray-900 text-gray-400 uppercase text-xs">
          <tr>
            {COLS.map((c) => (
              <th key={c.key} className="px-3 py-2 whitespace-nowrap">{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.layer_id}
              className={i % 2 === 0 ? 'bg-gray-950' : 'bg-gray-900'}>
              {COLS.map((c) => (
                <td key={c.key} className="px-3 py-1.5 text-gray-300 font-mono whitespace-nowrap">
                  {fmt(row[c.key] as number, c.dec)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
