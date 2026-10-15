import Dashboard from './pages/Dashboard.jsx'
import ModelManager from './pages/ModelManager.jsx'
import Policies from './pages/Policies.jsx'

// Three real pages, no dev-only style guide. Vite's default SPA fallback
// serves index.html for any path, so a plain pathname check is enough.
export default function App() {
  if (window.location.pathname === '/model') {
    return <ModelManager />
  }
  if (window.location.pathname === '/policies') {
    return <Policies />
  }
  return <Dashboard />
}
