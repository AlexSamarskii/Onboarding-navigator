# G2 / infra

```yaml
status: complete_offline_review_approve
files_changed:
  - Dockerfile
  - .dockerignore
  - .gitignore
  - deploy/k8s/deployment.yaml
  - tests/load/run_baseline.py
  - deploy/build_config_overlay.py
ac_covered: [AC-N01, AC-N02, AC-N08, AC-N09]
dependencies_added: []
author_context_ids: [/root/implementer_infra, /root]
frozen_hashes_checked: 44
unchanged: 44
accepted_i18n_hashes_checked: 8
coverage_unchanged: true
G2: open
suggested_commit_message: "feat: add offline-validated image deployment and reproducible load tooling"
```

## Implementation and consumers

The approved file_change_plan.yaml now lists six infra additions: the original four, authorized root .gitignore, and solution5 build overlay script. Five offline test modules live in .agent/artifacts/infra_checks/. No application, data, adapters, source tests, or pyproject files changed. Accepted i18n patch/note/review are preserved in backend_rest_i18n_archive/.

Docker builds the source checkout wheel in python:3.13-slim builder and installs it in a separate runtime stage. The runtime copies integrations, analytics and config, runs as uid1000, and uses urllib for the8080 healthcheck. The user approved adding `run` to CMD after static CLI inspection showed no-argument invocation only prints help. The separate approved image-copy overlay enables HTTP port8080; it does not edit repository config. Build context exclusions cover agent artifacts, tests, installed audit copy, credentials patterns and generated outputs. The .gitignore change applies only at repository root. No Docker daemon was invoked.

Kubernetes uses a plain ConfigMap+Deployment+Service manifest. Only config.yaml is overlaid via read-only subPath; locale and mode bundles remain baked. The overlay preserves the source product settings and adds HTTP8080, analytics/data and FAISS/data locations. The pod requests1CPU/2Gi and limits2CPU/4Gi; uid1000/fsGroup1000 and a restricted non-root initContainer prepare /data/analytics on emptyDir. Credentials are references to operator-provisioned telegram-secrets, never manifest values. ANALYTICS_PATH is exposed for operational consistency, but the frozen app reads the analytics path from config; the overlay supplies it explicitly. emptyDir is ephemeral and requires an external durable volume for retention beyond a pod's lifetime. The source baked config remains the dev/local default except for its authorized image-only HTTP setting.

The standalone runner samples1000 unique request IDs out of3000 offered, stratified84 for the first four scenarios and83 for the remaining eight, with seed0. Every offered request is scheduled at10RPS; warmup100 is separate. The manifest is persisted before warmup. The scheduled start is included in latency, and enough workers cover rps*timeout in-flight requests, so worker queuing cannot silently hide delay. p95 follows the requested sorted[950] definition. Failures contribute infinity internally and explicit "+inf" in standards-compliant JSON. No retrieval latency is invented: --rag-only exits2 with the prescribed message. --dry-run performs no HTTP.

AC-N01 requires an external operator-provided POST bridge accepting `{request_id, mode, query}` and responding with matching request_id and `telegram_e2e_completed: true` only after the Telegram reply is received. The frozen application's /health and /metrics are not query endpoints; a webhook ACK or Bot API sendMessage ACK does not establish E2E completion and is rejected. This bridge is an explicit environment prerequisite, not a new app endpoint. The operator must supply its real URL to --target-url. Direct Bot API acknowledgements cannot provide this measurement without such a completion bridge.

## build_time_config_overlay

```yaml
build_time_config_overlay:
  script: deploy/build_config_overlay.py
  target: /app/config/config.yaml
  changes: {http_server: {enabled: true, port: 8080}}
  order: COPY config -> COPY script -> RUN overlay -> RUN rm script -> RUN post_assert -> chown -> USER app
  post_assert: "assert c['http_server']['port']==8080; assert c['http_server']['enabled'] is True"
  internal_post_verify: reload YAML, validate enabled/port, compare top-level keys with original keys plus http_server
  repo_config_unchanged: true
  repo_config_sha256: 7739d95fa69c7e97998fdb0cca0f4eeb15c1c15c1935255c348055a20b28a277
```

The script validates mappings with ValueError (including the required string/list negatives), retains extra HTTP settings, and is idempotent. It does not resolve env placeholders or import the app. safe_dump preserves Unicode and insertion order. Only the supplied target path is read/written. Tests check original product values, top-level order, Cyrillic round-trip, postverification and error exit. Mutation controls prove that replacing update with setdefault, removing Docker overlay RUN, or removing Docker postassert fails acceptance assertions.

## Review fix

