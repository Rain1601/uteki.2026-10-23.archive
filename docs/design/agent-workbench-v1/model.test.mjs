import test from 'node:test';
import assert from 'node:assert/strict';
import { DEMO } from './demo-data.mjs';
import { createState, reduce, getTask, getRun, getArtifact, listTasks, listRuns, reviewKey, draftKey } from './model.mjs';

const dispatch = (state, type, fields = {}) => reduce(state, { type, ...fields }, DEMO);
function frozen(value, seen = new WeakSet()) {
  if (value && typeof value === 'object' && !seen.has(value)) {
    seen.add(value);
    Object.values(value).forEach(child => frozen(child, seen));
    Object.freeze(value);
  }
  return value;
}
frozen(DEMO);

test('the explicit fixture contains two companies, both agent roles and valid scoped artifact links', () => {
  assert.equal(DEMO.roles.length, 2);
  assert.ok(DEMO.tasks.some(task => task.companyIds.length === 2));
  assert.equal(new Set(DEMO.tasks.map(task => task.id)).size, DEMO.tasks.length);
  assert.equal(new Set(DEMO.artifacts.map(item => item.id)).size, DEMO.artifacts.length);
  for (const task of DEMO.tasks) {
    assert.ok(task.companyIds.length > 0);
    assert.ok(DEMO.roles.some(role => role.id === task.role));
    for (const run of task.runs) {
      for (const artifactId of run.artifactIds) {
        const item = getArtifact(DEMO, artifactId);
        assert.equal(item.taskId, task.id);
        assert.equal(item.runId, run.id);
        assert.match(item.scopeLabel.en, /synthetic/i);
      }
      for (const step of run.steps) {
        for (const artifactId of step.artifactIds) assert.ok(run.artifactIds.includes(artifactId));
      }
    }
    for (const related of task.relatedTaskIds) getTask(DEMO, related);
  }
});

test('initial selection comes only from the explicit named demo entry', () => {
  const state = createState(DEMO);
  assert.equal(state.taskId, DEMO.initialTaskId);
  assert.equal(state.runId, 'googl-cashflow-r2');
  assert.equal(state.lang, 'zh');
  assert.throws(() => createState({ ...DEMO, initialTaskId: '' }), /required/);
  assert.throws(() => createState({ ...DEMO, initialTaskId: 'missing' }), /Unknown task/);
});

test('a new role has no implicit task selection, and explicitly visited tasks can be restored', () => {
  const first = createState(DEMO);
  const analysis = dispatch(first, 'selectRole', { role: 'analysis' });
  assert.equal(analysis.taskId, null);
  assert.equal(analysis.runId, null);
  assert.equal(listTasks(DEMO, analysis).length, 2);
  const selected = dispatch(analysis, 'selectTask', { taskId: 'analysis-msft-research' });
  const data = dispatch(selected, 'selectRole', { role: 'data' });
  assert.equal(data.taskId, first.taskId);
  assert.equal(dispatch(data, 'selectRole', { role: 'analysis' }).taskId, 'analysis-msft-research');
});

test('unknown task, role, run and artifact scope is rejected without substitution', () => {
  const state = createState(DEMO);
  assert.throws(() => getTask(DEMO, ' '), /required/);
  assert.throws(() => dispatch(state, 'selectRole', { role: 'unknown' }), /Unknown role/);
  assert.throws(() => dispatch(state, 'selectTask', { taskId: 'missing' }), /Unknown task/);
  assert.throws(() => dispatch(state, 'selectRun', { runId: 'msft-report-r1' }), /does not belong/);
  assert.throws(() => dispatch(state, 'openArtifact', { artifactId: 'msft-blocks' }), /does not belong/);
  assert.throws(() => dispatch(state, 'openArtifact', { artifactId: 'googl-record-v1' }), /does not belong/);
  assert.throws(() => getArtifact(DEMO, 'missing'), /Unknown artifact/);
});

