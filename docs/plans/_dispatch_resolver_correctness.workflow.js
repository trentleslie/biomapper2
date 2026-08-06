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
const planPath = '/home/trentleslie/projects/biomapper2/docs/plans/resolver-correctness-plan.md';
const artifactPath = '/home/trentleslie/projects/biomapper2/docs/plans/resolver-correctness-brainstorm.md';
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
    `Implement the approved plan at ${planPath} test-first, in repo ${repoDir}. ` +
    `Use the ce-work skill. Work in an isolated git worktree. Return a JSON summary ` +
    `{branch, filesChanged, testsPassing:boolean, wikiDraftPath?}.`,
    { label: 'ce-work', phase: 'Work', 
      schema: { type:'object', required:['branch','testsPassing'],
        properties:{ branch:{type:'string'}, filesChanged:{type:'array',items:{type:'string'}},
          testsPassing:{type:'boolean'}, wikiDraftPath:{type:'string'} } } });
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
    `Run the ce-review skill on branch ${workResult.branch} in ${repoDir}. ` +
    `This is REVIEW ROUND 5. Round 4's structural fix HELD — the prose-figure invariant and its enforcing ` +
    `test are in place — and round 4's review correctly moved on from provenance to correctness, finding a ` +
    `real logic bug: refusal_provably_costless was summing CORRECT_BUT_REFUSED into the "costless" total, ` +
    `the exact population the metric exists to expose. That is now fixed (positive control 8,675 -> 3,913 / ` +
    `34.12%; the 369/369 and 1,133/1,138 refusal figures were right only because CORRECT_BUT_REFUSED == 0 ` +
    `and are now pinned by TestRefusalProvablyCostless, verified by reintroducing the bug). Also since ` +
    `round 4: studies/analysis/off_category_audit.py now has full unit coverage in ` +
    `tests/test_off_category_audit.py (all verdicts, all UNRESOLVABLE reasons, the costless arithmetic, both ` +
    `equivalent_ids response shapes, and is_off_category/is_failure_open asserted as the exact complement of ` +
    `base.is_on_category); metabolite_total_deduplicated is emitted (282/6,957 = 4.05%) alongside the ` +
    `file-weighted figure, which now carries a weighting_warning because metLinkR's five target-vocab files ` +
    `are exact replicas; the broken test_resolver_source_weighting comment and the false fetch_nodes ` +
    `truncation cross-reference are fixed; and the round-4 prose guard's own false positive (token-level ` +
    `docstring detection treating any string after a colon as a docstring) now uses ast.get_docstring with ` +
    `a regression test. Branch adds +109 passing tests, parity with dev unchanged. ` +
    `PRIORITY FOR THIS ROUND: correctness of the shipped resolver behaviour and of the audit generator. The ` +
    `provenance class has been closed for two rounds and is enforced by a test; do not re-litigate it unless ` +
    `you find a genuine NEW instance. If the branch is sound, say so and return blockingFindings: 0. ` +
    `HISTORICAL CONTEXT: rounds 1-3 each blocked ` +
    `on the same class: a measured figure written into a comment or docstring with no regenerating source ` +
    `(and in round 3, one that was verifiably FALSE). Round 4 removed the generator rather than the ` +
    `instances: NO measured figure now appears in any comment or docstring in the diff — comments name the ` +
    `artifact field that carries the value (metabolite_total, per_dataset, namespace_whitelist_cost, ` +
    `failure_open_candidate_scan, protein_gene_refusal_cost, adjudicator_positive_control, ` +
    `refmet_multi_node_rate) instead of restating it. This is enforced by a new committed test, ` +
    `tests/test_no_measured_figures_in_prose.py, which tokenizes each guarded file, scans only comment and ` +
    `docstring tokens, strips identifiers (CURIEs, InChIKeys, semver, SHAs, dates, file:line refs, code ` +
    `spans), and ships positive and negative controls. Round 4 also removed the false kynurenine text-search ` +
    `example in favour of a generic statement that category_filter is advisory on both endpoints, added ` +
    `parametrized bulk-forwarding tests for text and vector (mutation-verified), and corrected the ` +
    `regenerates list to name base.py where the figures now live. Branch adds +64 passing tests. ` +
    `PRIORITY CHECKS FOR THIS ROUND: (1) confirm the prose-figure invariant actually holds across the whole ` +
    `diff and that the enforcing test can genuinely fail; (2) confirm the bulk-forwarding tests fail under ` +
    `mutation; (3) review the branch as a whole for correctness defects, which is now the open question ` +
    `rather than provenance. Judgement call to assess, not auto-block: the enforcing test's threshold is 3+ ` +
    `digits, comma-grouped numbers, or any percentage, so two-digit structural counts like "12 descendants" ` +
    `pass on the grounds that they are asserted in code via EXPECTED_ACCEPTANCE_SET and therefore testable. ` +
    `Say whether you agree rather than treating it as a defect. ` +
    `HISTORICAL CONTEXT: Round 1 blocked on comment-only numbers in config.py; round 2 blocked because ` +
    `the same class persisted in kestrel_hybrid.py, and also found that kestrel_text/kestrel_vector wrongly ` +
    `documented the category guard as "not applicable", plus a truncate_long_fields divergence from Linker. ` +
    `Since then the branch has: swept the WHOLE diff for measured figures and backed each from ` +
    `studies/analysis/off_category_audit.py over the pinned suite_20260805T033340Z (regenerates is now a list ` +
    `naming every backed file); corrected the whitelist cost from 294 to 577 at one stated scope; DELETED the ` +
    `unbackable 18/45 pool-filter figure and made that argument qualitatively; replaced the 1,200-row ` +
    `failure-open claim with a deterministic 2,400-row scan (0 empty, 3 pure-NamedThing); emitted the ` +
    `8,814/0 RefMet multi-node rate rather than asserting it; implemented the guard in text and vector ` +
    `annotators via a shared base.is_on_category predicate; set truncate_long_fields to False with a ` +
    `post-fetch assertion; and corrected the 362-vs-369 and "0/4476 suspect" figures. ` +
    `Verify those fixes hold and review the branch as a whole. ` +
    `Priority check: confirm NO measured figure anywhere in the diff lacks a regenerating source, since that ` +
    `class has now blocked twice. ` +
    `Do NOT re-raise these as defects, they are recorded decisions: the category check is a validator on ` +
    `the committed node (never a pool filter, never a namespace whitelist); the coverage cost is accepted ` +
    `deliberately (~1,000 rows to unmapped, ~14pt on metLinkR) and flat accuracy is the expected outcome, ` +
    `not a regression; D3 (block1+block2 tightening) is intentionally deferred to a follow-up PR. ` +
    `Return {blockingFindings: number, findings: string[]} where findings carries the full text of EVERY ` +
    `blocking finding (file, line, defect, failure scenario, minimal fix) plus any advisory ones, so the ` +
    `orchestrator can act on them without mining your transcript.`,
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
