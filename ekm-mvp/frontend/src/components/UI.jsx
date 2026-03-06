import { formatDistanceToNow } from 'date-fns'

// ─── Source Badge ─────────────────────────────────────────────────────────────
const SOURCE_CONFIG = {
  sharepoint: { label: 'SharePoint', color: 'bg-blue-100 text-blue-700', dot: 'bg-blue-500' },
  confluence: { label: 'Confluence', color: 'bg-purple-100 text-purple-700', dot: 'bg-purple-500' },
  jira:       { label: 'Jira',       color: 'bg-orange-100 text-orange-700', dot: 'bg-orange-500' },
  servicenow: { label: 'ServiceNow', color: 'bg-gray-100 text-gray-500', dot: 'bg-gray-400' },
}

export function SourceBadge({ type }) {
  const cfg = SOURCE_CONFIG[type] || { label: type, color: 'bg-gray-100 text-gray-600', dot: 'bg-gray-400' }
  return (
    <span className={`badge ${cfg.color}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
      {cfg.label}
    </span>
  )
}

// ─── Status Badge ─────────────────────────────────────────────────────────────
const STATUS_CONFIG = {
  success: 'bg-green-100 text-green-700',
  failed:  'bg-red-100 text-red-700',
  running: 'bg-yellow-100 text-yellow-700',
  never:   'bg-gray-100 text-gray-500',
}

export function StatusBadge({ status }) {
  return (
    <span className={`badge ${STATUS_CONFIG[status] || 'bg-gray-100 text-gray-500'}`}>
      {status === 'running' && <span className="w-1.5 h-1.5 rounded-full bg-yellow-500 animate-pulse" />}
      {status}
    </span>
  )
}

// ─── Document Card ────────────────────────────────────────────────────────────
export function DocCard({ doc, onClick }) {
  const isGitHub = doc.source_type === 'github'
  const m = doc.metadata || {}
  const contentType = m.content_type || ''
  const isCommit = contentType === 'commit'
  const isPR     = contentType === 'pull_request'

  return (
    <div
      className="card p-4 hover:shadow-md transition-shadow cursor-pointer"
      onClick={() => onClick && onClick(doc)}
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <h3 className="font-semibold text-gray-900 text-sm leading-snug line-clamp-2">
          {doc.title}
        </h3>
        <div className="flex items-center gap-1 shrink-0">
          {isGitHub && (
            <span className={`badge text-xs ${
              isCommit ? 'bg-orange-50 text-orange-700' :
              isPR     ? 'bg-purple-50 text-purple-700' :
                         'bg-blue-50 text-blue-700'
            }`}>
              {isCommit ? '⬡ commit' : isPR ? '↔ PR' : '📄 file'}
            </span>
          )}
          <SourceBadge type={doc.source_type} />
        </div>
      </div>

      {/* GitHub commit details */}
      {isGitHub && isCommit && (
        <div className="flex flex-wrap gap-2 mb-2">
          {m.short_sha && (
            <span className="text-xs font-mono bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">
              {m.short_sha}
            </span>
          )}
          {m.additions != null && (
            <span className="text-xs text-green-600">+{m.additions}</span>
          )}
          {m.deletions != null && (
            <span className="text-xs text-red-500">-{m.deletions}</span>
          )}
          {m.files_changed?.length > 0 && (
            <span className="text-xs text-gray-400">{m.files_changed.length} files</span>
          )}
        </div>
      )}

      {/* PR details */}
      {isGitHub && isPR && m.number && (
        <div className="mb-2">
          <span className="text-xs text-purple-600 font-medium">PR #{m.number}</span>
        </div>
      )}

      <p className="text-gray-500 text-xs leading-relaxed line-clamp-3 mb-3">
        {doc.content_preview || 'No preview available.'}
      </p>

      <div className="flex items-center gap-3 text-xs text-gray-400">
        <span>{doc.source}</span>
        {doc.author && <span>· {doc.author}</span>}
        {doc.ingested_at && (
          <span>· {formatDistanceToNow(new Date(doc.ingested_at), { addSuffix: true })}</span>
        )}
        {doc.score && (
          <span className="ml-auto text-teal-600 font-medium">
            score {doc.score.toFixed(2)}
          </span>
        )}
      </div>

      {/* Files changed pills for commits */}
      {isGitHub && isCommit && m.files_changed?.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {m.files_changed.slice(0, 4).map(f => (
            <span key={f} className="badge bg-gray-50 text-gray-500 font-mono text-xs border border-gray-100">
              {f.split('/').pop()}
            </span>
          ))}
          {m.files_changed.length > 4 && (
            <span className="text-xs text-gray-400">+{m.files_changed.length - 4} more</span>
          )}
        </div>
      )}

      {!isGitHub && doc.tags?.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {doc.tags.slice(0, 5).map(tag => (
            <span key={tag} className="badge bg-gray-100 text-gray-500">{tag}</span>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Empty State ──────────────────────────────────────────────────────────────
export function EmptyState({ icon, title, subtitle }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="text-5xl mb-4">{icon}</div>
      <h3 className="font-semibold text-gray-700 mb-1">{title}</h3>
      <p className="text-gray-400 text-sm max-w-xs">{subtitle}</p>
    </div>
  )
}

// ─── Spinner ──────────────────────────────────────────────────────────────────
export function Spinner({ size = 'md' }) {
  const sz = size === 'sm' ? 'w-4 h-4' : 'w-8 h-8'
  return (
    <div className={`${sz} border-2 border-teal-500 border-t-transparent rounded-full animate-spin`} />
  )
}

// ─── Stat Card ────────────────────────────────────────────────────────────────
export function StatCard({ label, value, sub, color = 'teal' }) {
  const colors = {
    teal:   'text-teal-600',
    blue:   'text-blue-600',
    purple: 'text-purple-600',
    orange: 'text-orange-600',
    gray:   'text-gray-400',
  }
  return (
    <div className="card p-5">
      <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-3xl font-bold ${colors[color] || colors.teal}`}>{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}