test('changing task or run clears the old artifact and cannot leak evidence', () => {
  const state = dispatch(createState(DEMO), 'openArtifact', { artifactId: 'googl-record-v2' });
  assert.equal(state.artifactId, 'googl-record-v2');
  const earlier = dispatch(state, 'selectRun', { runId: 'googl-cashflow-r1' });
  assert.equal(earlier.artifactId, null);
  const msft = dispatch(state, 'selectTask', { taskId: 'data-msft-report' });
  assert.equal(msft.artifactId, null);
  assert.equal(msft.runId, 'msft-report-r1');
});

test('experiment artifact navigation requires explicit scope and preserves the comparison view', () => {
  const state = dispatch(createState(DEMO), 'setView', { view: 'experiments' });
  assert.throws(() => dispatch(state, 'openArtifact', { artifactId: 'googl-record-v1' }), /requires explicit/);
  assert.throws(() => dispatch(state, 'openArtifact', { artifactId: 'googl-record-v1', taskId: 'data-msft-report', runId: 'googl-cashflow-r1' }), /does not match/);
  const selected = dispatch(state, 'openArtifact', { artifactId: 'googl-record-v1', taskId: 'data-googl-cashflow', runId: 'googl-cashflow-r1' });
  assert.equal(selected.view, 'experiments');
  assert.equal(selected.runId, 'googl-cashflow-r1');
  assert.equal(selected.artifactId, 'googl-record-v1');
  for (const sample of DEMO.experiment.cases) {
    for (const result of sample.results) {
      assert.equal(getArtifact(DEMO, result.artifactId).taskId, sample.taskId);
      assert.ok(DEMO.experiment.configurations.some(config => config.id === result.configurationId));
    }
  }
});

test('explicit artifact scope cannot bypass task-view isolation', () => {
  const state = createState(DEMO);
  assert.throws(() => dispatch(state, 'openArtifact', { artifactId: 'msft-blocks', taskId: 'data-msft-report', runId: 'msft-report-r1' }), /does not belong/);
});

test('review notes bind task, run and criterion and never create instructions', () => {
  const state = createState(DEMO);
  const reviewed = dispatch(state, 'saveReview', { criterionId: 'evidence', verdict: 'insufficient', note: '需要核对单位' });
  const key = reviewKey(state.taskId, state.runId, 'evidence');
  assert.deepEqual(reviewed.notes[key], { taskId: state.taskId, runId: state.runId, criterionId: 'evidence', verdict: 'insufficient', note: '需要核对单位' });
  assert.equal(reviewed.followups.length, 0);
  assert.equal(reviewed.pendingRuns.length, 0);
  const other = dispatch(reviewed, 'selectTask', { taskId: 'data-msft-report' });
  assert.equal(other.notes[reviewKey(other.taskId, other.runId, 'evidence')], undefined);
  assert.throws(() => dispatch(state, 'saveReview', { criterionId: 'unregistered', verdict: 'supported', note: '' }), /criterion/);
});

test('revising a review retains its earlier entry and does not mutate previous state', () => {
  const first = dispatch(createState(DEMO), 'saveReview', { criterionId: 'evidence', verdict: 'insufficient', note: 'First review' });
  frozen(first);
  const second = dispatch(first, 'saveReview', { criterionId: 'evidence', verdict: 'supported', note: 'Rechecked the sample' });
  assert.equal(first.reviewHistory.length, 1);
  assert.equal(second.reviewHistory.length, 2);
  assert.equal(second.reviewHistory[0].verdict, 'insufficient');
  assert.equal(second.notes[reviewKey(first.taskId, first.runId, 'evidence')].verdict, 'supported');
});

