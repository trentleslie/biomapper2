export const meta = {
  name: 'brainstorm-pipeline',
  description: 'Deterministic back half: work -> validate -> wiki? -> PR -> compound',
  phases: [
    { title: 'Work' }, { title: 'Validate' }, { title: 'Publish' },
    { title: 'PR' }, { title: 'Greptile' }, { title: 'Compound' },
  ],
}
// --- inlined from lib.mjs (sandbox has no imports; keep in sync) ---
function pickTailStages(workType) {
  const base = ['validate'];
  return workType === 'research' ? [...base,'wiki','pr','compound'] : [...base,'pr','compound'];
}
function tallyRefuters(verdicts) {
  const refute = verdicts.filter(v => v && v.refuted).length;
  return { refute, blocked: refute >= 2 };
}
function nextRoundAction(round, blocked) {
  if (!blocked) return 'proceed';
  return round >= 3 ? 'halt' : 'fix';
}
function parseGreptileScore(body) {
  if (typeof body !== 'string') return null;
  const m = body.match(/confidence score[:\s]*([0-5])\s*\/\s*5/i);
  return m ? Number(m[1]) : null;
}
function greptileDone({ score, unaddressed }) {
  return score === 5 || unaddressed === 0;
}
function nextGreptileAction(round, done, maxRounds) {
  if (done) return 'done';
  return round >= maxRounds ? 'stop' : 'address';
}
function pickWorkStage(workType, researchMode) {
  return workType === 'research' && researchMode === 'review' ? 'systematic-review' : 'ce-work';
}
// -------------------------------------------------------------------
const planPath = '/home/trentleslie/projects/biomapper2/docs/plans/evidence-base-plan.md';
const artifactPath = '/home/trentleslie/projects/biomapper2/docs/plans/evidence-base-brainstorm.md';
const workType = 'software';
const repoDir = '/home/trentleslie/projects/biomapper2';
const researchMode = 'analysis';
const stages = pickTailStages(workType);
log(`work-type=${workType}${researchMode ? '/' + researchMode : ''}; tail stages=${stages.join(' -> ')}`);

