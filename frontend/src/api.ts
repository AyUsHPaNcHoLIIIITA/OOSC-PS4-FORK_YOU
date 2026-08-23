import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000/api',
});

export const generateScenarios = async (systemPrompt: string, tools: any[], taskDomain: string, countPerCategory: any) => {
  const res = await api.post('/scenarios/generate', {
    system_prompt: systemPrompt,
    tools,
    task_domain: taskDomain,
    count_per_category: countPerCategory
  });
  return res.data;
};

export const executeRuns = async (scenarioIds: string[], agentVersion: string, systemPrompt: string, tools: any[]) => {
  const res = await api.post('/runs/execute', {
    scenario_ids: scenarioIds,
    agent_version: agentVersion,
    system_prompt: systemPrompt,
    tools
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


