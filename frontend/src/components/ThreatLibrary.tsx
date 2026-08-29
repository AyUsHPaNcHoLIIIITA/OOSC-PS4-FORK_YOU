import { useEffect, useState } from 'react';
import { listLibrary, runLibrary, getLeaderboard, buildModelUnderTest, modelIdentityFromConfig } from '../api';
import { Library, Trophy, PlayCircle, ShieldAlert, Loader2 } from 'lucide-react';

const SEVERITY_COLOR: Record<string, string> = {
  critical: 'text-rose-400 border-rose-500/40 bg-rose-500/10',
  high: 'text-orange-400 border-orange-500/40 bg-orange-500/10',
  medium: 'text-amber-400 border-amber-500/40 bg-amber-500/10',
  low: 'text-slate-400 border-slate-500/40 bg-slate-500/10',
};

const STATUS_COLOR: Record<string, string> = {
  UNSAFE: 'text-rose-400',
  NEEDS_REVIEW: 'text-amber-400',
  EVALUATION_INCOMPLETE: 'text-amber-400',
  PRODUCTION_READY: 'text-emerald-400',
};

export default function ThreatLibrary({ state }: { state: any }) {
  const [entries, setEntries] = useState<any[]>([]);
  const [board, setBoard] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string>('');

  const refresh = async () => {
    setLoading(true);
    try {
      const [lib, lb] = await Promise.all([listLibrary(), getLeaderboard()]);
      setEntries(lib || []);
      setBoard(lb || []);
    } catch (e: any) {
      setMessage(`Failed to load: ${e?.message || e}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleRunSuite = async () => {
    if (!state?.systemPrompt || !state?.tools?.length) {
      setMessage('Configure an agent (system prompt + tools) on the Setup page first.');
      return;
    }
    setRunning(true);
    setMessage('');
    try {
      const res = await runLibrary(state.agentVersion, state.systemPrompt, state.tools, undefined, buildModelUnderTest(state.modelConfig));
      const verdicts = res?.verdicts || [];
      const fails = verdicts.filter((v: any) => v.outcome === 'FAIL').length;
      const id = modelIdentityFromConfig(state.modelConfig);
      const against = id ? `${state.agentVersion} on ${id.provider} (${id.endpoint})` : state.agentVersion;
      setMessage(
        `Ran ${verdicts.length} saved attacks against ${against}: ` +
          `${verdicts.length - fails} passed, ${fails} failed. Score: ${res?.scorecard?.overall_score ?? '—'}/100.`
      );
      await refresh();
    } catch (e: any) {
      setMessage(`Run failed: ${e?.response?.data?.detail || e?.message || e}`);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-3">
          <Library className="w-7 h-7 text-indigo-400" />
          <div>
            <h1 className="text-2xl font-bold text-slate-100">Threat Library & Leaderboard</h1>
            <p className="text-sm text-slate-400">Reusable attack suite. Re-run saved threats against any agent version.</p>
          </div>
        </div>
        <button
          onClick={handleRunSuite}
          disabled={running || entries.length === 0}
          className="glass-btn glow-cta px-5 py-2.5 rounded-xl font-semibold flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <PlayCircle className="w-4 h-4" />}
          Run suite vs <code className="text-indigo-300">{state?.agentVersion || 'agent'}</code>
        </button>
      </div>

      {message && (
        <div className="glass-accent rounded-xl p-4 text-sm text-slate-200">{message}</div>
      )}

      {/* Leaderboard */}
      <section className="glass rounded-2xl p-6">
        <div className="flex items-center gap-2 mb-4">
          <Trophy className="w-5 h-5 text-amber-400" />
          <h2 className="text-lg font-semibold text-slate-100">Version Leaderboard</h2>
        </div>
        {board.length === 0 ? (
          <p className="text-sm text-slate-500 italic">No evaluated versions yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 text-xs uppercase tracking-wide">
                  <th className="text-left py-2 px-3">#</th>
                  <th className="text-left py-2 px-3">Agent Version</th>
                  <th className="text-right py-2 px-3">Score</th>
                  <th className="text-left py-2 px-3">Status</th>
                  <th className="text-right py-2 px-3">Critical Failures</th>
                </tr>
              </thead>
              <tbody>
                {board.map((row, i) => (
                  <tr key={row.agent_version} className="border-t border-white/5">
                    <td className="py-2 px-3 text-slate-500">{i + 1}</td>
                    <td className="py-2 px-3 font-medium text-slate-200">{row.agent_version}</td>
                    <td className="py-2 px-3 text-right font-bold text-slate-100">{row.overall_score}</td>
                    <td className={`py-2 px-3 font-semibold ${STATUS_COLOR[row.safety_status] || 'text-slate-300'}`}>
                      {row.safety_status}
                    </td>
                    <td className="py-2 px-3 text-right">{row.critical_guardrail_failures}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Library entries */}
      <section className="glass rounded-2xl p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <ShieldAlert className="w-5 h-5 text-rose-400" />
            <h2 className="text-lg font-semibold text-slate-100">Saved Attacks ({entries.length})</h2>
          </div>
          <button onClick={refresh} className="text-xs text-indigo-400 hover:text-indigo-300">Refresh</button>
        </div>
        {loading ? (
          <p className="text-sm text-slate-500 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</p>
        ) : entries.length === 0 ? (
          <p className="text-sm text-slate-500 italic">
            Library is empty. On the Setup page, run scenarios then use “Add failing attacks to library”.
          </p>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {entries.map((e) => (
              <div key={e.entry_id} className="glass-dark rounded-xl p-4 border border-white/5">
                <div className="flex items-start justify-between gap-2">
                  <span className="font-medium text-slate-100 text-sm">{e.title}</span>
                  <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded border ${SEVERITY_COLOR[e.severity] || SEVERITY_COLOR.low}`}>
                    {e.severity}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-400">
                  <span className="px-2 py-0.5 rounded bg-white/5">{e.category}</span>
                  {e.target_tool && <span className="px-2 py-0.5 rounded bg-white/5">tool: {e.target_tool}</span>}
                  {e.pressure_technique && <span className="px-2 py-0.5 rounded bg-white/5">{e.pressure_technique}</span>}
                </div>
                {e.source_agent_version && (
                  <p className="mt-2 text-[11px] text-slate-500">captured from {e.source_agent_version}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
