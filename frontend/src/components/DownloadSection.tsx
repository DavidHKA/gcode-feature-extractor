import type { DownloadUrls } from '../types'

interface Props { urls: DownloadUrls }

const FILES = [
  { key: 'features_global_json' as const, label: 'features_global.json', desc: 'All global & derived features', icon: '{}', color: 'blue' },
  { key: 'features_layers_csv'  as const, label: 'features_layers.csv',  desc: 'Per-layer feature table',       icon: '☰',  color: 'green' },
  { key: 'feature_manifest_md'  as const, label: 'feature_manifest.md',  desc: 'Feature definitions + units',   icon: '📄', color: 'purple' },
  { key: 'segments_csv'         as const, label: 'segments.csv',         desc: 'Raw segment data (large)',       icon: '↗',  color: 'amber' },
]

const COLORS: Record<string, string> = {
  blue:   'bg-blue-900 hover:bg-blue-800 border-blue-700',
  green:  'bg-green-900 hover:bg-green-800 border-green-700',
  purple: 'bg-purple-900 hover:bg-purple-800 border-purple-700',
  amber:  'bg-amber-900 hover:bg-amber-800 border-amber-700',
}

export default function DownloadSection({ urls }: Props) {
  return (
    <div>
      <h2 className="text-lg font-semibold text-gray-300 mb-4">Download Artefacts</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {FILES.map(({ key, label, desc, icon, color }) => (
          <a
            key={key}
            href={urls[key]}
            download={label}
            className={`flex items-start gap-4 border rounded-xl p-4 transition-colors ${COLORS[color]}`}
          >
            <span className="text-2xl mt-0.5">{icon}</span>
            <div>
              <p className="font-mono text-sm font-semibold text-gray-200">{label}</p>
              <p className="text-xs text-gray-400 mt-0.5">{desc}</p>
            </div>
          </a>
        ))}
      </div>
    </div>
  )
}