phase('Work');
let workResult;
if (pickWorkStage(workType, researchMode) === 'systematic-review') {
  const review = await agent(
    `Run a systematic review for this task. Read the "## Review protocol" section of the ` +
    `approved plan at ${planPath} (researchQuestion, searches, screening criteria, extraction ` +
    `questions). Use ToolSearch to load the Elicit MCP. Call create_systematic_review with the ` +
    `protocol's searches, abstractScreening.criteria and extraction.questions passed explicitly, ` +
    `plus generate:true on screening and extraction to fill gaps, and generateReport:true. Then ` +
    `poll get_systematic_review until status is terminal — cap yourself at ~20 polls; if status ` +
    `is pausedForInsufficientQuota call resume_systematic_review and keep polling. On completion ` +
    `call get_systematic_review(includeReportBody:true). Write the FULL extraction table (all ` +
    `rows, untruncated) as JSON to an absolute file path under /tmp and return that path as ` +
    `extractionPath. Return {reviewId, status, reportBody, extractionPath, papersScreened}; ` +
    `set status 'completed' only if the review actually finished.`,
    { label: 'systematic-review', phase: 'Work',
      schema: { type:'object', required:['status'],
        properties:{ reviewId:{type:'string'}, status:{type:'string'}, reportBody:{type:'string'},
          extractionPath:{type:'string'}, papersScreened:{type:'number'} } } });

  if (!review || review.status !== 'completed' || !review.reportBody) {
    return { status: 'halted', where: 'work', reason: 'systematic review did not complete', review };
  }

  workResult = await agent(
    `Write the research wiki draft for this systematic review, in repo ${repoDir}, working in an ` +
    `isolated git worktree. Ground every claim and number STRICTLY in the review's extraction ` +
    `table (cite the screened paper for each; introduce nothing beyond the evidence). Read the ` +
    `FULL extraction table from the file at ${review.extractionPath} (JSON) — it is the ` +
    `ground-truth evidence; do not rely on any summary of it. Review report for ` +
    `structure/context only: ${JSON.stringify(review.reportBody).slice(0, 8000)}. Write the draft ` +
    `in the Phenome wiki house style. Commit the reproducible artifacts to a branch: the review protocol, ` +
    `the extraction table (JSON or CSV), and the draft. Return {branch, wikiDraftPath, filesChanged, testsPassing:true}.`,
    { label: 'review-writeup', phase: 'Work', 
      schema: { type:'object', required:['branch','testsPassing','wikiDraftPath'],
        properties:{ branch:{type:'string'}, wikiDraftPath:{type:'string'},
          filesChanged:{type:'array',items:{type:'string'}}, testsPassing:{type:'boolean'} } } });
} else {
  workResult = await agent(
    `**PART I OF THIS PLAN IS ALREADY IMPLEMENTED. DO NOT RE-IMPLEMENT IT.** The work is complete and `+
    `committed on branch **feat/evidence-base-stats-v2** at commit **945f00c**, checked out in the `+
    `worktree **/home/trentleslie/worktrees/bm2-eb2** (repo ${repoDir}). Note there is an OLDER, ABANDONED `+
    `branch named 'feat/evidence-base-stats' (no -v2 suffix) and a git-corrupt worktree at `+
    `~/worktrees/bm2-evidence-base — IGNORE BOTH; they are not the work. `+
    `Your job is to VERIFY and REPORT, not to build. Specifically: (1) cd to the bm2-eb2 worktree and `+
    `confirm HEAD is 945f00c and the tree is clean; (2) run the test suite there and record the result — `+
    `export PYTHONPATH=/home/trentleslie/worktrees/bm2-eb2/src FIRST, or pytest will silently test the `+
    `main checkout instead of this worktree; the expected result is ~1234 passed / 0 failed; (3) read the `+
    `'Part I acceptance' list in the approved plan at ${planPath} (Part I begins around line 72; it has 9 `+
    `offline-verifiable items) and report which items the committed code satisfies and which, if any, it `+
    `does not. `+
    `NEVER make a live call to kestrel.krakenkg.com, Metabolomics Workbench, PubChem, MetaNetX or any `+
    `bulk-download host. Everything under the heading '⛔ PART II — GATED: LIVE COMPUTE AGAINST A SHARED `+
    `PUBLIC SERVICE ⛔' (around line 401) is OUT OF SCOPE and must NOT be executed; the bisect machinery `+
    `ships behind a DEFAULT-OFF flag and must not be exercised live. `+
    `If tests do not pass or an acceptance item is genuinely unmet, make the MINIMAL fix on that branch `+
    `(test-first) rather than rebuilding, and say what you changed. `+
    `Return {branch:"feat/evidence-base-stats-v2", filesChanged, testsPassing:boolean, acceptanceUnmet:[strings]}.`,
    { label: 'ce-work', phase: 'Work',
      schema: { type:'object', required:['branch','testsPassing'],
        properties:{ branch:{type:'string'}, filesChanged:{type:'array',items:{type:'string'}},
          testsPassing:{type:'boolean'}, acceptanceUnmet:{type:'array',items:{type:'string'}},
          wikiDraftPath:{type:'string'} } } });
}
if (!workResult || !workResult.testsPassing) {
  return { status: 'halted', where: 'work', reason: 'implementation did not reach passing tests', workResult };
}

