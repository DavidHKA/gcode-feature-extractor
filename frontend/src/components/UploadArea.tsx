import React, { useCallback, useRef, useState } from 'react'

interface Props {
  onFile: (f: File) => void
  loading: boolean
}

export default function UploadArea({ onFile, loading }: Props) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragging(false)
      const file = e.dataTransfer.files[0]
      if (file) onFile(file)
    },
    [onFile]
  )

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) onFile(file)
  }

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => !loading && inputRef.current?.click()}
      className={`
        flex flex-col items-center justify-center gap-3
        border-2 border-dashed rounded-xl p-12 cursor-pointer
        transition-colors duration-200
        ${dragging ? 'border-blue-400 bg-blue-950' : 'border-gray-600 bg-gray-900 hover:border-gray-400'}
        ${loading ? 'opacity-50 cursor-not-allowed' : ''}
      `}
    >
      <svg className="w-12 h-12 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
          d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
      </svg>
      <p className="text-lg font-medium text-gray-300">
        {dragging ? 'Drop your .gcode file here' : 'Drag & drop .gcode file'}
      </p>
      <p className="text-sm text-gray-500">or click to browse</p>
      <input
        ref={inputRef}
        type="file"
        accept=".gcode"
        className="hidden"
        onChange={handleChange}
      />
    </div>
  )
}
