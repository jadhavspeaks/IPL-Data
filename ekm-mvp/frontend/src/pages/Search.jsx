import React, { useState } from 'react'
import axios from 'axios'
import { SourceBadge, EmptyState, Spinner } from '../components/UI'
import { Search, X, ExternalLink, ChevronDown, ChevronUp, Link, User, Star, GitCommit, FileCode, GitPullRequest, Loader } from 'lucide-react'

const SOURCES = ['sharepoint', 'confluence', 'jira', 'github']

const PRIORITY_COLORS = {
  highest: 'bg-red-100 text-red-700',
  high:    'bg-orange-100 text-orange-700',
  medium:  'bg-yellow-100 text-yellow-700',
  low:     'bg-blue-100 text-blue-700',
  lowest:  'bg-gray-100 text-gray-500',
}

const ROLE_ICONS = {
  'Confluence Author': '📝',
  'Jira Reporter':     '🎫',
  'Jira Assignee':     '👤',
  'Issue Resolver':    '✅',
  'SharePoint Author': '📄',
}

// ── SME Card ─────────────────────────────────────────────────────────────────
function SMEPanel({ smes }) {
  if (!smes?.length) return null
  const maxScore = smes[0]?.score || 1

  return (
    <div className="card p-4 border-2 border-indigo-200 bg-gradient-to-br from-indigo-50 to-white">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-7 h-7 rounded-lg bg-indigo-500 flex items-center justify-center">
          <User size={14} className="text-white" />
        </div>
        <span className="font-semibold text-indigo-800 text-sm">Best People To Ask</span>
        <span className="ml-auto text-xs text-gray-400">ranked by topic expertise</span>
      </div>

      <div className="space-y-3">
        {smes.map((sme, i) => {
          const barWidth = Math.round((sme.score / maxScore) * 100)
          const b = sme.contribution_breakdown || {}

          return (
            <div key={sme.name} className="flex items-start gap-3">
              {/* Rank badge */}
              <div className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold
                ${i === 0 ? 'bg-yellow-400 text-yellow-900' :
                  i === 1 ? 'bg-gray-300 text-gray-700' :
                  i === 2 ? 'bg-orange-300 text-orange-800' :
                  'bg-gray-100 text-gray-500'}`}>
                {i === 0 ? <Star size={12}/> : i + 1}
              </div>

              <div className="flex-1 min-w-0">
                {/* Name + score */}
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-gray-900 text-sm truncate">{sme.name}</span>
                  <span className="text-xs text-gray-400 shrink-0">{sme.doc_count} docs</span>
                </div>

                {/* Score bar */}
                <div className="mt-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${i === 0 ? 'bg-indigo-500' : 'bg-indigo-300'}`}
                    style={{ width: `${barWidth}%` }}
                  />
                </div>

                {/* Role tags */}
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {sme.roles.map(role => (
                    <span key={role} className="text-xs text-indigo-600 bg-indigo-50 px-1.5 py-0.5 rounded">
                      {ROLE_ICONS[role] || '•'} {role}
                    </span>
                  ))}
                </div>

                {/* Contribution breakdown */}
                <div className="flex gap-3 mt-1">
                  {b.authored  > 0 && <span className="text-xs text-gray-400">{b.authored} authored</span>}
                  {b.reported  > 0 && <span className="text-xs text-gray-400">{b.reported} reported</span>}
                  {b.assigned  > 0 && <span className="text-xs text-gray-400">{b.assigned} assigned</span>}
                  {b.commented > 0 && <span className="text-xs text-gray-400">{b.commented} comments</span>}
                  {b.resolved  > 0 && <span className="text-xs text-gray-400">{b.resolved} resolved</span>}
                  {sme.last_active && (
                    <span className="text-xs text-gray-400 ml-auto">
                      last active {sme.last_active}
                    </span>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Best Answer Panel ─────────────────────────────────────────────────────────
function BestAnswerPanel({ answer }) {
  if (!answer) return null
  return (
    <div className="card p-4 border-2 border-teal-200 bg-gradient-to-br from-teal-50 to-white">
      <div className="flex items-center gap-2 mb-2">
        <div className="w-7 h-7 rounded-lg bg-teal-500 flex items-center justify-center">
          <span className="text-white text-xs font-bold">A</span>
        </div>
        <span className="font-semibold text-teal-800 text-sm">Best Match</span>
        <span className="ml-auto text-xs text-gray-400">extracted from top result</span>
      </div>
      <p className="text-gray-700 text-sm leading-relaxed">{answer}</p>
    </div>
  )
}

// ── Knowledge Card ────────────────────────────────────────────────────────────
function KnowledgeCard({ doc }) {
  const e = doc.entities || {}
  const hasEntities = (
    e.jira_tickets?.length || e.change_numbers?.length ||
    e.versions?.length || e.dates?.length || e.environments?.length
  )
  if (!hasEntities && !doc.related_docs?.length) return null

  return (
    <div className="mt-3 pt-3 border-t border-gray-100 space-y-2">
      {hasEntities && (
        <div className="flex flex-wrap gap-1.5">
          {e.environments?.map(env => (
            <span key={env} className="badge bg-green-50 text-green-700 text-xs">🌐 {env}</span>
          ))}
          {e.dates?.slice(0,3).map(d => (
            <span key={d} className="badge bg-blue-50 text-blue-700 text-xs">📅 {d}</span>
          ))}
          {e.versions?.slice(0,3).map(v => (
            <span key={v} className="badge bg-purple-50 text-purple-700 text-xs">🏷 v{v}</span>
          ))}
          {e.change_numbers?.slice(0,3).map(c => (
            <span key={c} className="badge bg-orange-50 text-orange-700 text-xs">🔄 {c}</span>
          ))}
          {e.jira_tickets?.slice(0,5).map(t => (
            <span key={t} className="badge bg-indigo-50 text-indigo-700 text-xs font-mono">🎫 {t}</span>
          ))}
        </div>
      )}
      {doc.related_docs?.length > 0 && (
        <div>
          <p className="text-xs text-gray-400 mb-1 flex items-center gap-1">
            <Link size={10}/> Related
          </p>
          <div className="space-y-1">
            {doc.related_docs.map((r, i) => (
              <a key={i} href={r.url} target="_blank" rel="noopener noreferrer"
                className="flex items-center gap-2 text-xs text-teal-600 hover:text-teal-800 group">
                <SourceBadge type={r.source_type} />
                <span className="truncate group-hover:underline">{r.title}</span>
                <ExternalLink size={9} className="shrink-0"/>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Result Card ───────────────────────────────────────────────────────────────
function ResultCard({ doc }) {
  const [expanded, setExpanded] = useState(false)
  const m = doc.metadata || {}
  const priorityColor = PRIORITY_COLORS[(m.priority || '').toLowerCase()] || 'bg-gray-100 text-gray-500'

  return (
    <div className="card overflow-hidden">
      <div className="p-4">
        <div className="flex items-start justify-between gap-2 mb-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <SourceBadge type={doc.source_type} />
            {m.status   && <span className="badge bg-gray-100 text-gray-600 text-xs">{m.status}</span>}
            {m.priority && <span className={`badge text-xs ${priorityColor}`}>{m.priority}</span>}
            {m.issue_type && <span className="badge bg-blue-50 text-blue-600 text-xs">{m.issue_type}</span>}
          </div>
          <a href={doc.url} target="_blank" rel="noopener noreferrer"
            className="shrink-0 flex items-center gap-1 text-xs text-teal-600 hover:text-teal-800 font-medium">
            <ExternalLink size={11}/> Open
          </a>
        </div>

        <h3 className="font-semibold text-gray-900 text-sm leading-snug mb-1">{doc.title}</h3>

        <p className="text-xs text-gray-400 mb-2">
          {doc.source}
          {doc.author   && ` · by ${doc.author}`}
          {m.assignee   && ` · assigned to ${m.assignee}`}
          {doc.updated_at && ` · ${new Date(doc.updated_at).toLocaleDateString()}`}
        </p>

        <p className="text-gray-600 text-xs leading-relaxed line-clamp-3">{doc.content_preview}</p>

        <KnowledgeCard doc={doc} />
      </div>

      <div className="border-t border-gray-100">
        <button onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center justify-between px-4 py-2 text-xs text-gray-400 hover:bg-gray-50 transition-colors">
          <span>{expanded ? 'Hide content' : 'Show full content'}</span>
          {expanded ? <ChevronUp size={12}/> : <ChevronDown size={12}/>}
        </button>
        {expanded && (
          <div className="px-4 pb-4">
            <div className="bg-gray-50 rounded-lg p-3 text-xs text-gray-700 leading-relaxed max-h-60 overflow-y-auto whitespace-pre-wrap">
              {doc.content_preview}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}


// ── GitHub Explain Panel ──────────────────────────────────────────────────────
function ExplainPanel({ docId, onClose }) {
  const [data, setData] = React.useState(null)
  const [loading, setLoading] = React.useState(true)
  const { useState, useEffect } = React

  useEffect(() => {
    axios.get(`/api/explain/${docId}`)
      .then(r => setData(r.data))
      .catch(() => setData({ error: true }))
      .finally(() => setLoading(false))
  }, [docId])

  if (loading) return (
    <div className="mt-3 p-4 bg-gray-50 rounded-lg border border-gray-200 flex items-center gap-2 text-sm text-gray-500">
      <Loader size={14} className="animate-spin"/> Analysing commit...
    </div>
  )

  if (!data || data.error) return (
    <div className="mt-3 p-3 bg-red-50 rounded-lg border border-red-200 text-sm text-red-600">
      Could not load explanation. Is this doc a GitHub commit or file?
    </div>
  )

  const Section = ({ title, children }) => (
    <div className="mb-3">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">{title}</p>
      <div className="text-sm text-gray-700">{children}</div>
    </div>
  )

  const Pill = ({ label, color = "gray" }) => {
    const colors = {
      gray: "bg-gray-100 text-gray-700", blue: "bg-blue-50 text-blue-700",
      green: "bg-green-50 text-green-700", red: "bg-red-50 text-red-700",
      purple: "bg-purple-50 text-purple-700", orange: "bg-orange-50 text-orange-700",
    }
    return <span className={`inline-block text-xs px-2 py-0.5 rounded mr-1 mb-1 font-mono ${colors[color]}`}>{label}</span>
  }

  return (
    <div className="mt-3 bg-slate-50 border border-slate-200 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-base">{data.category?.split(' ')[0]}</span>
          <span className="font-semibold text-gray-800 text-sm">{data.category?.split(' ').slice(1).join(' ')}</span>
          {data.change_size && <span className="text-xs bg-gray-200 text-gray-600 px-2 py-0.5 rounded">{data.change_size} change</span>}
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={14}/></button>
      </div>

      {/* Signal 3 — What changed */}
      {data.code_changes && (
        <Section title="🔧 What Changed (Static Analysis)">
          {data.code_changes.new_functions?.length > 0 && (
            <div className="mb-1"><span className="text-xs text-green-600 font-medium">New functions: </span>
              {data.code_changes.new_functions.map(f => <Pill key={f} label={f} color="green"/>)}</div>
          )}
          {data.code_changes.modified_functions?.length > 0 && (
            <div className="mb-1"><span className="text-xs text-blue-600 font-medium">Modified: </span>
              {data.code_changes.modified_functions.map(f => <Pill key={f} label={f} color="blue"/>)}</div>
          )}
          {data.code_changes.deleted_functions?.length > 0 && (
            <div className="mb-1"><span className="text-xs text-red-600 font-medium">Removed: </span>
              {data.code_changes.deleted_functions.map(f => <Pill key={f} label={f} color="red"/>)}</div>
          )}
          {data.code_changes.new_endpoints?.length > 0 && (
            <div className="mb-1"><span className="text-xs text-purple-600 font-medium">New endpoints: </span>
              {data.code_changes.new_endpoints.map(e => <Pill key={e} label={e} color="purple"/>)}</div>
          )}
          {data.code_changes.new_classes?.length > 0 && (
            <div className="mb-1"><span className="text-xs text-orange-600 font-medium">New classes: </span>
              {data.code_changes.new_classes.map(c => <Pill key={c} label={c} color="orange"/>)}</div>
          )}
          {data.code_changes.db_changes?.length > 0 && (
            <div className="mb-1"><span className="text-xs text-red-600 font-medium">DB changes: </span>
              {data.code_changes.db_changes.map((d,i) => <div key={i} className="text-xs font-mono bg-red-50 px-2 py-0.5 rounded mb-0.5">{d}</div>)}</div>
          )}
          {data.stats && (
            <p className="text-xs text-gray-400 mt-1">+{data.stats.added} additions / -{data.stats.removed} deletions</p>
          )}
        </Section>
      )}

      {/* Signal 1 — Why (Jira) */}
      {data.jira_context?.length > 0 && (
        <Section title="🎫 Why It Was Built (Jira)">
          {data.jira_context.map((j, i) => (
            <div key={i} className="bg-white border border-indigo-100 rounded-lg p-3 mb-2">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-mono bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded">{j.ticket}</span>
                {j.status && <span className="text-xs text-gray-500">{j.status}</span>}
                {j.priority && <span className="text-xs text-gray-500">· {j.priority}</span>}
              </div>
              <a href={j.url} target="_blank" rel="noopener noreferrer" className="text-sm font-medium text-indigo-700 hover:underline">{j.title}</a>
              {j.description && <p className="text-xs text-gray-500 mt-1 line-clamp-2">{j.description}</p>}
            </div>
          ))}
        </Section>
      )}

      {/* Signal 2 — How (PR) */}
      {data.pr_context && (
        <Section title="🔀 Pull Request Context">
          <div className="bg-white border border-gray-200 rounded-lg p-3">
            <a href={data.pr_context.url} target="_blank" rel="noopener noreferrer"
              className="text-sm font-medium text-gray-800 hover:underline">{data.pr_context.title}</a>
            {data.pr_context.body && (
              <p className="text-xs text-gray-500 mt-1 line-clamp-3">{data.pr_context.body}</p>
            )}
          </div>
        </Section>
      )}

      {/* Signal 4 — Architecture docs */}
      {data.architecture_docs?.length > 0 && (
        <Section title="📐 Architecture / Docs (Confluence/SharePoint)">
          {data.architecture_docs.map((d, i) => (
            <a key={i} href={d.url} target="_blank" rel="noopener noreferrer"
              className="flex items-start gap-2 bg-white border border-teal-100 rounded-lg p-2 mb-2 hover:border-teal-300 transition-colors">
              <span className="text-xs bg-teal-50 text-teal-700 px-1.5 py-0.5 rounded shrink-0">{d.source_type}</span>
              <div>
                <p className="text-xs font-medium text-gray-800">{d.title}</p>
                {d.preview && <p className="text-xs text-gray-400 line-clamp-1 mt-0.5">{d.preview}</p>}
              </div>
            </a>
          ))}
        </Section>
      )}
    </div>
  )
}

// ── GitHub Result Card ────────────────────────────────────────────────────────
function GitHubCard({ doc }) {
  const [showExplain, setShowExplain] = React.useState(false)
  const m = doc.metadata || {}
  const isCommit = m.content_type === 'commit'
  const isPR     = m.content_type === 'pull_request'
  const isFile   = m.content_type === 'file'

  const TypeIcon = isCommit ? GitCommit : isPR ? GitPullRequest : FileCode
  const typeColor = isCommit ? 'bg-orange-50 text-orange-700' :
                    isPR     ? 'bg-purple-50 text-purple-700' :
                               'bg-blue-50 text-blue-700'
  const typeLabel = isCommit ? `Commit · ${m.short_sha || ''}` :
                    isPR     ? `PR #${m.number}` :
                               `File · ${m.extension || ''}`

  return (
    <div className="card overflow-hidden">
      <div className="p-4">
        <div className="flex items-start justify-between gap-2 mb-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="badge bg-gray-800 text-white text-xs">GitHub</span>
            <span className={`badge text-xs flex items-center gap-1 ${typeColor}`}>
              <TypeIcon size={10}/>{typeLabel}
            </span>
            {m.repo && <span className="text-xs text-gray-400">{m.repo}</span>}
          </div>
          <a href={doc.url} target="_blank" rel="noopener noreferrer"
            className="shrink-0 flex items-center gap-1 text-xs text-teal-600 hover:text-teal-800 font-medium">
            <ExternalLink size={11}/> Open
          </a>
        </div>

        <h3 className="font-semibold text-gray-900 text-sm leading-snug mb-1">{doc.title}</h3>

        <p className="text-xs text-gray-400 mb-2">
          {doc.author && `by ${doc.author}`}
          {m.author_date && ` · ${m.author_date?.slice(0,10)}`}
          {isCommit && m.additions != null && ` · +${m.additions} -${m.deletions}`}
          {isCommit && m.files_changed?.length > 0 && ` · ${m.files_changed.length} files`}
        </p>

        <p className="text-gray-600 text-xs leading-relaxed line-clamp-3">{doc.content_preview}</p>

        {/* Files changed pills for commits */}
        {isCommit && m.files_changed?.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {m.files_changed.slice(0,6).map(f => (
              <span key={f} className="text-xs font-mono bg-gray-50 text-gray-500 px-1.5 py-0.5 rounded border border-gray-100">
                {f.split('/').pop()}
              </span>
            ))}
            {m.files_changed.length > 6 && (
              <span className="text-xs text-gray-400">+{m.files_changed.length - 6} more</span>
            )}
          </div>
        )}

        {/* Explain button for commits and files */}
        {(isCommit || isFile) && (
          <div className="mt-3">
            <button
              onClick={() => setShowExplain(v => !v)}
              className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-colors flex items-center gap-1.5 ${
                showExplain
                  ? 'bg-slate-200 text-slate-700'
                  : 'bg-slate-700 text-white hover:bg-slate-800'
              }`}>
              <FileCode size={11}/>
              {showExplain ? 'Hide explanation' : 'Explain this code'}
            </button>

            {showExplain && (
              <ExplainPanel docId={doc.id} onClose={() => setShowExplain(false)}/>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function SearchPage() {
  const [query, setQuery]               = useState('')
  const [sourceFilter, setSourceFilter] = useState('')
  const [results, setResults]           = useState(null)
  const [loading, setLoading]           = useState(false)
  const [page, setPage]                 = useState(1)

  const doSearch = async (q = query, src = sourceFilter, p = 1) => {
    if (!q.trim()) return
    setLoading(true)
    try {
      const params = new URLSearchParams({ q, page: p })
      if (src) params.append('source_type', src)
      const res = await axios.get(`/api/search?${params}`)
      setResults(res.data)
      setPage(p)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Search</h1>
        <p className="text-gray-500 text-sm mt-0.5">
          BM25 search · extracted entities · SME ranking · cross-linked results
        </p>
      </div>

      {/* Search bar */}
      <div className="card p-4 space-y-3">
        <div className="flex gap-3">
          <div className="relative flex-1">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"/>
            <input
              type="text"
              className="w-full pl-9 pr-9 py-2.5 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-400"
              placeholder='e.g. "when was feature X deployed" · "CHG-12345" · "who handles deployments"'
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && doSearch()}
            />
            {query && (
              <button onClick={() => { setQuery(''); setResults(null) }}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                <X size={14}/>
              </button>
            )}
          </div>
          <button className="btn-primary px-6" onClick={() => doSearch()} disabled={loading}>
            {loading ? 'Searching…' : 'Search'}
          </button>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-gray-500">Filter:</span>
          {['', ...SOURCES].map(src => (
            <button key={src}
              onClick={() => { setSourceFilter(src); if (query) doSearch(query, src) }}
              className={`badge cursor-pointer text-xs px-3 py-1 transition-colors ${
                sourceFilter === src ? 'bg-teal-500 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}>
              {src === '' ? 'All sources' : src}
            </button>
          ))}
        </div>
      </div>

      {loading && <div className="flex justify-center py-12"><Spinner/></div>}

      {!loading && results && (
        <div className="space-y-4">
          <p className="text-sm text-gray-500">
            <span className="font-semibold text-gray-900">{results.total?.toLocaleString()}</span> results
            for "<span className="italic">{results.query}</span>"
          </p>

          {/* Best Answer + SME side by side on wide screens */}
          {(results.best_answer || results.smes?.length > 0) && (
            <div className="grid md:grid-cols-2 gap-4">
              <BestAnswerPanel answer={results.best_answer} />
              <SMEPanel smes={results.smes} />
            </div>
          )}

          {/* Results */}
          {results.results?.length === 0
            ? <EmptyState icon="🔍" title="No results" subtitle="Try different keywords or remove the source filter."/>
            : <div className="space-y-3">
                {results.results.map(doc => doc.source_type === 'github' ? <GitHubCard key={doc.id} doc={doc}/> : <ResultCard key={doc.id} doc={doc}/>)}
              </div>
          }

          {/* Pagination */}
          {results.total > results.page_size && (
            <div className="flex justify-center gap-2 pt-2">
              <button className="btn-secondary text-sm" disabled={page === 1}
                onClick={() => doSearch(query, sourceFilter, page - 1)}>Previous</button>
              <span className="flex items-center px-4 text-sm text-gray-500">
                Page {page} of {Math.ceil(results.total / results.page_size)}
              </span>
              <button className="btn-secondary text-sm"
                disabled={page >= Math.ceil(results.total / results.page_size)}
                onClick={() => doSearch(query, sourceFilter, page + 1)}>Next</button>
            </div>
          )}
        </div>
      )}

      {!loading && !results && (
        <EmptyState icon="💡" title="Start searching"
          subtitle='Try: "deployment to production" · "release notes v2.0" · "who handles incidents"'/>
      )}
    </div>
  )
}