phase('Validate');
let validation = { passed: true, unresolved: [] };
if (workType === 'research') {
  const claims = await agent(
    `Extract checkable claims from ${workResult.wikiDraftPath} following ` +
    `references/refuter-lenses.md 'Claim extraction'. Return JSON array of ` +
    `{id,text,number,unit,cited_source}.`,
    { label: 'extract-claims', phase: 'Validate',
      schema: { type:'array', items:{ type:'object', required:['id','text'] } } }) || [];

  if (claims.length === 0) {
    return { status: 'halted', where: 'validation', workType, unresolved: [], workResult,
      message: 'No checkable claims extracted from the research draft; refusing to publish unvalidated.' };
  }

  // Discovery on-ramp: enrich the control-set index from the AWS Registry of Open
  // Data (RODA) before refuting, so later runs inherit any datasets this one resolves.
  await agent(
    `You are resolving control sets for research-claim validation. Read ` +
    `datasets.index.json — the pipeline's catalog of concrete control-set sources ` +
    `(each entry: {name, description, api_endpoint, access_method, provenance, last_updated}). ` +
    `For these claims, judge whether the index already holds a source able to check them: ` +
    `${JSON.stringify(claims.map(c => ({ id: c.id, text: c.text, unit: c.unit })))}. ` +
    `For any claim whose domain has no suitable existing source, use ToolSearch to load the ` +
    `Registry of Open Data on AWS (RODA) MCP tools (server 'roda': search_datasets, then ` +
    `get_dataset_details for the S3 bucket ARN), search RODA for a relevant open ` +
    `life-sciences/biomedical dataset, and APPEND one concrete entry per genuinely-relevant ` +
    `dataset to datasets.index.json: api_endpoint = the dataset's S3 URI/bucket ARN or landing ` +
    `page, access_method = e.g. "S3" or "HTTP", provenance = "AWS Registry of Open Data: ` +
    `<dataset owner>", last_updated = today's date. RODA's coverage is strong for ` +
    `genomics/large reference datasets and weak for metabolomics — do not force an off-topic ` +
    `hit; leave the claim in coverageGaps if RODA has nothing genuinely relevant. Each appended ` +
    `entry must have all six string fields. Never invent a dataset RODA did not return, never add ` +
    `catalog entries unrelated to a claim, and if the index already covers the claims change nothing. ` +
    `Validate-before-persist: after writing, run \`node validate-index.mjs\` from this directory; ` +
    `if it exits non-zero, remove the entr(y/ies) you just added and re-run until it passes, so a ` +
    `malformed append never persists. Report indexValid:true only once the guard passes. ` +
    `Return {added:[names], coverageGaps:[claimIds still without a source], indexValid:boolean}.`,
    { label: 'resolve-control-sets', phase: 'Validate',
      schema: { type:'object', required:['indexValid'],
        properties:{ added:{type:'array',items:{type:'string'}},
          coverageGaps:{type:'array',items:{type:'string'}}, indexValid:{type:'boolean'} } } });

  for (let round = 1; round <= 3; round++) {
    const judged = await parallel(claims.map(c => () =>
      parallel(['source-fidelity','unit/magnitude','control-set concordance'].map(lens => () =>
        agent(`Refute claim via the ${lens} lens per references/refuter-lenses.md. ` +
              `Claim: ${JSON.stringify(c)}. Control source: read datasets.index.json. ` +
              `Return {refuted:boolean, reason:string, controlSetFailure:boolean}.`,
          { label: `refute:${lens}:${c.id}`, phase: 'Validate',
            schema: { type:'object', required:['refuted','reason'],
              properties:{ refuted:{type:'boolean'}, reason:{type:'string'},
                controlSetFailure:{type:'boolean'} } } })))
        .then(vs => {
          const verdicts = vs.filter(Boolean);
          const t = tallyRefuters(verdicts);
          const controlFail = verdicts.some(v => v.controlSetFailure);
          return { claim: c, blocked: t.blocked || controlFail, verdicts };
        })));

    const bad = judged.filter(Boolean).filter(j => j.blocked);
    if (bad.length === 0) { validation = { passed: true, unresolved: [] }; break; }

    const action = nextRoundAction(round, true);
    log(`validation round ${round}: ${bad.length} blocked claim(s) -> ${action}`);
    if (action === 'halt') { validation = { passed: false, unresolved: bad }; break; }

    const fixPayload = JSON.stringify(bad.map(b => ({ id: b.claim.id, reasons: b.verdicts.map(v => v.reason) })));
    await agent(`Fix these blocked claims in ${workResult.wikiDraftPath} and the underlying analysis: ${fixPayload}. Do not fabricate; correct or remove.`,
      { label: `fix-round-${round}`, phase: 'Validate' });
  }
} else {
  const review = await agent(
    `ROUND 5 re-review at HEAD e048e95. Run the ce-review skill on branch ${workResult.branch}. ` +
    `ROUND 4 found three more report-agreement-without-comparing paths plus a control of mine ` +
    `that asserted column HEADERS rather than cell VALUES (so restoring the original defect left ` +
    `it green). Fixed at e048e95: field resolution hoisted into _resolve_targets and shared by ` +
    `BOTH value shapes with an unreadable-field sentinel; n-less and k-less claims made ` +
    `symmetric; the rendered-table controls now assert cell values and positions, with a ` +
    `guard-the-guard test proving the two p columns differ on the fixture. Five mutations each ` +
    `redden a distinct control. THIS IS THE FIFTH ROUND and each has found a real defect of the ` +
    `same shape one level deeper, so weight your effort toward: (a) any REMAINING path in ` +
    `reconcile_section3 or confidence_report that can report agreement, resolution or ` +
    `publishability without comparing anything; (b) controls that pass for the wrong reason -- ` +
    `satisfied by an earlier branch, by a fixture coincidence, or asserting a label/shape where ` +
    `the defect is a value; (c) whether _resolve_targets' field whitelist can be desynchronised ` +
    `from the fields claims actually use. If you find NOTHING blocking, say so plainly and ` +
    `report blockingFindings 0 -- do not manufacture a finding to continue the pattern.` +

    `ROUND 3 verified all eight round-2 controls genuinely fail under ten mutations, then found ` +
    `_has_drifted still had THREE silent-pass paths whose comments falsely claimed the rename ` +
    `check had reported them (it is top-level-key only and cannot see a coverage sub-key or ` +
    `present-but-None) -- and that one of the three was INTRODUCED by the round-2 numerator fix. ` +
    `All three now return True, matching the scalar branch. Seven controls added; restoring the ` +
    `silent passes reddens six, while the seventh (a correct k-bearing coverage claim) stays ` +
    `green so the parametrization is not merely asserting that everything fails. The k-bearing ` +
    `coverage path is unreachable through the live claim set, so it is pinned directly on ` +
    `_has_drifted rather than through reconcile(). HUNT FOR CONTROLS THAT PASS FOR THE WRONG ` +
    `REASON -- ones satisfied by an earlier branch, by a fixture coincidence, or that never ` +
    `reach the code they name. Check too whether any REMAINING path in this module can still ` +
    `report agreement without comparing anything. ` +

    `ROUND 2 confirmed all three round-1 blockers hold, then correctly blocked on the repair ` +
    `shipping with NO committed red-green pin while the commit message claimed a positive control. ` +
    `Fixed at 60b37ed: the reconciler controls (k-less coverage claim, full-set negative, ` +
    `unreadable field, coverage numerator), the rendered-table controls for the score p column and ` +
    `the coherence warning, a multi-chunk bisect-budget control, and a pin on the 46-id blocked ` +
    `claim set. Each was mutation-tested by reverting its fix and confirming the suite turns red. ` +
    `Also fixed the two P2s round 2 raised: the coverage NUMERATOR now resolves from coverage ` +
    `(n_predicted) instead of falling through to row['k'], and the bisect budget starts once per ` +
    `call rather than per failing chunk. CHECK THE CONTROLS THEMSELVES: confirm each genuinely ` +
    `fails when its fix is reverted and none passes for an incidental reason. ` +

    `**Work in the isolated worktree /home/trentleslie/worktrees/bm2-eb2**, NOT the shared checkout ` +
    `at ${repoDir} — that checkout is on a different branch with uncommitted changes and another ` +
    `job is active in it. Export PYTHONPATH=/home/trentleslie/worktrees/bm2-eb2/src before running ` +
    `pytest or you will silently test the wrong tree. Diff base is the merge-base with origin/dev. ` +
    `CONTEXT: round 1 raised three BLOCKING findings, all three now fixed at 066396e — (1) the ` +
    `Python 3.10 \`datetime.UTC\` crash in confidence_report.build_report, (2) \`_has_drifted\` in ` +
    `reconcile_section3 ignoring the claim's named \`field\` and skipping k-less claims entirely, ` +
    `(3) the paired-difference table printing the exact McNemar p beside the score-inverted ` +
    `interval. Verify each fix genuinely holds — in particular confirm the reconciler now FAILS on ` +
    `a claim whose denominator disagrees with the field it names, rather than merely reporting ok, ` +
    `and confirm no correct claim was turned into false drift. Round 1's P2/P3 findings are ` +
    `deliberately deferred to follow-ups; re-report them only if you judge one actually blocking. ` +
    `Return {blockingFindings: number, findings: string[]} where findings carries the FULL TEXT of every `+
    `blocking finding (file, line, defect, failure scenario, minimal fix) plus any advisory ones.`,
    { label: 'ce-review', phase: 'Validate',
      schema: { type:'object', required:['blockingFindings','findings'],
        properties:{ blockingFindings:{type:'number'},
                     findings:{ type:'array', items:{ type:'string' } } } } });
  validation = { passed: !!review && review.blockingFindings === 0,
    unresolved: review ? (review.findings || []) : ['ce-review returned no result'] };
}