The independent review found an incorrect advertised RAG threshold700ms in dry-run output. It now follows the authoritative AC-N02 threshold200ms, guarded by an explicit assertion; --rag-only remains blocked and never pretends to measure retrieval. The final infra aggregate was repeated after this correction.

## Checks run

- Offline infra aggregate: **20 passed,1 skipped**. The skip is `kubeconform not installed; schema validated offline by structure assertions above`. Structural checks are not a claim of full Kubernetes JSON-schema validation. JUnit: infra_checks/test_report.xml.
- Full frozen source coverage guard: **316 passed,3 existing skips**, **2238/2869=78.00627396305333%**. All28 package files and aggregate coverage totals equal the accepted baseline; infra files are outside telegram_rag_bot. Existing dependency deprecation/coroutine warnings remain.
- Runtime-derived SHA256: **44/44 frozen hashes unchanged**, plus **8/8 accepted i18n hashes unchanged**. The repository config hash above is part of this check.
- No real HTTP, LLM, Redis, Telegram, Docker daemon or cluster was used. Load tests only execute --dry-run; unit checks import the standalone module for pure sampling/p95 and forbidden-network checks. Overlay tests only touch temporary copies.

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:workspace/telegram-rag-bot-src:workspace/telegram-rag-bot .venv/bin/python -B -m pytest .agent/artifacts/infra_checks -q -p no:cacheprovider --basetemp=/tmp/hr_bot_infra_checks --junitxml=/tmp/hr_bot_infra_test_report.xml

env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=workspace/telegram-rag-bot-src:workspace/telegram-rag-bot:. COVERAGE_FILE=/tmp/hr_bot_infra.coverage .venv/bin/python -B -m pytest workspace/telegram-rag-bot-src/tests --ignore=workspace/telegram-rag-bot-src/tests/load_test.py --cov=telegram_rag_bot --cov-config=workspace/telegram-rag-bot-src/pyproject.toml --cov-report=term-missing --cov-report=json:/tmp/hr_bot_infra_coverage.json --basetemp=/tmp/hr_bot_infra_cov_tmp -q -p no:cacheprovider
```

The existing source load_test.py is excluded exactly as in the accepted source coverage run; it has import-time credential-file access and is not a unit test. Coverage JSON is retained at infra_checks/coverage.json and coverage.json. Temporary XML was copied to infra_checks/test_report.xml. Real build/deploy/load, offline Kubernetes schema tool (unavailable), ao orphan scan (unavailable), and subject-manifest schema validation (schema unavailable) were not run. The content manifest records actual SHA256 identities without claiming schema validation.

## pending_environment_reproduction

The following commands are documented for an operator; none were executed. Provision runtime secrets and the external Telegram completion bridge first. AC-N08/N09 remain risk: validated offline; real build/deploy requires external environment. AC-N01 remains risk: requires real load environment; reproducible runner provided, no known code defect. AC-N02 is blocked on the stated external prerequisite. Expected outcomes below are targets, not observed results.

```yaml
pending_environment_reproduction:
  AC-N08:
    commands:
      - docker build -t onboarding-navigator .
      - docker run --rm --env-file .env -p 8080:8080 onboarding-navigator
      - curl -f http://127.0.0.1:8080/health
    expected: "HTTP 200, container healthy"
  AC-N09:
    commands:
      - kubectl apply -f deploy/k8s/deployment.yaml
      - kubectl rollout status deployment/onboarding-navigator --timeout=120s
      - kubectl get pods -l app=onboarding-navigator
    expected: "1/1 Running"
  AC-N01:
    command: python tests/load/run_baseline.py --target-url <REAL_URL> --rps 10 --duration 300 --samples 1000 --seed 0 --telegram-e2e --out artifacts/ac_n01
    expected: "artifacts/ac_n01/summary.json p95_telegram_e2e_ms <= 3000"
  AC-N02:
    status: blocked
    reason: "requires /debug/rag_latency endpoint not in current frozen app"
    options:
      - "separate small PR adding endpoint (out of infra scope)"
      - "out-of-band py-spy/pyinstrument profiling on real environment"
```

Additional live image overlay verification (also not run):

```sh
docker run --rm onboarding-navigator python -c "import yaml; c=yaml.safe_load(open('/app/config/config.yaml')); assert c['http_server']['port']==8080"
```

Before kubectl apply, make the built image available to the cluster and provision telegram-secrets. The manifest deliberately does not create secret values. Readiness/startup and real dependency compatibility await the external deployment.

## Stop boundary

Deliver patch.diff, implementation_note.md, review.json and coverage.json. G2 remains open; real build/deploy/load are pending_environment. No commit, push, or further application changes are authorized by this handoff.

Independent Reviewer `/root/reviewer_infra`: approve, round1/3,0blockers,0major,0minor;20passed1skip independently rerun. See review.json. G2 remains open.
