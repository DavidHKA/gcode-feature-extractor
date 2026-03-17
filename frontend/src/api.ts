import axios from 'axios'
import type { ExtractResponse } from './types'

const BASE = '/api'

export async function extractFeatures(file: File): Promise<ExtractResponse> {
  const form = new FormData()
  form.append('file', file)
  const res = await axios.post<ExtractResponse>(`${BASE}/extract-features`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data
}

export function downloadUrl(url: string, filename: string) {
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
}