test('an appended instruction creates only a pending demo request, with no generated output', () => {
  const initial = createState(DEMO);
  const withDraft = dispatch(initial, 'setDraft', { text: '请补充单位核验' });
  frozen(withDraft);
  const fixtureBefore = JSON.stringify(DEMO);
  const appended = dispatch(withDraft, 'appendInstruction', { text: ' 请补充单位核验 ' });
  const run = getRun(DEMO, appended.taskId, appended.runId, appended);
  assert.equal(run.status, 'pending');
  assert.equal(run.baseRunId, initial.runId);
  assert.equal(run.instruction, '请补充单位核验');
  assert.deepEqual(run.steps, []);
  assert.deepEqual(run.artifactIds, []);
  assert.equal(appended.followups[0].runId, initial.runId);
  assert.equal(appended.notes[reviewKey(initial.taskId, initial.runId, 'evidence')], undefined);
  assert.equal(appended.drafts[draftKey(initial.taskId, initial.runId)], '');
  assert.equal(listRuns(DEMO, initial.taskId, appended).length, 3);
  assert.equal(listRuns(DEMO, 'data-msft-report', appended).length, 1);
  assert.equal(JSON.stringify(DEMO), fixtureBefore);
  assert.equal(withDraft.pendingRuns.length, 0);
  assert.equal(getRun(DEMO, initial.taskId, initial.runId).status, 'review');
  assert.throws(() => dispatch(appended, 'saveReview', { criterionId: 'evidence', verdict: 'supported', note: 'no output' }), /no output to review/);
  assert.throws(() => dispatch(initial, 'appendInstruction', { text: '  ' }), /required/);
});

test('instruction and draft scope survives task switches without cross-company mixing', () => {
  let state = dispatch(createState(DEMO), 'setDraft', { text: 'GOOGL question' });
  const googlDraftKey = draftKey(state.taskId, state.runId);
  state = dispatch(state, 'selectTask', { taskId: 'data-msft-report' });
  assert.equal(state.drafts[draftKey(state.taskId, state.runId)], undefined);
  state = dispatch(state, 'appendInstruction', { text: 'MSFT image question' });
  assert.equal(state.followups[0].taskId, 'data-msft-report');
  assert.equal(state.drafts[googlDraftKey], 'GOOGL question');
  state = dispatch(state, 'selectTask', { taskId: 'data-googl-cashflow' });
  assert.equal(state.runId, 'googl-cashflow-r2');
  assert.equal(state.drafts[draftKey(state.taskId, state.runId)], 'GOOGL question');
});

test('search and status filtering keep the selected role and support both languages and symbols', () => {
  let state = dispatch(createState(DEMO), 'setSearch', { search: 'MSFT' });
  assert.deepEqual(listTasks(DEMO, state).map(task => task.id), ['data-msft-report', 'data-cross-company']);
  state = dispatch(state, 'setFilter', { statusFilter: 'gap' });
  assert.deepEqual(listTasks(DEMO, state).map(task => task.id), ['data-msft-report']);
  state = dispatch(state, 'setSearch', { search: '不存在的公司' });
  assert.deepEqual(listTasks(DEMO, state), []);
  assert.throws(() => dispatch(state, 'setLanguage', { lang: 'unknown' }), /Unsupported/);
  assert.throws(() => dispatch(state, 'setTab', { tab: 'hidden' }), /Unsupported/);
  assert.throws(() => dispatch(state, 'unsupported'), /Unknown action/);
});

