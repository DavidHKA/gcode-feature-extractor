import { useState, useCallback } from 'react'
import { extractFeatures } from './api'
import type { ExtractResponse } from './types'
import UploadArea from './components/UploadArea'
import KPICards from './components/KPICards'
import LayerChart from './components/LayerChart'
import LayerTable from './components/LayerTable'
import EventsView from './components/EventsView'
import DownloadSection from './components/DownloadSection'

type Tab = 'summary' | 'layers' | 'events' | 'downloads'

const TABS: { id: Tab; label: string }[] = [
  { id: 'summary',   label: 'Summary' },
  { id: 'layers',    label: 'Layer Features' },
  { id: 'events',    label: 'Events & Settings' },
  { id: 'downloads', label: 'Downloads' },
]

export default function App() {
  const [loading,    setLoading]    = useState(false)
  const [error,      setError]      = useState<string | null>(null)
  const [result,     setResult]     = useState<ExtractResponse | null>(null)
  const [activeTab,  setActiveTab]  = useState<Tab>('summary')
  const [pendingFile, setPendingFile] = useState<File | null>(null)

  const handleFile = useCallback((file: File) => {
    setPendingFile(file)
    setError(null)
  }, [])

  const handleExtract = useCallback(async () => {
    if (!pendingFile) return
    setLoading(true)
    setError(null)
    try {
      const res = await extractFeatures(pendingFile)
      setResult(res)
      setActiveTab('summary')
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } }; message?: string })
        ?.response?.data?.detail ?? (e as Error)?.message ?? 'Unknown error'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [pendingFile])

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      {/* Header */}
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center gap-3">
          <span className="text-2xl">🖨️</span>
          <div>
            <h1 className="text-xl font-bold text-white">G-Code Feature Extractor</h1>
            <p className="text-xs text-gray-500">PrusaSlicer · FDM · Hidden Feature Engineering</p>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8 space-y-8">

        {/* Upload section */}
        <div className="space-y-4">
          <UploadArea onFile={handleFile} loading={loading} />

          {pendingFile && (
            <div className="flex items-center justify-between bg-gray-900 rounded-lg px-4 py-3">
              <div className="flex items-center gap-2">
                <span className="text-gray-400 text-sm">Selected:</span>
                <span className="font-mono text-sm text-blue-300">{pendingFile.name}</span>
                <span className="text-xs text-gray-500">
                  ({(pendingFile.size / 1024 / 1024).toFixed(1)} MB)
                </span>
              </div>
              <button
                onClick={handleExtract}
                disabled={loading}
                className="px-5 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700
                           disabled:cursor-not-allowed rounded-lg text-sm font-semibold
                           transition-colors flex items-center gap-2"
              >
                {loading && (
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                  </svg>
                )}
                {loading ? 'Extracting…' : 'Extract Features'}
              </button>
            </div>
          )}

          {error && (
            <div className="bg-rose-950 border border-rose-800 text-rose-300 rounded-lg px-4 py-3 text-sm">
              <strong>Error:</strong> {error}
            </div>
          )}
        </div>

        {/* Results */}
        {result && (
          <div className="space-y-6">
            {/* File info bar */}
            <div className="flex flex-wrap gap-4 text-xs text-gray-400 bg-gray-900 rounded-lg px-4 py-3">
              <span>File: <span className="text-gray-200 font-mono">{result.filename}</span></span>
              <span>Lines: <span className="text-gray-200">{result.total_lines.toLocaleString()}</span></span>
              <span>Layers: <span className="text-gray-200">{result.layer_count}</span></span>
              <span>Session: <span className="text-gray-500 font-mono text-xs">{result.session_id.slice(0, 8)}…</span></span>
            </div>

            {/* Tabs */}
            <div className="border-b border-gray-800">
              <nav className="flex gap-6">
                {TABS.map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`pb-3 text-sm font-medium transition-colors ${
                      activeTab === tab.id ? 'tab-active' : 'tab-inactive'
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </nav>
            </div>

            {/* Tab content */}
            {activeTab === 'summary' && (
              <div className="space-y-6">
                <KPICards
                  gf={result.global_features}
                  layerCount={result.layer_count}
                  totalLines={result.total_lines}
                />

                {/* E per mm by type */}
                {Boolean(result.global_features.e_per_mm_by_type) && (
                  <div className="bg-gray-900 rounded-lg p-4">
                    <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
                      E/mm Ratio by Section Type
                    </h3>
                    <div className="overflow-auto">
                      <table className="text-xs w-full">
                        <thead className="text-gray-500">
                          <tr>
                            {['Type', 'Mean', 'Median', 'P95', 'Count'].map((h) => (
                              <th key={h} className="text-left px-3 py-1">{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(
                            result.global_features.e_per_mm_by_type as Record<string, Record<string, number>>
                          ).map(([type, stats]) => (
                            <tr key={type} className="border-t border-gray-800">
                              <td className="px-3 py-1 text-blue-300 font-mono">{type}</td>
                              <td className="px-3 py-1 font-mono text-gray-300">{stats.mean?.toFixed(5)}</td>
                              <td className="px-3 py-1 font-mono text-gray-300">{stats.median?.toFixed(5)}</td>
                              <td className="px-3 py-1 font-mono text-gray-300">{stats.p95?.toFixed(5)}</td>
                              <td className="px-3 py-1 font-mono text-gray-300">{stats.count}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {/* Raw JSON collapsible */}
                <details className="bg-gray-900 rounded-lg p-4">
                  <summary className="text-sm text-gray-400 cursor-pointer hover:text-gray-200">
                    Raw Global Features JSON
                  </summary>
                  <pre className="mt-3 text-xs text-gray-400 overflow-auto max-h-96 font-mono leading-relaxed">
                    {JSON.stringify(result.global_features, null, 2)}
                  </pre>
                </details>
              </div>
            )}

            {activeTab === 'layers' && (
              <div className="space-y-6">
                {result.layer_features_preview.length > 0 ? (
                  <>
                    <p className="text-xs text-gray-500">
                      Showing first {result.layer_features_preview.length} of {result.layer_count} layers.
                      Download CSV for full data.
                    </p>
                    <LayerChart
                      rows={result.layer_features_preview}
                      globalFeatures={result.global_features}
                    />
                    <LayerTable rows={result.layer_features_preview} />
                  </>
                ) : (
                  <p className="text-gray-500">No layer data available.</p>
                )}
              </div>
            )}

            {activeTab === 'events' && (
              <EventsView
                globalFeatures={result.global_features}
                declaredSettings={result.declared_settings}
              />
            )}

            {activeTab === 'downloads' && (
              <DownloadSection urls={result.download_urls} />
            )}
          </div>
        )}
      </main>
    </div>
  )
}
