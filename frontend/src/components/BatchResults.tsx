import type { BatchRow } from '../App'

interface BatchResultsProps {
  fileCount:      number
  csvUrl:         string
  rows:           BatchRow[]
  onDownload:     () => void
  onOpenDetail:   (row: BatchRow) => void
}

function fmt(v: number | null | undefined, decimals = 3): string {
  if (v == null) return '—'
  return v.toFixed(decimals)
}

export default function BatchResults({ fileCount, rows, onDownload, onOpenDetail }: BatchResultsProps) {
  const successCount = rows.filter(r => !r.error).length
  const errorCount   = rows.filter(r =>  r.error).length

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-green-950 border border-green-800 rounded-xl p-5 flex items-center justify-between">
        <div>
          <h3 className="text-green-300 font-semibold text-base">Extraktion abgeschlossen</h3>
          <p className="text-green-600 text-xs mt-1">
            {successCount} von {fileCount} Datei{fileCount !== 1 ? 'en' : ''} erfolgreich
            {errorCount > 0 && <span className="text-red-400 ml-2">· {errorCount} Fehler</span>}
          </p>
        </div>
        <button
          onClick={onDownload}
          className="px-4 py-2 bg-green-700 hover:bg-green-600 rounded-lg text-sm font-semibold
                     text-white transition-colors flex items-center gap-2 shrink-0"
        >
          ⬇ training_data.csv
        </button>
      </div>

      {/* Preview table */}
      <div className="bg-gray-900 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-800">
          <h4 className="text-sm font-semibold text-gray-300">Vorschau</h4>
          <p className="text-xs text-gray-500 mt-0.5">
            Füge eine Spalte <code className="text-gray-400">tensile_strength_mpa</code> hinzu
            und trage die gemessenen Zugfestigkeiten ein — fertig für das NN-Training.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-gray-500 bg-gray-800/50">
              <tr>
                <th className="text-left px-4 py-2 font-medium">Dateiname</th>
                <th className="text-right px-4 py-2 font-medium">Layer</th>
                <th className="text-right px-4 py-2 font-medium">Düsentemp (°C)</th>
                <th className="text-right px-4 py-2 font-medium">Thermal Bonding</th>
                <th className="text-right px-4 py-2 font-medium">Features</th>
                <th className="text-center px-4 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t border-gray-800 hover:bg-gray-800/30 transition-colors">
                  <td className="px-4 py-2 max-w-xs">
                    {r.fullResult ? (
                      <button
                        onClick={() => onOpenDetail(r)}
                        className="font-mono text-blue-400 hover:text-blue-200 hover:underline
                                   truncate block max-w-full text-left transition-colors"
                        title={`${r.filename} – Detailanalyse öffnen`}
                      >
                        {r.filename}
                      </button>
                    ) : (
                      <span className="font-mono text-gray-500 truncate block" title={r.filename}>
                        {r.filename}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right text-gray-300 font-mono">
                    {r.layerCount ?? '—'}
                  </td>
                  <td className="px-4 py-2 text-right text-gray-300 font-mono">
                    {fmt(r.nozzleTemp, 0)}
                  </td>
                  <td className="px-4 py-2 text-right text-gray-300 font-mono">
                    {fmt(r.thermalBonding)}
                  </td>
                  <td className="px-4 py-2 text-right text-green-400 font-mono font-semibold">
                    {r.nFeatures > 0 ? r.nFeatures : '—'}
                  </td>
                  <td className="px-4 py-2 text-center">
                    {r.error
                      ? <span className="text-red-400 font-bold" title={r.error}>✗ Fehler</span>
                      : <span className="text-green-400 font-bold">✓</span>
                    }
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