test('review drafts retain partial edits by task, run and criterion without saving a review', () => {
  let state = createState(DEMO);
  const key = reviewKey(state.taskId, state.runId, 'evidence');
  state = dispatch(state, 'setReviewDraft', { criterionId: 'evidence', note: 'Unfinished inspection' });
  assert.equal(state.reviewDrafts[key].verdict, '');
  assert.equal(state.notes[key], undefined);
  assert.equal(state.reviewHistory.length, 0);
  state = dispatch(state, 'setReviewDraft', { criterionId: 'evidence', verdict: 'insufficient' });
  assert.equal(state.reviewDrafts[key].note, 'Unfinished inspection');
  assert.equal(dispatch(state, 'setReviewDraft', { criterionId: 'evidence', verdict: '' }).reviewDrafts[key].verdict, '');
  assert.throws(() => dispatch(state, 'saveReview', { criterionId: 'evidence', verdict: '', note: 'No verdict chosen' }), /Unsupported/);
  const earlier = dispatch(state, 'selectRun', { runId: 'googl-cashflow-r1' });
  assert.equal(earlier.reviewDrafts[reviewKey(earlier.taskId, earlier.runId, 'evidence')], undefined);
  const other = dispatch(state, 'selectTask', { taskId: 'data-msft-report' });
  assert.equal(other.reviewDrafts[reviewKey(other.taskId, other.runId, 'evidence')], undefined);
  assert.equal(other.reviewDrafts[key].verdict, 'insufficient');
  frozen(state);
  const saved = dispatch(state, 'saveReview', { criterionId: 'evidence', verdict: 'insufficient', note: '  Source unit is missing  ' });
  assert.equal(saved.reviewDrafts[key], undefined);
  assert.equal(state.reviewDrafts[key].note, 'Unfinished inspection');
  assert.equal(saved.notes[key].note, 'Source unit is missing');
  const revised = dispatch(saved, 'setReviewDraft', { criterionId: 'evidence', note: 'Continue reviewing' });
  assert.equal(revised.reviewDrafts[key].verdict, 'insufficient');
  assert.equal(revised.notes[key].note, 'Source unit is missing');
  assert.throws(() => dispatch(state, 'setReviewDraft', { criterionId: 'wrong', note: 'x' }), /criterion/);
  assert.throws(() => dispatch(state, 'setReviewDraft', { criterionId: 'evidence' }), /requires/);
  const pending = dispatch(state, 'appendInstruction', { text: 'Check again' });
  assert.throws(() => dispatch(pending, 'setReviewDraft', { criterionId: 'evidence', note: 'x' }), /no output to review/);
});

test('review and instruction text enforce meaningful blank and length boundaries', () => {
  const state = createState(DEMO);
  for (const text of ['', '   ', '\n\t']) {
    assert.throws(() => dispatch(state, 'saveReview', { criterionId: 'evidence', verdict: 'supported', note: text }), /required/);
    assert.throws(() => dispatch(state, 'appendInstruction', { text }), /required/);
  }
  const tooLong = 'x'.repeat(4001);
  assert.throws(() => dispatch(state, 'setDraft', { text: tooLong }), /4000/);
  assert.throws(() => dispatch(state, 'appendInstruction', { text: tooLong }), /4000/);
  assert.throws(() => dispatch(state, 'saveReview', { criterionId: 'evidence', verdict: 'supported', note: tooLong }), /4000/);
  assert.throws(() => dispatch(state, 'setReviewDraft', { criterionId: 'evidence', note: tooLong }), /4000/);
  const boundary = 'x'.repeat(4000);
  assert.equal(dispatch(state, 'setDraft', { text: boundary }).drafts[draftKey(state.taskId, state.runId)], boundary);
  assert.equal(dispatch(state, 'appendInstruction', { text: boundary }).followups[0].text, boundary);
  assert.equal(dispatch(state, 'saveReview', { criterionId: 'evidence', verdict: 'supported', note: boundary }).reviewHistory[0].note, boundary);
  assert.equal(dispatch(state, 'setReviewDraft', { criterionId: 'evidence', note: boundary }).reviewDrafts[reviewKey(state.taskId, state.runId, 'evidence')].note, boundary);
  assert.equal(dispatch(state, 'setDraft', { text: '' }).drafts[draftKey(state.taskId, state.runId)], '');
});

test('cross-role task navigation clears stale filters while same-role navigation retains them', () => {
  let state = dispatch(createState(DEMO), 'setSearch', { search: 'cashflow' });
  state = dispatch(state, 'setFilter', { statusFilter: 'gap' });
  const sameRole = dispatch(state, 'selectTask', { taskId: 'data-msft-report' });
  assert.equal(sameRole.search, 'cashflow');
  assert.equal(sameRole.statusFilter, 'gap');
  const crossRole = dispatch(state, 'selectTask', { taskId: 'analysis-msft-research' });
  assert.equal(crossRole.search, '');
  assert.equal(crossRole.statusFilter, 'all');
  assert.ok(listTasks(DEMO, crossRole).some(task => task.id === crossRole.taskId));
});
