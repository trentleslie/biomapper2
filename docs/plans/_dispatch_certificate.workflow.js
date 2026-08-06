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
const planPath = '/home/trentleslie/projects/biomapper2/docs/plans/resolution-certificate-plan.md';
const artifactPath = '/home/trentleslie/projects/biomapper2/docs/plans/resolution-certificate-brainstorm.md';
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
    `Implement the approved plan at ${planPath} test-first, in repo ${repoDir}. `+
    `LIVE COMPUTE IS OUT OF SCOPE. Tier B is opt-in and DEFAULT-OFF: build it and unit-test it against `+
    `fixtures, but NEVER fire the Tier B sweep and never call Metabolomics Workbench, PubChem or `+
    `kestrel.krakenkg.com. The single committed Tier B sweep that produces Figure 5 is a separate supervised `+
    `step fired by the operator, not by this pipeline. Tier A must remain ZERO-I/O: it reads `+
    `kg_equivalent_ids['INCHIKEY'] ONLY and must NOT reuse inchikey_blocks(), which falls through to `+
    `MW/PubChem by name when the KG lists no key — that is a VERIFIED hazard, not a precaution, and `+
    `consolidating them would shift the state distribution with no test going red. `+
    `If a task appears to need a live call, STOP and say so rather than making it. ` +
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
    `REVIEW ROUND 7 at HEAD bd47557. Run the ce-review skill on branch ${workResult.branch}. ` +
    `ROUND 6 found the decisive one: I had hardened the STUDY MODULE against an InChIKey case ` +
    `mismatch twice and never checked the SHIPPED comparison, which folded nothing on either ` +
    `side -- so issue() emitted 'contradicted' for two spellings of one molecule, and because ` +
    `the audit folds and issue() did not, a partial mismatch published Panel B with the ` +
    `separation INVERTED and every gate satisfied. Fixed at bd47557: folded at both producers ` +
    `AND at the comparison. Also pinned three controls that were green under mutation ` +
    `(_first_block's gold-side fold, the no-certificate refusal reason, every term of the ` +
    `mapper's Tier B scoping predicate). Five mutations each redden a distinct control. ` +
    `THE GENERALIZABLE LESSON, and where to look next: I repeatedly fixed a defect in the ` +
    `INSTRUMENT and left the same defect in the CODE BEING MEASURED. Sweep for that shape ` +
    `specifically -- any normalization, guard, or invariant the study module enforces that the ` +
    `production path does not (and vice versa), especially where the two disagreeing would make ` +
    `the artifact look BETTER rather than crash. Also continue hunting controls that pass ` +
    `because an earlier gate fires or because they assert a shape where the defect is a value. ` +
    `THIS IS ROUND 7. If nothing blocking survives verification, say so plainly and report ` +
    `blockingFindings 0 -- do NOT manufacture a finding to continue the pattern.` +

    `ROUND 5 found Panel B strata keyed on _independent_source ALONE, pooling rows the ` +
    `corroborating registry also SELECTED with rows it did not (the L26 axis). Fixed at 8291a11: ` +
    `strata are keyed on the PAIR {source}/indep={true|false|unknown} and the gate refuses any ` +
    `stratum with Tier-B-adjudicated rows whose independence is not established, scoped to ` +
    `adjudicated states so a verdict-free stratum cannot veto the arm. Also: the per-stratum and ` +
    `pooled gates now treat an unmeasurable overlap identically, BOTH operands of the agreement ` +
    `comparison case-fold, and the committed artifact was regenerated (it was two ` +
    `generator-changing commits stale). All four branches mutation-tested. NOTE one mutation ` +
    `caught a DECORATIVE control of mine: the first unmeasurable-overlap test passed because the ` +
    `POOLED gate refused first, so the per-stratum branch was never reached. It was rebuilt to ` +
    `isolate the branch. HUNT FOR MORE OF THAT SHAPE -- controls that pass because an earlier ` +
    `gate fires, fixtures that satisfy an assertion incidentally, and any gate branch no test ` +
    `reaches. Also check the new stratum KEY itself is not spoofable (a source string containing ` +
    `'/indep=', or a stratum whose points list is empty). ` +

    `ROUND 4 said the round-3 gate was correct but applied to the POOLED population while Panel B ` +
    `is drawn PER STRATUM, so a circular stratum could hide behind an independent one. Fixed at ` +
    `29bb563: the control is computed per stratum, attached to each, and the arm refused when any ` +
    `stratum exceeds the ceiling. Pinned by a two-stratum fixture that asserts the POOLED rate ` +
    `clears the ceiling, so it cannot pass for the wrong reason; mutation-tested by emptying the ` +
    `per-stratum loop. Also fixed: _first_block now case-folds (a lower-case gold file drove the ` +
    `agreement rate to 0.0, which SILENTLY CLEARED the gate), the control now renders into the .md, ` +
    `and the mapper's Tier B scope now matches issue()'s population predicate including ` +
    `equivalent_ids_lookup_ok. VERIFY the per-stratum gate cannot itself be dodged -- consider ` +
    `strata with one row, all-None agreement, mixed independent_of_selection, and a stratum whose ` +
    `curve is drawable but whose control is None. The worktree's git index was corrupt and has been ` +
    `repaired with git read-tree HEAD; if a git-touching test fails, re-check the index before ` +
    `reporting it as a defect. ` +

    `**Work in the isolated worktree /home/trentleslie/worktrees/bm2-certificate**, NOT the shared ` +
    `checkout at ${repoDir}, which is on a different branch with uncommitted changes. Export ` +
    `PYTHONPATH=/home/trentleslie/worktrees/bm2-certificate/src before pytest or you will silently ` +
    `test the wrong tree. Diff base is the merge-base with origin/dev. ` +
    `ROUND 3 CONTEXT: one BLOCKING finding — Panel B's precision and the \`corroborated\` state both ` +
    `test membership in the same node block set, so when Tier B's answer equals the gold key the ` +
    `curve's separation is an identity rather than a measurement (reachable on the RefMet arm, whose ` +
    `gold key and Tier B first hop are both RefMet keyed on the query name). Fixed at 0c81021 by an ` +
    `\`oracle_independence_control\` that measures Tier B/gold agreement and refuses the curve above a ` +
    `ceiling, with an unmeasurable overlap also refusing. VERIFY THAT GATE HARD: confirm it actually ` +
    `refuses a circular arm, that it does not refuse a genuinely independent one, and that the ` +
    `agreement rate is computed over the right population. I mutation-tested it (disabling the gate ` +
    `fails the control) — check that this holds and that the control is not passing for an incidental ` +
    `reason. Also re-check the three advisories fixed in the same commit: independent-evidence fields ` +
    `now scoped to the certificate population (certificate.py + mapper.py), the no-verifiable-population ` +
    `refusal reason, and the committed-rows/all-rows table headers. ` +
    `The deferred fixture-naming advisory is a known follow-up; re-report only if actually blocking. ` +
    `PRIOR ROUND CONTEXT (still applies, fixed at 5464e3a): `+
    `(a) The encoding sweep is now COMPLETE: grep -rn 'quote(' src/ | grep -v safe= returns EMPTY — all `+
    `six sites carry safe='', including the two default-on annotator sites (metabolomics_workbench.py, `+
    `lipidmaps_rest.py) that round 2 correctly identified as reaching chosen_kg_id via the vote. Both `+
    `pinned by tests and positive-controlled. (b) The past-tense prose is reworded: slash_bearing_name_rate `+
    `is now documented as EXPOSURE — a property of the NAMES that does not shrink when a site is fixed — `+
    `with all six call sites enumerated so a seventh is added against a correct picture. (c) `+
    `curve_publishable now has a positive control, verified by wiring the gate shut. (d) The Tier B gate is `+
    `scoped to the verifiable population Panel B plots, with the all-rows figure retained as `+
    `resolution_rate_all_rows. 881 passed / 216 skipped. `+
    `A new artifact field spurious_independence reports 292/6,957 = 4.20% and carries bound: upper inline, `+
    `because a committed artifact cannot separate 'could not ask' from 'asked and got nothing' — treat that `+
    `labelling as correct, not as an unfinished measurement. `+
    `PRIORITY: correctness of certificate semantics and the audit generator. Do not re-litigate the `+
    `prose-figure class absent a genuine NEW instance. If sound, return blockingFindings: 0. `+
    `HISTORICAL: round 1 blocked on quote() encoding and audit filter ordering; round 2 on an incomplete `+
    `encoding sweep that missed the annotator path. (a) All four quote() sites now use ` +
    `safe='' (tier_b 2, structure_resolver 2), pinned by tests with POSITIVE CONTROLS — the fix was ` +
    `reverted, both tests went red, then restored. (b) The audit's committed-only filter no longer ` +
    `precedes state accounting, so uncommitted rows reach Panel A and certificate_state_counts while ` +
    `precision denominators stay committed-only; positive-controlled at 9 != 12 against the old ordering. ` +
    `All five non-blocking items are also done: the Tier B sweep resolves inside --suite-dir so audit() ` +
    `is a pure function of one input; Tier B no longer memoizes transient lookup_failed; ` +
    `SELECTION_CONFLICT_VALUES is now the real tri-valued domain; the bogus test citation is corrected; ` +
    `UNGUARDED_TREES_KNOWN is enforced by a meta-test. 877 passed / 216 skipped, and the skips were ` +
    `verified as unreachable state-table combinations rather than assumed. ` +
    `PRIORITY THIS ROUND: correctness of the certificate semantics and of the audit generator. The ` +
    `prose-figure class is enforced by a glob-derived guard with meta-tests — do not re-litigate it ` +
    `absent a genuine NEW instance. Note Tier B is default-off and was never fired; the sweep is a ` +
    `separate operator step, so curve_publishable: false everywhere is the correct honest state, not a gap. ` +
    `If the branch is sound, say so and return blockingFindings: 0. ` +
    `Return {blockingFindings: number, findings: string[]} where findings carries the FULL TEXT of every `+
    `blocking finding (file, line, defect, failure scenario, minimal fix) plus any advisory ones, so the `+
    `orchestrator can act without mining your transcript.`,
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
