import { useState, useEffect } from 'react'
import { getDashboard, triggerSync } from '../api'
import { SourceBadge, StatusBadge, StatCard, Spinner } from '../components/UI'
import { RefreshCw, Database, Clock, AlertCircle, CheckCircle } from 'lucide-react'
import { formatDistanceToNow, format } from 'date-fns'

const SOURCE_COLORS = { sharepoint: 'blue', confluence: 'purple', jira: 'orange' }

export default function Dashboard() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(null) // source_type or 'all'

  const load = async () => {
    try {
      const res = await getDashboard()
      setData(res.data)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleSync = async (sourceType) => {
    setSyncing(sourceType || 'all')
    try {
      await triggerSync(sourceType)
      await load()
    } finally {
      setSyncing(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Spinner />
      </div>
    )
  }

  const sources = data?.sources || []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-gray-500 text-sm mt-0.5">Knowledge base overview & sync status</p>
        </div>
        <button
          className="btn-primary flex items-center gap-2"
          onClick={() => handleSync(null)}
          disabled={syncing === 'all'}
        >
          <RefreshCw size={16} className={syncing === 'all' ? 'animate-spin' : ''} />
          {syncing === 'all' ? 'Syncing…' : 'Sync All'}
        </button>
      </div>

      {/* Top stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="Total Documents"
          value={data?.total_documents?.toLocaleString() ?? '—'}
          sub="across all sources"
          color="teal"
        />
        {sources.map(src => (
          <StatCard
            key={src.source_type}
            label={src.source_type.charAt(0).toUpperCase() + src.source_type.slice(1)}
            value={src.doc_count.toLocaleString()}
            sub={src.last_sync
              ? `synced ${formatDistanceToNow(new Date(src.last_sync), { addSuffix: true })}`
              : 'never synced'}
            color={SOURCE_COLORS[src.source_type] || 'gray'}
          />
        ))}
      </div>

      {/* Source cards */}
      <div>
        <h2 className="text-lg font-semibold text-gray-800 mb-3">Data Sources</h2>
        <div className="grid md:grid-cols-3 gap-4">
          {sources.map(src => (
            <div key={src.source_type} className="card p-5 space-y-4">
              <div className="flex items-center justify-between">
                <SourceBadge type={src.source_type} />
                <StatusBadge status={src.sync_status} />
              </div>

              <div className="space-y-1">
                <p className="text-2xl font-bold text-gray-900">
                  {src.doc_count.toLocaleString()}
                </p>
                <p className="text-xs text-gray-500">documents indexed</p>
              </div>

              {src.last_sync && (
                <div className="flex items-center gap-1 text-xs text-gray-400">
                  <Clock size={12} />
                  Last sync: {format(new Date(src.last_sync), 'MMM d, HH:mm')}
                </div>
              )}

              {src.error_message && (
                <div className="flex items-start gap-2 text-xs text-red-600 bg-red-50 rounded-lg p-2">
                  <AlertCircle size={12} className="mt-0.5 shrink-0" />
                  <span className="line-clamp-2">{src.error_message}</span>
                </div>
              )}

              <button
                className="btn-secondary w-full flex items-center justify-center gap-2 text-sm"
                onClick={() => handleSync(src.source_type)}
                disabled={!!syncing}
              >
                <RefreshCw size={14} className={syncing === src.source_type ? 'animate-spin' : ''} />
                {syncing === src.source_type ? 'Syncing…' : 'Sync Now'}
              </button>
            </div>
          ))}

          {/* ServiceNow — future scope */}
          <div className="card p-5 space-y-4 opacity-50">
            <div className="flex items-center justify-between">
              <span className="badge bg-gray-100 text-gray-500">
                <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
                ServiceNow
              </span>
              <span className="badge bg-gray-100 text-gray-400">future scope</span>
            </div>
            <div>
              <p className="text-2xl font-bold text-gray-300">—</p>
              <p className="text-xs text-gray-400">not yet configured</p>
            </div>
            <button className="btn-secondary w-full text-sm" disabled>
              Coming Soon
            </button>
          </div>
        </div>
      </div>

      {/* Recent sync activity */}
      <div>
        <h2 className="text-lg font-semibold text-gray-800 mb-3">Recent Sync Activity</h2>
        <div className="card overflow-hidden">
          {data?.recent_syncs?.length > 0 ? (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  {['Source', 'Status', 'Added', 'Updated', 'Time'].map(h => (
                    <th key={h} className="text-left px-4 py-3 text-xs text-gray-500 font-medium uppercase tracking-wide">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.recent_syncs.map((log, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-3"><SourceBadge type={log.source_type} /></td>
                    <td className="px-4 py-3"><StatusBadge status={log.status} /></td>
                    <td className="px-4 py-3 text-green-600 font-medium">+{log.docs_added ?? 0}</td>
                    <td className="px-4 py-3 text-blue-600 font-medium">~{log.docs_updated ?? 0}</td>
                    <td className="px-4 py-3 text-gray-400 text-xs">
                      {log.started_at ? formatDistanceToNow(new Date(log.started_at), { addSuffix: true }) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="py-10 text-center text-gray-400 text-sm">
              No sync activity yet. Click "Sync All" to start.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
