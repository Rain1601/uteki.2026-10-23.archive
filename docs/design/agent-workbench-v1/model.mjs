// Pure interaction state. No networking, persistence or real job execution.
const enumValue = (value, values, name) => {
  if (!values.includes(value)) throw new Error(`Unsupported ${name}: ${String(value)}`);
  return value;
};
const required = (value, name) => {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${name} is required`);
  return value;
};
const checkedText = (value, name, nonempty = false) => {
  if (typeof value !== 'string') throw new Error(`${name} must be text`);
  if (value.length > 4000) throw new Error(`${name} cannot exceed 4000 characters`);
  if (nonempty && !value.trim()) throw new Error(`${name} is required`);
  return value;
};
const localized = (zh, en) => ({ zh, en });

export const reviewKey = (taskId, runId, criterionId) => JSON.stringify([taskId, runId, criterionId]);
export const draftKey = (taskId, runId) => JSON.stringify([taskId, runId]);

export function getTask(data, taskId) {
  required(taskId, 'taskId');
  const task = data.tasks.find(item => item.id === taskId);
  if (!task) throw new Error(`Unknown task: ${taskId}`);
  return task;
}

export function listRuns(data, taskId, state = {}) {
  const task = getTask(data, taskId);
  return [...task.runs, ...(state.pendingRuns ?? []).filter(run => run.taskId === taskId)];
}

export function getRun(data, taskId, runId, state = {}) {
  required(runId, 'runId');
  const run = listRuns(data, taskId, state).find(item => item.id === runId);
  if (!run) throw new Error(`Run ${runId} does not belong to task ${taskId}`);
  return run;
}

export function getArtifact(data, artifactId) {
  required(artifactId, 'artifactId');
  const artifact = data.artifacts.find(item => item.id === artifactId);
  if (!artifact) throw new Error(`Unknown artifact: ${artifactId}`);
  const run = getRun(data, artifact.taskId, artifact.runId);
  if (!run.artifactIds.includes(artifact.id)) throw new Error(`Artifact ${artifactId} is outside its declared run`);
  return artifact;
}

export function listTasks(data, state) {
  const needle = (state.search ?? '').trim().toLocaleLowerCase();
  return data.tasks.filter(task => task.role === state.role)
    .filter(task => state.statusFilter === 'all' || task.status === state.statusFilter)
    .filter(task => !needle || [task.title.zh, task.title.en, task.goal.zh, task.goal.en, ...task.symbols, ...task.companyIds].join(' ').toLocaleLowerCase().includes(needle));
}

function chooseTask(state, taskId, data) {
  const task = getTask(data, taskId);
  const rememberedRun = state.runSelections[task.id];
  const runs = listRuns(data, task.id, state);
  const runId = rememberedRun ?? runs.at(-1)?.id;
  getRun(data, task.id, runId, state);
  return { ...state, ...(state.role !== task.role ? { search: '', statusFilter: 'all' } : {}),
    role: task.role, taskId, runId, view: 'tasks', tab: 'result', artifactId: null, settingsRoleId: null,
    taskSelections: { ...state.taskSelections, [task.role]: taskId },
    runSelections: { ...state.runSelections, [taskId]: runId } };
}

export function createState(data) {
  if (!data || !Array.isArray(data.roles) || !Array.isArray(data.tasks) || !data.roles.length) throw new Error('An explicit demo dataset is required');
  const initialTask = getTask(data, data.initialTaskId);
  if (!data.roles.some(role => role.id === initialTask.role)) throw new Error('Initial task has an unknown role');
  return chooseTask({ role: initialTask.role, taskId: null, runId: null, tab: 'result', view: 'tasks',
    search: '', statusFilter: 'all', lang: 'zh', artifactId: null, notes: {}, reviewHistory: [], reviewDrafts: {},
    followups: [], drafts: {}, pendingRuns: [], taskSelections: {}, runSelections: {}, nextInstruction: 1 }, initialTask.id, data);
}

export function reduce(state, action, data) {
  if (!action || typeof action.type !== 'string') throw new Error('An explicit action is required');
  switch (action.type) {
    case 'selectRole': {
      if (!data.roles.some(role => role.id === action.role)) throw new Error(`Unknown role: ${String(action.role)}`);
      if (state.role === action.role && state.view === 'tasks') return { ...state, settingsRoleId: null };
      const clean = { ...state, role: action.role, taskId: null, runId: null, artifactId: null, settingsRoleId: null, search: '', statusFilter: 'all', view: 'tasks', tab: 'result' };
      const rememberedTask = state.taskSelections[action.role];
      return rememberedTask ? chooseTask(clean, rememberedTask, data) : clean;
    }
    case 'selectTask': return chooseTask(state, action.taskId, data);
    case 'selectRun': {
      getRun(data, state.taskId, action.runId, state);
      return { ...state, runId: action.runId, artifactId: null, settingsRoleId: null,
        runSelections: { ...state.runSelections, [state.taskId]: action.runId } };
    }
    case 'setTab': return { ...state, tab: enumValue(action.tab, ['result', 'process', 'review'], 'tab') };
    case 'setView': return { ...state, view: enumValue(action.view, ['tasks', 'experiments'], 'view'), artifactId: null, settingsRoleId: null };
    case 'setLanguage': return { ...state, lang: enumValue(action.lang, ['zh', 'en'], 'language') };
    case 'setFilter': return { ...state, statusFilter: enumValue(action.statusFilter, ['all', 'review', 'gap', 'complete'], 'status filter') };
    case 'setSearch': {
      if (typeof action.search !== 'string') throw new Error('Search must be text');
      return { ...state, search: action.search };
    }
    case 'openArtifact': {
      const artifact = getArtifact(data, action.artifactId);
      const explicitScope = action.taskId !== undefined || action.runId !== undefined;
      if (explicitScope && (action.taskId !== artifact.taskId || action.runId !== artifact.runId)) throw new Error('Artifact scope does not match the explicit task and run');
      if (state.view === 'experiments') {
        if (!explicitScope) throw new Error('An experiment artifact requires explicit taskId and runId');
        const task = getTask(data, artifact.taskId);
        return { ...state, taskId: artifact.taskId, runId: artifact.runId, role: task.role, artifactId: artifact.id, settingsRoleId: null,
          taskSelections: { ...state.taskSelections, [task.role]: task.id },
          runSelections: { ...state.runSelections, [task.id]: artifact.runId } };
      }
      if (artifact.taskId !== state.taskId || artifact.runId !== state.runId) throw new Error('Artifact does not belong to the selected task and run');
      return { ...state, artifactId: artifact.id, settingsRoleId: null };
    }
    case 'openAgentSettings': {
      if (!data.roles.some(role => role.id === action.role)) throw new Error(`Unknown role: ${String(action.role)}`);
      return { ...state, settingsRoleId: action.role };
    }
    case 'closeAgentSettings': return { ...state, settingsRoleId: null };
    case 'closeArtifact': return { ...state, artifactId: null };
    case 'setDraft': {
      getRun(data, state.taskId, state.runId, state);
      checkedText(action.text, 'Draft');
      return { ...state, drafts: { ...state.drafts, [draftKey(state.taskId, state.runId)]: action.text } };
    }
    case 'setReviewDraft': {
      const task = getTask(data, state.taskId);
      const run = getRun(data, task.id, state.runId, state);
      if (run.status === 'pending') throw new Error('A pending demo run has no output to review');
      if (!task.criteria.some(criterion => criterion.id === action.criterionId)) throw new Error('Review criterion does not belong to the selected task');
      const hasNote = Object.hasOwn(action, 'note');
      const hasVerdict = Object.hasOwn(action, 'verdict');
      if (!hasNote && !hasVerdict) throw new Error('A review draft update requires a note or verdict');
      if (hasNote) checkedText(action.note, 'Review note');
      if (hasVerdict) enumValue(action.verdict, ['', 'supported', 'insufficient', 'incorrect'], 'review verdict');
      const key = reviewKey(task.id, run.id, action.criterionId);
      const base = state.reviewDrafts[key] ?? state.notes[key] ?? {
        taskId: task.id, runId: run.id, criterionId: action.criterionId, verdict: '', note: '',
      };
      return { ...state, reviewDrafts: { ...state.reviewDrafts, [key]: {
        ...base, ...(hasNote ? { note: action.note } : {}), ...(hasVerdict ? { verdict: action.verdict } : {}),
      } } };
    }
    case 'saveReview': {
      const task = getTask(data, state.taskId);
      const run = getRun(data, task.id, state.runId, state);
      if (run.status === 'pending') throw new Error('A pending demo run has no output to review');
      if (!task.criteria.some(criterion => criterion.id === action.criterionId)) throw new Error('Review criterion does not belong to the selected task');
      enumValue(action.verdict, ['supported', 'insufficient', 'incorrect'], 'review verdict');
      checkedText(action.note, 'Review note', true);
      const note = { taskId: task.id, runId: run.id, criterionId: action.criterionId, verdict: action.verdict, note: action.note.trim() };
      const key = reviewKey(task.id, run.id, action.criterionId);
      const reviewDrafts = { ...state.reviewDrafts };
      delete reviewDrafts[key];
      return { ...state, notes: { ...state.notes, [key]: note }, reviewHistory: [...state.reviewHistory, note], reviewDrafts };
    }
    case 'appendInstruction': {
      const task = getTask(data, state.taskId);
      const base = getRun(data, task.id, state.runId, state);
      const text = checkedText(action.text, 'Instruction', true).trim();
      const newRunId = `${task.id}-demo-request-${state.nextInstruction}`;
      if (listRuns(data, task.id, state).some(run => run.id === newRunId)) throw new Error('Duplicate demo run identity');
      const pendingRun = { id: newRunId, taskId: task.id, baseRunId: base.id,
        label: localized(`追加请求 ${state.nextInstruction} · 未执行`, `Follow-up ${state.nextInstruction} · not executed`),
        model: base.model, version: base.version, status: 'pending', instruction: text,
        summary: localized('追加要求仅保存在本页演示状态；尚未发送给 Agent，也没有生成回复或新产物。', 'The request exists only in this page’s demo state. It has not been sent to an Agent; no response or output has been generated.'),
        steps: [], artifactIds: [] };
      const followup = { id: `instruction-${state.nextInstruction}`, taskId: task.id, runId: base.id, newRunId, text, status: 'pending' };
      return { ...state, runId: newRunId, artifactId: null, settingsRoleId: null, tab: 'process',
        nextInstruction: state.nextInstruction + 1,
        pendingRuns: [...state.pendingRuns, pendingRun], followups: [...state.followups, followup],
        drafts: { ...state.drafts, [draftKey(task.id, base.id)]: '' },
        runSelections: { ...state.runSelections, [task.id]: newRunId } };
    }
    default: throw new Error(`Unknown action: ${action.type}`);
  }
}
