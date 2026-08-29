import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || (typeof window !== 'undefined' && window.location.hostname === 'localhost' ? 'http://localhost:8000/api' : '/api');

const api = axios.create({
  baseURL: API_BASE_URL,
});

// Fail loud on a misconfigured deploy. In production the frontend is served by a
// static host with a SPA catch-all: if /api is NOT routed to the backend, an API
// call falls through to that rewrite and returns index.html (HTML, HTTP 200).
// Without this guard that HTML would be handed back as `res.data` and blow up
// later as an opaque ".map is not a function". Instead we detect it here and
// throw an actionable error. (getReportMarkdown legitimately returns text/plain,
// which is allowed — only text/html is treated as the misroute signal.)
api.interceptors.response.use(
  (res) => {
    const ct = String(res.headers?.['content-type'] || '');
    const looksLikeHtml =
      ct.includes('text/html') ||
      (typeof res.data === 'string' && /^\s*<(?:!doctype|html)/i.test(res.data));
    if (looksLikeHtml) {
      throw new Error(
        `AgentCI backend not reachable at "${API_BASE_URL}": the API returned an HTML page ` +
          `instead of JSON. The frontend is deployed but /api is not routed to the backend. ` +
          `Set VITE_API_BASE_URL to your backend URL (e.g. https://your-app.onrender.com/api) ` +
          `in the Vercel project env, or add an /api proxy rewrite pointing at the backend.`,
      );
    }
    return res;
  },
  (err) => {
    if (err?.response) {
      const { status, statusText } = err.response;
      throw new Error(
        `AgentCI backend error ${status}${statusText ? ` (${statusText})` : ''} from ${err.config?.url ?? 'API'}.`,
      );
    }
    throw new Error(
      `AgentCI backend unreachable at "${API_BASE_URL}". Is the backend running, and is ` +
        `VITE_API_BASE_URL set for this deploy? (${err?.message ?? 'network error'})`,
    );
  },
);

export const generateScenarios = async (systemPrompt: string, tools: any[], taskDomain: string, countPerCategory: any) => {
  const res = await api.post('/scenarios/generate', {
    system_prompt: systemPrompt,
    tools,
    task_domain: taskDomain,
    count_per_category: countPerCategory
  });
  return res.data;
};

export const executeRuns = async (scenarioIds: string[], agentVersion: string, systemPrompt: string, tools: any[], samples: number = 1) => {
  const res = await api.post('/runs/execute', {
    scenario_ids: scenarioIds,
    agent_version: agentVersion,
    system_prompt: systemPrompt,
    tools,
    samples
  });
  return res.data;
};

export const classifyRuns = async (runIds: string[], tools: any[]) => {
  const res = await api.post('/classify', {
    run_ids: runIds,
    tools
  });
  return res.data;
};

export const analyzeAgent = async (systemPrompt: string, tools: any[], taskDomain: string) => {
  const res = await api.post('/agent/analyze', {
    system_prompt: systemPrompt,
    tools,
    task_domain: taskDomain
  });
  return res.data;
};

export const autoGenerateScenarios = async (systemPrompt: string, tools: any[], taskDomain: string, overrideCounts?: any) => {
  const res = await api.post('/agent/auto-generate', {
    system_prompt: systemPrompt,
    tools,
    task_domain: taskDomain,
    override_counts: overrideCounts
  });
  return res.data;
};

export const replayRun = async (runId: string, systemPrompt: string, tools: any[]) => {
  const res = await api.post(`/runs/replay/${runId}`, {
    system_prompt: systemPrompt,
    tools
  });
  return res.data;
};

export const listScenarios = async () => {
  const res = await api.get('/scenarios/list');
  return res.data;
};

export const getScorecard = async (agentVersion: string, previousVersion?: string) => {
  const params = previousVersion ? { previous_version: previousVersion } : {};
  const res = await api.get(`/scorecard/${agentVersion}`, { params });
  return res.data;
};

// --- Feature 1: CI Ship-Gate + embeddable badge ---
export const getCiGate = async (agentVersion: string, previousVersion?: string, minScore?: number) => {
  const res = await api.post('/ci/gate', {
    agent_version: agentVersion,
    previous_version: previousVersion,
    min_score: minScore ?? 75,
  });
  return res.data;
};

// Absolute (or /api-proxied) URLs for direct <img src> / new-tab use — mirror the
// same base axios uses, so whatever proxy makes the API reachable also serves these.
export const badgeUrl = (agentVersion: string) =>
  `${API_BASE_URL}/badge/${encodeURIComponent(agentVersion)}.svg`;

// --- Feature 4: exportable report ---
export const reportUrl = (agentVersion: string) =>
  `${API_BASE_URL}/report/${encodeURIComponent(agentVersion)}.html`;

// Fetch the Markdown flavor of the report (for one-click copy into a PR/issue).
export const getReportMarkdown = async (agentVersion: string) => {
  const res = await api.get(`/report/${encodeURIComponent(agentVersion)}.md`, {
    responseType: 'text',
    transformResponse: [(d) => d],
  });
  return res.data as string;
};

// --- Feature 3: Threat Library + Leaderboard ---
export const addToLibrary = async (agentVersion?: string, scenarioIds?: string[]) => {
  const res = await api.post('/library/add', {
    agent_version: agentVersion,
    scenario_ids: scenarioIds,
  });
  return res.data;
};

export const listLibrary = async () => {
  const res = await api.get('/library/list');
  return res.data;
};

export const runLibrary = async (agentVersion: string, systemPrompt: string, tools: any[], entryIds?: string[]) => {
  const res = await api.post('/library/run', {
    agent_version: agentVersion,
    system_prompt: systemPrompt,
    tools,
    entry_ids: entryIds,
  });
  return res.data;
};

export const getLeaderboard = async () => {
  const res = await api.get('/leaderboard');
  return res.data;
};


