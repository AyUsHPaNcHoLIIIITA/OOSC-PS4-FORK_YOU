import { useState, lazy, Suspense } from 'react';
import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import AgentSetup from './components/AgentSetup';
import ScorecardView from './components/ScorecardView';
import ThreatLibrary from './components/ThreatLibrary';
import BrainHero from './components/BrainHero';
import { ShieldAlert } from 'lucide-react';

// Lazy so the WebGL view (three.js, loaded from CDN) never weighs down the
// initial bundle — it's only fetched when the user opens the 3D Pipeline tab.
const PipelineView3D = lazy(() => import('./components/PipelineView3D'));

function App() {
  const [globalState, setGlobalState] = useState<any>({
    agentVersion: 'v1.0',
    systemPrompt: '',
    tools: [],
    scenarios: [],
    runs: [],
    verdicts: [],
    // Setup-page working state lifted here so it survives route navigation
    // (AgentSetup unmounts on route change; anything left in its local useState
    // is wiped). Keeps the live console, analysis panel, and test matrix intact.
    logs: [],
    analysis: null,
    agentDomain: 'devops',
    selectedCounts: {
      happy_path: 1,
      destructive_action_pressure: 1,
      direct_injection: 1,
      indirect_injection: 1
    },
    samplesPerScenario: 1,
    activeTab: 'console'
  });

  return (
    <Router>
      <div className="min-h-screen overflow-x-hidden text-slate-200 font-sans selection:bg-indigo-500/30">
        <nav className="glass-nav p-4 sticky top-0 z-50">
          <div className="max-w-6xl mx-auto flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <ShieldAlert className="text-rose-500 w-6 h-6" />
              <span className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-rose-400 to-indigo-400">AgentCI</span>
            </div>
            <div className="space-x-6 text-sm font-medium">
              <Link to="/" className="hover:text-indigo-400 transition-colors">Setup & Generation</Link>
              <Link to="/scorecard" className="hover:text-indigo-400 transition-colors">Scorecard</Link>
              <Link to="/pipeline" className="hover:text-indigo-400 transition-colors">3D Pipeline</Link>
              <Link to="/threats" className="hover:text-indigo-400 transition-colors">Threat Library</Link>
            </div>
          </div>
        </nav>
        <main className="max-w-6xl mx-auto p-6">
          <Routes>
            <Route
              path="/"
              element={
                <>
                  <BrainHero />
                  <div id="app-start" className="scroll-mt-24">
                    <AgentSetup state={globalState} setState={setGlobalState} />
                  </div>
                </>
              }
            />
            <Route path="/scorecard" element={<ScorecardView state={globalState} />} />
            <Route
              path="/pipeline"
              element={
                <Suspense fallback={<div className="text-center p-16 text-slate-400 font-mono">Loading 3D pipeline…</div>}>
                  <PipelineView3D state={globalState} />
                </Suspense>
              }
            />
            <Route path="/threats" element={<ThreatLibrary state={globalState} />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}

export default App;
