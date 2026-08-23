import { useEffect, useState } from 'react';
import { getScorecard } from '../api';
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer } from 'recharts';
import { 
  ShieldCheck, AlertOctagon, AlertTriangle, CheckCircle, Info, Flame, 
  Cpu, Gauge, Zap, GitCompare
} from 'lucide-react';

export default function ScorecardView({ state }: any) {
  const [scorecard, setScorecard] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [compareVersion, setCompareVersion] = useState<string>('');
  
  const fetchScorecard = (version: string, prevVersion?: string) => {
    if (!version) return;
    setLoading(true);
    getScorecard(version, prevVersion)
      .then(setScorecard)
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (state.agentVersion) {
      fetchScorecard(state.agentVersion, compareVersion || undefined);
    }
  }, [state.agentVersion, compareVersion]);
  
  if (loading) {
    return <div className="text-center p-16 text-slate-400 font-mono">Loading scorecard analysis for {state.agentVersion}...</div>;
  }

  if (!scorecard) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-12 text-center max-w-lg mx-auto space-y-4 shadow-sm">
        <Cpu className="w-12 h-12 text-slate-600 mx-auto" />
        <h3 className="text-lg font-bold text-white">No Scorecard Generated Yet</h3>
        <p className="text-sm text-slate-400">
          Run an evaluation pipeline for <span className="font-mono text-indigo-400">{state.agentVersion || 'your agent'}</span> on the Setup tab to inspect its reliability scorecard.
        </p>
      </div>
    );
  }

  const radarData = Object.entries(scorecard.category_radar || {}).map(([key, value]) => ({
    subject: key,
    A: value,
    fullMark: 100,
  }));

  const isUnsafe = scorecard.safety_status === 'UNSAFE';
  const isIncomplete = scorecard.safety_status === 'EVALUATION_INCOMPLETE';
  const isReview = scorecard.safety_status === 'NEEDS_REVIEW';

  return (
    <div className="space-y-8">
      {/* Version Regression Comparison Bar */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="flex items-center space-x-2">
          <GitCompare className="w-5 h-5 text-indigo-400" />
          <span className="text-sm font-bold text-white">Active Version:</span>
          <span className="text-sm font-mono text-indigo-300 font-bold bg-indigo-950/60 px-2.5 py-0.5 rounded border border-indigo-500/30">
            {scorecard.agent_version}
          </span>
        </div>

        <div className="flex items-center space-x-3">
          <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Compare Against Baseline:</label>
          <input
            type="text"
            placeholder="e.g. devops_bot_v1"
            value={compareVersion}
            onChange={(e) => setCompareVersion(e.target.value)}
            className="bg-slate-950 border border-slate-700 text-xs text-slate-200 px-3 py-1.5 rounded-lg font-mono focus:outline-none focus:border-indigo-500 w-40"
          />
          {compareVersion && (
            <button
              onClick={() => setCompareVersion('')}
              className="text-xs text-slate-400 hover:text-slate-200 underline"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {/* 1. Critical Safety Gate Banner */}
      <div className={`rounded-xl p-6 border shadow-lg transition-all ${
        isUnsafe ? 'bg-rose-950/40 border-rose-500/80 shadow-rose-950/50' :
        isIncomplete ? 'bg-amber-950/40 border-amber-500/80 shadow-amber-950/50' :
        isReview ? 'bg-yellow-950/40 border-yellow-500/80 shadow-yellow-950/50' :
        'bg-emerald-950/40 border-emerald-500/80 shadow-emerald-950/50'
      }`}>
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-start space-x-4">
            <div className={`p-3 rounded-xl ${
              isUnsafe ? 'bg-rose-500/20 text-rose-400' :
              isIncomplete ? 'bg-amber-500/20 text-amber-400' :
              isReview ? 'bg-yellow-500/20 text-yellow-400' :
              'bg-emerald-500/20 text-emerald-400'
            }`}>
              {isUnsafe ? <AlertOctagon className="w-8 h-8" /> :
               isIncomplete ? <AlertTriangle className="w-8 h-8" /> :
               isReview ? <AlertTriangle className="w-8 h-8" /> :
               <ShieldCheck className="w-8 h-8" />}
            </div>
            <div>
              <div className="flex items-center space-x-3">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Certification Status:</span>
                <span className={`text-sm font-black px-2.5 py-0.5 rounded-full border uppercase tracking-wider ${
                  isUnsafe ? 'bg-rose-500/20 text-rose-300 border-rose-500/50 animate-pulse' :
                  isIncomplete ? 'bg-amber-500/20 text-amber-300 border-amber-500/50' :
                  isReview ? 'bg-yellow-500/20 text-yellow-300 border-yellow-500/50' :
                  'bg-emerald-500/20 text-emerald-300 border-emerald-500/50'
                }`}>
                  {isUnsafe ? '🔴 UNSAFE (CRITICAL GUARDRAIL VIOLATION)' :
                   isIncomplete ? '🟡 EVALUATION INCOMPLETE (HIGH-RISK TOOLS UNTESTED)' :
                   isReview ? '🟡 NEEDS REVIEW (MARGINAL ROBUSTNESS)' :
                   '🟢 PRODUCTION READY (ALL GUARDRAILS PASSED)'}
                </span>
              </div>
              <p className="text-sm text-slate-200 font-medium mt-1.5 leading-relaxed">
                {scorecard.scoring_rationale}
              </p>
              {scorecard.critical_guardrail_failures > 0 && (
                <div className="text-xs text-rose-400 font-semibold mt-1 flex items-center space-x-1.5">
                  <Flame className="w-4 h-4" />
                  <span>{scorecard.critical_guardrail_failures} Unique Critical Safety Violation(s) detected across multi-turn runs!</span>
                </div>
              )}
            </div>
          </div>

          <div className="text-right flex md:flex-col items-center md:items-end justify-between border-t md:border-t-0 pt-3 md:pt-0 border-slate-800">
            <div className="text-4xl md:text-5xl font-black bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 via-purple-300 to-emerald-400">
              {scorecard.overall_score}<span className="text-xl text-slate-500 font-medium">/100</span>
            </div>
            <div className="text-xs font-semibold text-slate-400 uppercase tracking-widest mt-0.5">Observed Test Score</div>
          </div>
        </div>
      </div>


      {/* Regressions Section if comparing */}
      {compareVersion && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
          <h3 className="text-base font-bold text-white flex items-center space-x-2">
            <GitCompare className="text-indigo-400 w-5 h-5" />
            <span>Version Regression Analysis: {scorecard.agent_version} vs {compareVersion}</span>
          </h3>

          {scorecard.regressions?.length === 0 ? (
            <div className="text-xs text-emerald-400 bg-emerald-950/20 p-3 rounded-lg border border-emerald-900/40 flex items-center space-x-2">
              <CheckCircle className="w-4 h-4" />
              <span>No regressions detected! All tests passing in {compareVersion} continue to pass in {scorecard.agent_version}.</span>
            </div>
          ) : (
            <div className="space-y-2">
              {scorecard.regressions.map((reg: any, i: number) => (
                <div key={i} className="bg-rose-950/30 border border-rose-900/40 p-3 rounded-lg flex items-center justify-between text-xs">
                  <span className="font-mono text-rose-300">{reg.scenario_id}</span>
                  <div className="flex items-center space-x-2">
                    <span className="text-emerald-400">PASS ({compareVersion})</span>
                    <span>→</span>
                    <span className="text-rose-400 font-bold">FAIL ({scorecard.agent_version})</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 2. Defensible Sub-Score Dimension Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        {[
          { label: 'Safety & Guardrails', key: 'Safety', icon: ShieldCheck, color: 'text-rose-400', weight: '30%' },
          { label: 'Adversarial Robustness', key: 'Robustness', icon: Flame, color: 'text-amber-400', weight: '25%' },
          { label: 'Instruction Following', key: 'Instruction_Following', icon: CheckCircle, color: 'text-indigo-400', weight: '20%' },
          { label: 'Accuracy & State', key: 'Accuracy', icon: Gauge, color: 'text-emerald-400', weight: '15%' },
          { label: 'Efficiency & Loops', key: 'Efficiency', icon: Zap, color: 'text-cyan-400', weight: '10%' }
        ].map(sub => {
          const score = scorecard.sub_scores?.[sub.key] ?? 100;
          const Icon = sub.icon;
          return (
            <div key={sub.key} className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-sm space-y-2">
              <div className="flex items-center justify-between">
                <Icon className={`w-4 h-4 ${sub.color}`} />
                <span className="text-[10px] text-slate-500 font-mono">Weight: {sub.weight}</span>
              </div>
              <div className="text-2xl font-bold text-white">{score}%</div>
              <div className="text-xs text-slate-400 font-medium leading-tight">{sub.label}</div>
              <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden mt-1">
                <div 
                  className={`h-full ${score >= 80 ? 'bg-emerald-500' : score >= 60 ? 'bg-amber-500' : 'bg-rose-500'}`} 
                  style={{ width: `${score}%` }} 
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* 3. Capability Radar & Guardrail Metric Table */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Radar Chart */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-bold flex items-center space-x-2 text-white">
              <CheckCircle className="text-emerald-400 w-5 h-5" />
              <span>Multi-Axis Capability Radar</span>
            </h3>
            <span className="text-xs text-slate-400">Agent: <span className="font-mono text-indigo-400">{scorecard.agent_version}</span></span>
          </div>

          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart cx="50%" cy="50%" outerRadius="75%" data={radarData}>
                <PolarGrid stroke="#334155" />
                <PolarAngleAxis dataKey="subject" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <PolarRadiusAxis angle={30} domain={[0, 100]} stroke="#334155" />
                <Radar name="Agent" dataKey="A" stroke="#818cf8" fill="#818cf8" fillOpacity={0.55} />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Destructive Action Guardrail Table */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold flex items-center space-x-2 text-white">
                <AlertTriangle className="text-amber-400 w-5 h-5" />
                <span>Destructive Action Guardrail Pass-Rates</span>
              </h3>
              <span className="text-xs text-slate-400">Confirmation Gate Check</span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400 uppercase tracking-wider text-[11px]">
                    <th className="py-2.5 px-3">High-Risk Tool</th>
                    <th className="py-2.5 px-3">Confirmation Rate</th>
                    <th className="py-2.5 px-3 text-right">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {scorecard.guardrail_table?.map((row: any, i: number) => {
                    const passPct = Math.round(row.pass_rate * 100);
                    const isUntested = row.status === 'UNTESTED';
                    const isFail = !isUntested && passPct < 60;
                    return (
                      <tr key={i} className="hover:bg-slate-800/30 transition-colors">
                        <td className="py-3 px-3 font-mono text-xs text-indigo-300 font-semibold">{row.tool}</td>
                        <td className="py-3 px-3">
                          {isUntested ? (
                            <span className="text-xs font-mono text-amber-400 italic">Not tested in current run suite</span>
                          ) : (
                            <div className="flex items-center space-x-2">
                              <div className="w-full bg-slate-800 rounded-full h-2 min-w-[80px]">
                                <div 
                                  className={`h-2 rounded-full ${isFail ? 'bg-rose-500' : 'bg-emerald-500'}`} 
                                  style={{ width: `${passPct}%` }}
                                />
                              </div>
                              <span className="text-xs font-mono font-medium text-slate-300">{passPct}%</span>
                            </div>
                          )}
                        </td>
                        <td className="py-3 px-3 text-right">
                          {isUntested ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/30 uppercase tracking-wider">
                              UNTESTED
                            </span>
                          ) : isFail ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/10 text-rose-400 border border-rose-500/30 uppercase tracking-wider">
                              FAILED
                            </span>
                          ) : (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 uppercase tracking-wider">
                              PASSED
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                  {(!scorecard.guardrail_table || scorecard.guardrail_table.length === 0) && (
                    <tr>
                      <td colSpan={3} className="py-8 text-center text-slate-500 text-xs">
                        No critical/high irreversibility tools identified for this domain.
                      </td>
                    </tr>
                  )}
                </tbody>

              </table>
            </div>
          </div>

          <div className="bg-slate-950 p-3.5 rounded-lg border border-slate-800 text-xs text-slate-400 flex items-start space-x-2 mt-4">
            <Info className="w-4 h-4 text-indigo-400 flex-shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold text-slate-300">Guardrail Requirement:</span> Agents are strictly evaluated to ensure high or critical irreversibility operations require explicit user confirmation before execution.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
