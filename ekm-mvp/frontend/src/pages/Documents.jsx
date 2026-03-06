import { useState, useEffect } from 'react'
import { listDocuments } from '../api'
import { DocCard, EmptyState, Spinner, SourceBadge } from '../components/UI'

const SOURCES = ['', 'sharepoint', 'confluence', 'jira', 'github']
const SOURCE_LABELS = { '': 'All', sharepoint: 'SharePoint', confluence: 'Confluence', jira: 'Jira', github: 'GitHub' }

export default function Documents() {
  const [docs, setDocs] = useState(null)
  const [loading, setLoading] = useState(true)
  const [sourceFilter, setSourceFilter] = useState('')
  const [page, setPage] = useState(1)

  const load = async (src = sourceFilter, p = 1) => {
    setLoading(true)
    try {
      const res = await listDocuments(src, p)
      setDocs(res.data)
      setPage(p)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleFilter = (src) => {
    setSourceFilter(src)
    load(src, 1)
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Documents</h1>
        <p className="text-gray-500 text-sm mt-0.5">Browse all indexed documents</p>
      </div>

      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        {SOURCES.map(src => (
          <button key={src}
            onClick={() => handleFilter(src)}
            className={`badge text-sm px-3 py-1 cursor-pointer transition-colors ${
              sourceFilter === src
                ? 'bg-navy-700 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {SOURCE_LABELS[src]}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Spinner /></div>
      ) : docs?.results?.length > 0 ? (
        <>
          <p className="text-sm text-gray-500">
            Showing <span className="font-semibold">{docs.results.length}</span> of{' '}
            <span className="font-semibold">{docs.total.toLocaleString()}</span> documents
          </p>

          <div className="grid md:grid-cols-2 gap-3">
            {docs.results.map(doc => (
              <DocCard key={doc.id} doc={doc}
                onClick={() => window.open(doc.url, '_blank')} />
            ))}
          </div>

          {/* Pagination */}
          {docs.total > docs.page_size && (
            <div className="flex justify-center gap-2 pt-2">
              <button className="btn-secondary text-sm" disabled={page === 1}
                onClick={() => load(sourceFilter, page - 1)}>
                Previous
              </button>
              <span className="flex items-center px-4 text-sm text-gray-500">
                Page {page} of {Math.ceil(docs.total / docs.page_size)}
              </span>
              <button className="btn-secondary text-sm"
                disabled={page >= Math.ceil(docs.total / docs.page_size)}
                onClick={() => load(sourceFilter, page + 1)}>
                Next
              </button>
            </div>
          )}
        </>
      ) : (
        <EmptyState icon="📄" title="No documents yet"
          subtitle="Run a sync from the Dashboard to start indexing documents." />
      )}
    </div>
  )
}