if (!validation.passed) {
  return { status: 'halted', where: 'validation', workType,
    unresolved: validation.unresolved, workResult,
    message: 'Validation could not pass; nothing published or PR\'d.' };
}

let wikiUrl;
if (stages.includes('wiki')) {
  phase('Publish');
  const pub = await agent(
    `Publish ${workResult.wikiDraftPath} to the Phenome wiki using the ` +
    `publish-wiki skill. Return {wikiUrl}.`,
    { label: 'publish-wiki', phase: 'Publish',
      schema: { type:'object', properties:{ wikiUrl:{type:'string'} } } });
  wikiUrl = pub && pub.wikiUrl;
}

phase('PR');
const pr = await agent(
  `Open a PR for branch ${workResult.branch} in ${repoDir} using commit-push-pr. ` +
  `Do NOT merge. Return {prUrl, prNumber, repoFullName, defaultBranch, remote} where ` +
  `repoFullName is "owner/repo", remote is "github" or "gitlab", and defaultBranch is the ` +
  `repository's default branch (e.g. "main").`,
  { label: 'open-pr', phase: 'PR',
    schema: { type:'object', required:['prUrl','prNumber','repoFullName','defaultBranch','remote'],
      properties:{ prUrl:{type:'string'}, prNumber:{type:'number'}, repoFullName:{type:'string'},
        defaultBranch:{type:'string'}, remote:{type:'string', enum:['github','gitlab'] } } } });

