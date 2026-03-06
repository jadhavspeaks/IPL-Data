import { Routes, Route, NavLink, useLocation } from 'react-router-dom'
import { LayoutDashboard, Search, FileText, Settings, Brain } from 'lucide-react'
import Dashboard from './pages/Dashboard'
import SearchPage from './pages/Search'
import Documents from './pages/Documents'

const NAV = [
  { to: '/',          icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/search',    icon: Search,          label: 'Search'    },
  { to: '/documents', icon: FileText,        label: 'Documents' },
]

export default function App() {
  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 bg-navy-700 flex flex-col shrink-0" style={{ backgroundColor: '#1e3a5f' }}>
        {/* Logo */}
        <div className="px-5 py-5 border-b border-white/10">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-teal-500 flex items-center justify-center">
              <Brain size={18} className="text-white" />
            </div>
            <div>
              <p className="text-white font-bold text-sm leading-tight">EKM</p>
              <p className="text-white/50 text-xs">Knowledge Hub</p>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-1">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink key={to} to={to} end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-teal-500 text-white'
                    : 'text-white/60 hover:text-white hover:bg-white/10'
                }`
              }
            >
              <Icon size={17} />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-white/10">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-teal-400 animate-pulse" />
            <span className="text-white/50 text-xs">MVP v1.0</span>
          </div>
          <p className="text-white/30 text-xs mt-1">ServiceNow: future scope</p>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-6xl mx-auto p-6">
          <Routes>
            <Route path="/"          element={<Dashboard />} />
            <Route path="/search"    element={<SearchPage />} />
            <Route path="/documents" element={<Documents />} />
          </Routes>
        </div>
      </main>
    </div>
  )
}
