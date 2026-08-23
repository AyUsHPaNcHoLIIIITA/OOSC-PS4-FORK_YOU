import React, { useState } from 'react';
import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import AgentSetup from './components/AgentSetup';
import ScorecardView from './components/ScorecardView';
import { ShieldAlert } from 'lucide-react';

function App() {
  const [globalState, setGlobalState] = useState<any>({
    agentVersion: 'v1.0',
    systemPrompt: '',
    tools: [],
    scenarios: [],
    runs: [],
    verdicts: []
  });

  return (
    <Router>
      <div className="min-h-screen bg-slate-950 text-slate-200 font-sans selection:bg-indigo-500/30">
        <nav className="bg-slate-900 border-b border-slate-800 p-4 sticky top-0 z-50 shadow-lg">
          <div className="max-w-6xl mx-auto flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <ShieldAlert className="text-rose-500 w-6 h-6" />
              <span className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-rose-400 to-indigo-400">AgentCI</span>
            </div>
            <div className="space-x-6 text-sm font-medium">
              <Link to="/" className="hover:text-indigo-400 transition-colors">Setup & Generation</Link>
              <Link to="/scorecard" className="hover:text-indigo-400 transition-colors">Scorecard</Link>
            </div>
          </div>
        </nav>
        <main className="max-w-6xl mx-auto p-6">
          <Routes>
            <Route path="/" element={<AgentSetup state={globalState} setState={setGlobalState} />} />
            <Route path="/scorecard" element={<ScorecardView state={globalState} />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}

export default App;
