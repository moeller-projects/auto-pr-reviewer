meta:
  repo: moeller-projects/reviewforge
  branch: "main (snapshot 8a5edab)"
  analyzed_at: "2026-08-09"
  language: "Python 3.11+, PowerShell 7, Docker, Azure Pipelines"
  total_files: 265
  lines_changed: null  # full-snapshot review; no diff provided

summary:
  critical: 1
  high: 3
  medium: 7
  low: 7
  informational: 4

issues:

  - id: ISS-001
    severity: critical
    category: Security
    file: src/reviewforge/ai/runner.py
    line_range: [71, 74]
    title: "SYSTEM_ACCESSTOKEN survives the ADO credential scrub given to the Pi subprocess"
    description: >
      _scrub_ado_env only pops ("ADO_AUTH_TOKEN", "ADO_MCP_AUTH_TOKEN", "ADO_API_KEY"), but
      config.py's canonical token alias chain (config.py:112) is
      (SYSTEM_ACCESSTOKEN, ADO_AUTH_TOKEN, ...) -- SYSTEM_ACCESSTOKEN is the primary alias and
      the one actually present in the production Azure Pipelines path. The documented security
      invariant ("authentication tokens are stripped from the subprocess environment so the
      model cannot exfiltrate them") is therefore broken on the main deployment. The Pi agent
      has read/grep tools, so a prompt-injected PR can have the model read /proc/self/environ
      and embed the token in a "finding" that is then posted publicly to the PR thread.
    reproduction: >
      PYTHONPATH=src python3 -c "from reviewforge.ai.runner import _scrub_ado_env; import os;
      os.environ['SYSTEM_ACCESSTOKEN']='x'; os.environ['ADO_AUTH_TOKEN']='y';
      e=_scrub_ado_env(); print({k:v for k,v in e.items() if 'TOKEN' in k or 'KEY' in k})"
      → {'SYSTEM_ACCESSTOKEN': 'x'}
    suggested_fix: >
      Extend the pop tuple to ("SYSTEM_ACCESSTOKEN", "ADO_AUTH_TOKEN", "ADO_MCP_AUTH_TOKEN",
      "ADO_API_KEY", "AZURE_DEVOPS_EXT_PAT") -- or build the scrub list directly from
      config._ENV_ALIASES["ado_token"] so future aliases can't be missed. Add a regression
      test asserting every token alias is absent from the child env.
    fix_complexity: trivial
    delegation_ready: true

  - id: ISS-002
    severity: high
    category: Correctness & Logic
    file: src/reviewforge/ado/operations.py
    line_range: [503, 554]
    title: "POST_MIN_SEVERITY=none hard-crashes posting; the 'none disables filtering' branch is dead"
    description: >
      _filter_findings validates `post_min in SEV_RANK` at line 505 and raises AdoApiError
      *before* the `post_min == "none"` branch at line 520 can ever execute. "none" is
      explicitly documented as the value that disables severity filtering -- and it is even the
      Config-field default in config.py (while operations.py separately defaults to "minor",
      creating two contradictory defaults). Verified crash: AdoApiError on the filter call
      with post_min="none".
    reproduction: >
      PYTHONPATH=src python3 - <<'PY'
      from reviewforge.ado.operations import _filter_findings
      from reviewforge.pipeline.schemas import ReviewFinding
      f = ReviewFinding(file="a.py", line=1, severity="info", title="t", body="b")
      _filter_findings([f], post_min_severity="none")   # AdoApiError: invalid POST_MIN_SEVERITY
      PY
    suggested_fix: >
      Move the `if post_min == "none": ...` check above the SEV_RANK validation, and align the
      two defaults (pick "none" or "minor" in one place -- Config -- and import it in
      operations.py instead of the hardcoded getenv fallback).
    fix_complexity: trivial
    delegation_ready: true

  - id: ISS-003
    severity: high
    category: Correctness & Logic
    file: src/reviewforge/cli.py
    line_range: [98, 141]
    title: "--pr <URL> crashes: documented 'PR id or full URL' input never reaches the URL parser"
    description: >
      _build_config (124-141) passes the --pr value verbatim as pr_id. The URL-to-(org, project,
      repo, pr_id) handling exists only in _apply_common (98-121), which is dead production
      code -- only tests call it. Config later does int(cfg.pr_id) and raises ValueError. The
      CLI help text explicitly advertises "PR id or full URL", so every URL-style invocation
      of the primary entry point fails.
    reproduction: >
      reviewforge run --pr "https://dev.azure.com/org/proj/_git/repo/pullrequest/42" ...
      → ValueError: invalid literal for int() with base 10
    suggested_fix: >
      In _build_config, route non-digit --pr values through the same parsing as _apply_common
      (or simply call _apply_common's logic there) and delete/reuse the dead function so the
      tested code path is the executed one.
    fix_complexity: simple
    delegation_ready: true

  - id: ISS-004
    severity: high
    category: Correctness & Logic
    file: src/reviewforge/ai/runner.py
    line_range: [185, 200]
    title: "Augmented system prompts collide on filename stem -- wrong system prompt served to the model"
    description: >
      _resolve_system_prompt materializes a language-augmented prompt as
      f"{prompt_path.stem}.lang.md" in a shared temp dir. Two distinct prompt files with the
      same stem (e.g. fast-review/prompt.md and chunk-synthesis/prompt.md, both standard
      layouts) map to the same destination; the second caller silently receives the first
      file's content. Verified empirically: two same-stem prompts → second gets first's text.
      This corrupts review behavior with no error and no log line.
    reproduction: >
      Two PromptSpec paths /a/prompt.md (content "A") and /b/prompt.md (content "B") through
      augment_prompt_file → both read back "A".
    suggested_fix: >
      Key the augmented file by content hash or full source path, e.g.
      f"{prompt_path.stem}.{sha1(str(prompt_path.resolve()).encode())[:8]}.lang.md".
    fix_complexity: trivial
    delegation_ready: true

  - id: ISS-005
    severity: medium
    category: Correctness & Logic
    file: src/reviewforge/reasoning/single_pi.py
    line_range: [373, 373]
    title: "DISABLE_CHUNK_REVIEW / CHUNK_TRIGGER_DIFF_BYTES silently ignored by the default engine"
    description: >
      single_pi (the default ReasoningEngine) chunks solely on cfg.max_diff_bytes (line 373)
      and contains no reference to disable_chunk_review or chunk_trigger_diff_bytes
      (grep-confirmed). Only the legacy stages/review_diff.py path (126-137) honors them. Both
      knobs are documented in docs/reference/environment-variables.md and forwarded by
      azure-pipelines-pr-review.yml, so operators setting them get no effect and no warning.
    suggested_fix: >
      In single_pi, apply the same gate: skip chunking when cfg.disable_chunk_review or when
      len(diff) < cfg.chunk_trigger_diff_bytes; log which threshold fired. Alternatively
      deprecate the env vars loudly at config load if the engine won't honor them.
    fix_complexity: simple
    delegation_ready: true

  - id: ISS-006
    severity: medium
    category: Correctness & Logic
    file: src/reviewforge/ado/operations.py
    line_range: [557, 788]
    title: "Config posting settings never reach the posting logic in the in-process pipeline"
    description: >
      command_post_findings (557-741) reads POST_MIN_SEVERITY, VOTE_WAITING_ON, FAIL_ON,
      DROP_LOW_CONFIDENCE, REQUIRE_CONTEXT_FOR, MAX_FINDINGS directly from os.environ, and
      post_findings (762-788) constructs a bare SimpleNamespace without bridging any of the
      cfg.posting fields. Result: values set via Config/from_sources (the documented source of
      truth) are silently ignored; only raw environment variables work. Combined with ISS-002,
      the posting policy surface is half-wired and dual-defaulted.
    suggested_fix: >
      Have post_findings copy the six posting fields from cfg into the namespace (cfg-first,
      env-fallback), then let command_post_findings read from the namespace instead of
      os.getenv. Add a test asserting a Config-set post_min_severity is honored.
    fix_complexity: simple
    delegation_ready: true

  - id: ISS-007
    severity: medium
    category: Correctness & Logic
    file: src/reviewforge/ado/diff_mapper.py
    line_range: [206, 242]
    title: "DiffLineMapper.find() TypeError on string line numbers (reachable via run-post-only JSON)"
    description: >
      find() does `line <= new_line` in the fallback path (231-236); if new_line arrives as a
      str this raises TypeError: '<=' not supported between 'int' and 'str'. validate_findings
      and validate_postable_review_doc don't coerce the line type, so user-supplied findings
      JSON in the run-post-only flow can crash posting instead of being downgraded/dropped per
      policy.
    reproduction: >
      DiffLineMapper(diff).find("f.py", "2") → TypeError (verified).
    suggested_fix: >
      Coerce at the boundary: `new_line = int(new_line)` inside find() (with a guarded
      try/except returning the drop verdict), and/or enforce line: int via Pydantic validation
      on the findings schema before mapping.
    fix_complexity: trivial
    delegation_ready: true

  - id: ISS-008
    severity: medium
    category: Performance & Scalability
    file: src/reviewforge/pipeline/stages/review_diff.py
    line_range: [142, 190]
    title: "Chunked reviews (the most expensive path) are never written to the stage cache"
    description: >
      The single-pass branch stores cache at line 142, but the chunked else-branch (145-190)
      never calls store_cached_json. Large PRs -- exactly the runs that cost the most tokens and
      wall time -- re-execute fully on every retry/re-run, while small PRs hit cache. The branch
      also launches a per-file git diff (chunker.py:29-38), an N+1 subprocess pattern.
    suggested_fix: >
      After merging chunk results in the else-branch, call store_cached_json with the same key
      scheme as the single-pass branch. Add a cache-hit test for a two-chunk diff.
    fix_complexity: simple
    delegation_ready: true

  - id: ISS-009
    severity: medium
    category: Security
    file: src/reviewforge/ops.py
    line_range: [102, 111]
    title: "Entire host environment dumped into a temp .env and forwarded to the container via --env-file"
    description: >
      _env_file serializes all of os.environ -- every CI variable and unrelated secret on the
      agent (npm tokens, cloud creds, service-connection vars) -- into a file the container
      process receives wholesale. The container only needs a handful of REVIEWFORGE_*/ADO_*
      vars. File perms are 0600 and it's deleted in cmd_run's finally, which limits but does
      not remove the exposure (child process env, /proc, crash paths).
    suggested_fix: >
      Build the env file from an explicit allowlist (the keys config.py consumes plus PATH-less
      runtime vars), not os.environ wholesale.
    fix_complexity: simple
    delegation_ready: true

  - id: ISS-010
    severity: medium
    category: Maintainability & Code Quality
    file: src/reviewforge/config.py
    line_range: [293, 293]
    title: "Config.from_env mutates global os.environ (CHUNK_TRIGGER_DIFF_BYTES) as a side effect"
    description: >
      from_env writes os.environ["CHUNK_TRIGGER_DIFF_BYTES"] while parsing, so merely loading
      config changes process-global state (verified). from_sources does not do this, so the two
      loaders diverge in observable behavior -- an action-at-a-distance bug source for any
      caller that reads the env afterwards (e.g. operations.py's getenv-based reads, ISS-006).
    suggested_fix: >
      Return the normalized value on the Config instance only; never write to os.environ in a
      loader. If a bridge is needed for operations.py, do it explicitly in post_findings (see
      ISS-006).
    fix_complexity: trivial
    delegation_ready: true

  - id: ISS-011
    severity: medium
    category: Build/Deploy/Config Hygiene
    file: src/reviewforge/git/ops.py
    line_range: [232, 235]
    title: "git_ops.cleanup() exists but no pipeline stage ever calls it -- temp repos and auth dirs accumulate"
    description: >
      cleanup() (removes repo.* clone dirs and the GIT_ASKPASS auth temp dir) has zero callers
      in the pipeline. Long-running containers or shared clone_root volumes fill with orphaned
      clones. Related edge: GIT_ASKPASS_SCRIPT (19-23) reads os.environ['ADO_AUTH_TOKEN']
      directly, so a run authenticated only via SYSTEM_ACCESSTOKEN (a supported alias) raises
      KeyError during clone.
    suggested_fix: >
      Call cleanup() in a finally in PrepareRepository (or at pipeline teardown), and make the
      askpass script resolve the token via the same alias chain as config (SYSTEM_ACCESSTOKEN
      first).
    fix_complexity: simple
    delegation_ready: true

  - id: ISS-012
    severity: low
    category: Correctness & Logic
    file: src/reviewforge/pipeline/review_state.py
    line_range: [309, 309]
    title: "__all__ exports build_review_state_payload, which does not exist -- `import *` raises AttributeError"
    description: >
      Verified: from reviewforge.pipeline.review_state import * fails. Any future star-import
      or tooling relying on __all__ breaks; it also signals drift between the public surface
      and implementation.
    reproduction: "PYTHONPATH=src python3 -c 'from reviewforge.pipeline.review_state import *' → AttributeError"
    suggested_fix: "Remove the stale name from __all__ (or implement the payload builder if it was intended)."
    fix_complexity: trivial
    delegation_ready: true

  - id: ISS-013
    severity: low
    category: Correctness & Logic
    file: src/reviewforge/config.py
    line_range: [480, 512]
    title: "validate_files silently skips missing default /app prompt files → runtime failure instead of config error"
    description: >
      When from_env defaults point at /app/prompts/..., validate_files only validates those
      paths *if they exist*; a missing default prompt passes validation and the run fails deep
      in the reasoning stage. from_env and from_sources also default to different prompt roots
      (/app/prompts vs repo-local prompts), compounding the ambiguity.
    suggested_fix: >
      Fail fast: if a prompt path is required and missing, raise ConfigError at validate_files
      time regardless of whether it came from a default; unify the two loaders' default roots.
    fix_complexity: simple
    delegation_ready: true

  - id: ISS-014
    severity: low
    category: Correctness & Logic
    file: src/reviewforge/config.py
    line_range: [639, 643]
    title: "_build_from_sources reads pi_session_* via os.getenv, bypassing the injectable env mapping"
    description: >
      Verified: PI_SESSION_ENABLED=0 supplied through the env mapping is ignored. This breaks
      the otherwise-clean dependency-injection seam used by tests and embedders, making
      session settings uncontrollable except through the real process environment.
    suggested_fix: "Read the pi_session_* keys from the passed env mapping like every other field in that builder."
    fix_complexity: trivial
    delegation_ready: true

  - id: ISS-015
    severity: low
    category: Testing & Observability
    file: src/reviewforge/reasoning/multi_stage.py
    line_range: [116, 116]
    title: "Batched per-finding worker token usage is dropped from metrics"
    description: >
      multi_stage reads ctx.extras["_worker_token_usage"], but only review_diff.py (line 181)
      ever sets it; the forked-runner workers in verify_findings and calibrate_severity record
      nothing. Reported token totals under-count exactly the stages that fan out the most
      subprocesses. Additionally, verify_findings merges worker results in as_completed order,
      making posted finding order (and cached artifacts) nondeterministic run-to-run;
      calibrate already re-orders by index -- verify should match.
    suggested_fix: >
      Have each worker return its token usage and aggregate into _worker_token_usage in both
      stages; merge verify results by original index as calibrate does.
    fix_complexity: simple
    delegation_ready: true

  - id: ISS-016
    severity: low
    category: Correctness & Logic
    file: src/reviewforge/pipeline/sarif.py
    line_range: [11, 124]
    title: "SARIF output hardcodes a foreign org URL and always emits an empty prId"
    description: >
      _REPO_URL (line 11) is hardcoded to
      https://dev.azure.com/aveato/auto-pr-reviewer/_git/auto-pr-reviewer -- a different
      org/project than this repo, leaking stale branding into every SARIF artifact. Line 124
      reads prId from metadata.model_dump().get("pr_id"), but ReviewMetadata has no pr_id
      field, so the property is always "".
    suggested_fix: >
      Derive the repo URL from cfg (org/project/repo) at emit time; source prId from the
      actual run context (cfg.pr_id) instead of the metadata dump.
    fix_complexity: simple
    delegation_ready: true

  - id: ISS-017
    severity: low
    category: Correctness & Logic
    file: src/reviewforge/pipeline/schemas.py
    line_range: [219, 236]
    title: "RichFinding.evidence default_factory is unusable -- RichEvidence validator rejects an empty instance"
    description: >
      RichEvidence's model_validator requires ≥1 reference plus rationale, so the
      default_factory=RichEvidence on RichFinding.evidence raises a raw ValueError the moment
      the default is materialized. Any code path touching finding.evidence without explicitly
      constructing evidence crashes with a non-ValidationError.
    suggested_fix: "Make evidence Optional[RichEvidence] = None, or relax the validator to permit an empty evidence object."
    fix_complexity: trivial
    delegation_ready: true

  - id: ISS-018
    severity: low
    category: Build/Deploy/Config Hygiene
    file: azure-pipelines-pr-review.yml
    line_range: [1, 41]
    title: "Pipeline never triggers on PRs and forwards undefined variables as literal strings"
    description: >
      `trigger: none` + `pr: none` (1-2) means the PR-review pipeline cannot run in response
      to a PR -- only manual/scheduled runs work. Separately, $(DISABLE_CHUNK_REVIEW) and
      $(CHUNK_TRIGGER_DIFF_BYTES) are forwarded unconditionally (40-41); when those pipeline
      variables are undefined, Azure DevOps substitutes the literal "$(…)" string, and
      CHUNK_TRIGGER_DIFF_BYTES then fails require_uint at Config load, aborting the run.
    suggested_fix: >
      Add a real `pr:` trigger (or document that invocation is build-validation-only), and
      guard forwarding with conditional env blocks or default the variables to safe values at
      the pipeline level.
    fix_complexity: simple
    delegation_ready: true

  - id: ISS-019
    severity: informational
    category: Maintainability & Code Quality
    file: src/reviewforge/cli.py
    line_range: [98, 121]
    title: "Dead code cluster: _apply_common, _reduce_diff, duplicate SEV_LABEL, legacy _commit_lines"
    description: >
      _apply_common (cli.py 98-121) contains the only working PR-URL parser yet is called only
      by tests (see ISS-003); single_pi._reduce_diff (215-258) is never called; SEV_LABEL is
      defined twice with divergent glyphs (⚪ vs 💡 for nit); _commit_lines is superseded.
      Dead/duplicated code hides real bugs and invites wrong assumptions about which path runs.
    suggested_fix: "Delete the dead functions or wire the useful one (_apply_common) into _build_config; keep one SEV_LABEL."
    fix_complexity: simple
    delegation_ready: true

  - id: ISS-020
    severity: informational
    category: Build/Deploy/Config Hygiene
    file: pyproject.toml
    line_range: [1, 10]
    title: "Version and model-pin drift across the repo"
    description: >
      pyproject.toml says 0.3.0 while src/reviewforge/__init__.py __version__ is 0.2.0. Model
      pins also diverge: .env.example (openai/gpt-5.4-mini) vs versions.env / config default
      (gpt-5.5). Artifact contract drift too: ARTIFACT_NAMES lists posted-comments.json but
      post_findings writes posted-findings.json.
    suggested_fix: "Single-source the version (importlib.metadata or bump script), align model pins, reconcile artifact names."
    fix_complexity: trivial
    delegation_ready: true

  - id: ISS-021
    severity: informational
    category: Testing & Observability
    file: .github/workflows/python-tests.yml
    line_range: [1, 40]
    title: "97% coverage gate coexists with untested env-behavior seams -- every confirmed bug here is a live-code bug the suite misses"
    description: >
      The suite enforces --cov-fail-under=97, yet all of ISS-001…004, 007, 010, 014 reproduce
      today. The gaps concentrate on: env-var scrubbing, the operations.py getenv reads, the
      from_env/from_sources divergence, and CLI input shapes (--pr URL). pytest.ini's
      pythonpath also references a nonexistent scripts/ dir.
    suggested_fix: >
      Add targeted tests for the reproductions above (each is a few lines), preferring
      behavior tests over coverage percentage; drop the stale scripts/ pythonpath entry.
    fix_complexity: simple
    delegation_ready: false

  - id: ISS-022
    severity: informational
    category: Maintainability & Code Quality
    file: src/reviewforge/pipeline/schemas.py
    line_range: [1, 30]
    title: "Briefing/session-id text mismatch and other cosmetic doc drift"
    description: >
      _default_session_id is pr-{pr_id}-review[-{run_id}], but docstrings/comments in the
      briefing path describe a different scheme; minor, but it misleads anyone debugging Pi
      session reuse. Grouped here per the repeated-pattern rule.
    suggested_fix: "Sync the docstrings with _default_session_id's actual format."
    fix_complexity: trivial
    delegation_ready: true