phase('Greptile');
const MAX_GREPTILE_ROUNDS = 3;
let greptile;
let expectedSha;  // SHA the prior address round pushed; round 1 reviews whatever open-pr pushed
if (pr && pr.prNumber && (pr.remote === 'github' || pr.remote === 'gitlab')) {
  for (let round = 1; round <= MAX_GREPTILE_ROUNDS; round++) {
    const poll = await agent(
      `Ensure a Greptile code review is complete for PR #${pr.prNumber} on ` +
      `${pr.repoFullName} (remote ${pr.remote}, default branch ${pr.defaultBranch}). ` +
      (expectedSha
        ? `The review you read MUST cover commit ${expectedSha} (the latest push). If the ` +
          `most recent COMPLETED review predates that commit, it is stale — call ` +
          `trigger_code_review and wait for the fresh review before reading results. `
        : ``) +
      `If no review covers the latest commit, call trigger_code_review. Then poll ` +
      `list_code_reviews (filter by prNumber) until the latest review status is COMPLETED, ` +
      `FAILED, or SKIPPED — cap yourself at ~15 checks; if still pending, report ` +
      `reviewStatus 'PENDING'. On COMPLETED, call get_merge_request for the count of ` +
      `un-addressed Greptile comments, then take that latest review's codeReviewId from the ` +
      `list_code_reviews result and pass it to get_code_review for the summary body text. Return ` +
      `{reviewStatus, summaryBody, unaddressedCount, unaddressedComments:[{path,line,body}]}.`,
      { label: `greptile-poll-r${round}`, phase: 'Greptile',
        schema: { type:'object', required:['reviewStatus','unaddressedCount'],
          properties:{
            reviewStatus:{type:'string', enum:['COMPLETED','FAILED','SKIPPED','PENDING'] },
            summaryBody:{type:'string'},
            unaddressedCount:{type:'number'},
            unaddressedComments:{type:'array', items:{ type:'object',
              properties:{ path:{type:'string'}, line:{type:'number'}, body:{type:'string'} } } } } } });

    if (!poll || poll.reviewStatus !== 'COMPLETED') {
      greptile = { outcome: 'unavailable', rounds: round,
        reason: poll ? `review ${poll.reviewStatus}` : 'poll returned no result' };
      break;
    }

    const score = parseGreptileScore(poll.summaryBody);
    const done = greptileDone({ score, unaddressed: poll.unaddressedCount });
    const action = nextGreptileAction(round, done, MAX_GREPTILE_ROUNDS);
    log(`greptile round ${round}: score=${score}, unaddressed=${poll.unaddressedCount} -> ${action}`);

    if (action === 'done') {
      greptile = { outcome: score === 5 ? '5-of-5' : 'clean', score, rounds: round };
      break;
    }
    if (action === 'stop') {
      greptile = { outcome: 'exhausted', score, rounds: round,
        unresolved: poll.unaddressedComments || [] };
      break;
    }
    const addr = await agent(
      `On PR branch ${workResult.branch} in ${repoDir} (PR #${pr.prNumber}), address these ` +
      `unaddressed Greptile review comments: ${JSON.stringify(poll.unaddressedComments || [])}. ` +
      `Make the code changes, keep tests passing, commit, and push to the PR branch. Do NOT ` +
      `merge. Return {pushed, commitsAdded, headSha} where headSha is the full SHA of the ` +
      `commit you pushed (so the next review round can confirm it is not reading a stale review).`,
      { label: `greptile-address-r${round}`, phase: 'Greptile', 
        schema: { type:'object', required:['pushed'],
          properties:{ pushed:{type:'boolean'}, commitsAdded:{type:'number'}, headSha:{type:'string'} } } });
    expectedSha = addr && addr.headSha;
  }
} else {
  greptile = { outcome: 'unavailable',
    reason: pr ? `unsupported remote ${pr && pr.remote}` : 'no PR opened' };
}

phase('Compound');
await agent(
  `Document the learning from this run using the ce-compound skill ` +
  `(what was built, what validation caught). Reference PR ${pr && pr.prUrl}.`,
  { label: 'ce-compound', phase: 'Compound' });

return { status: 'done', prUrl: pr && pr.prUrl, wikiUrl, compound: true, workType, greptile };
