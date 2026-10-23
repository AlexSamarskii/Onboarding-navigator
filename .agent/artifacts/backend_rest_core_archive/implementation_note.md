# G2 — backend-rest-core implementation

```yaml
agent: Implementer
status: ready_for_review
zone: backend-rest-core
files_changed:
  - workspace/telegram-rag-bot-src/telegram_rag_bot/mode_loader.py
  - workspace/telegram-rag-bot-src/telegram_rag_bot/config_loader.py
  - workspace/telegram-rag-bot-src/telegram_rag_bot/utils/session_manager.py
  - workspace/telegram-rag-bot-src/telegram_rag_bot/utils/metrics.py
ac_covered:
  - AC-S4
  - AC-S6
  - AC-S7
  - AC-S8
  - AC-F01
  - AC-F02
  - AC-F05
  - AC-C04
  - AC-C05
  - AC-C07
  - AC-U02
  - AC-N04
  - AC-N05
  - AC-N06
  - AC-N07
  - AC-N11
dependencies_added: []
commit_created: false
suggested_commit_message: "feat: extend HR configuration, session and metrics contracts"
checks:
  new_artifact_cases: 76
  unchanged_targeted_baseline_cases: 40
  passed: 116
  failed: 0
  skipped: 0
  report: .agent/artifacts/backend_rest_core_checks/test_report.xml
```

These AC are supported at infrastructure level, not accepted end to end. Full G2,
provider/ticketing wiring, data behavior, handlers and performance are not claimed.

## Behavior and public API

- ModeLoader preserves existing dictionary values/types, files.* content and
  unresolved display_name/source_titles. Additive fields enforce contained
  relative paths, Windows/traversal rejection and symlink containment before
  file access. Forbidden path spellings are rejected as strings without access.
  Invalid existing enabled MVP bundles raise ModeValidationError, including an
  MVP name in a custom directory. Disabled/optional bundles retain skip behavior;
  no requirement to create all five MVP directories in a generic legacy fixture.
- Greeting markers use t(loader.greeting_header/greeting_instruction/role_header).
  If a locale is unavailable or its marker differs from the actual old document,
  the three explicit original marker literals preserve parsing. This is the latest
  user-authorized exception to prior zero-Cyrillic AST AC-C07; it is not hidden
  with Unicode escapes. Display labels are not translated in the loader.
- Product ConfigLoader accepts the preflight config without legacy sections;
  legacy telegram/orchestrator/platform validation is retained. Modes resolve
  relative to the YAML; modes_directory retains the absolute directory after
  config.modes becomes loaded bundles. Provider order is preserved.
- _substitute_env_vars retains required legacy missing-variable errors and legacy
  optional empty substitution. Product load passes preserve_missing=True so full
  unresolved optional placeholders remain available for offline validation;
  populated referenced variables come only from os.environ at runtime.
  Product ADMIN_IDS accepts integer lists, JSON integer-array env strings or
  comma-separated decimal integers. Bool/string list elements are rejected;
  explicitly empty env means [] (no admins). Missing product placeholders are
  not proof that a runnable external integration is configured.
- SessionManager.get_session/set_session retain async signatures. New fields are
  profile, diagnostics_state, rag_fallback_streak and active_ticket_uuid. New
  explicit APIs: set_profile(user_id, role, department),
  record_rag_fallback(user_id), record_rag_success(user_id),
  record_ticket_created(user_id). The last four return the resulting dict.
  Event helpers serialize read-modify-write for one session within one process;
  diagnostics/history writes alone cannot modify the streak or profile timestamp.
- TTL is checked independently on reads in both backends; set_at_iso is anchored
  to explicit role/department input. Boundary elapsed>=ttl expires; ttl=0 means
  immediate expiry and never SETEX 0. A recent profile survives expiry of an older
  session, while streak/diagnostics/ticket operation reset. Malformed/future
  profile timestamps fail closed. New writes use aware UTC. Legacy naive
  profile.set_at_iso is interpreted as UTC; baseline naive created_at is interpreted
  in local time because the baseline wrote datetime.now(). No old tests changed.
- Redis has 5s connect/socket timeouts; logs never interpolate exception text,
  connection strings or raw IDs. Memory fallback is explicitly process-local,
  not shared state or cross-pod deduplication.
- register_metrics(registry=REGISTRY) returns a mapping keyed by existing
  QUERY_LATENCY/ACTIVE_USERS/ERROR_COUNT plus LLM_REQUESTS, RAG_SCORE,
  FALLBACK_TOTAL, TICKETS_CREATED, TICKETS_FAILED. It never rebinds REGISTRY or
  unregisters collectors. Repeated import/reload reuses collectors.
- Baseline orchestrator already registers llm_requests_total{provider,status}.
  Reuse that Counter through a bounded facade, avoiding duplicate registration.
  Application label domains are provider=gigachat|yandexgpt,
  status=success|failure (matching existing exporter), type=rag|llm. RAG_SCORE
  exposes rag_score_bucket with the exact requested nine bounds plus Prometheus
  +Inf. The other new unlabelled counters export without user-specific labels.

## Validation

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=workspace/telegram-rag-bot-src .venv/bin/python -B -m pytest .agent/artifacts/backend_rest_core_checks workspace/telegram-rag-bot-src/tests/test_mode_loader.py workspace/telegram-rag-bot-src/tests/test_config_loader.py workspace/telegram-rag-bot-src/tests/test_session_manager.py -q -p pytest_asyncio.plugin -p no:cacheprovider --basetemp=.agent/artifacts/backend_rest_core_checks/tmp --junitxml=.agent/artifacts/backend_rest_core_checks/test_report.xml
```

Five requested artifact test modules cover additive schema/legacy preservation,
path traversal and symlink escape, locale available/unavailable/changed markers,
real checked-in product configuration with an empty synthetic environment,
malformed scalar values, ordered providers and legacy substitution/platform,
profile age/Redis sliding/TTL boundary/TTL0/future and malformed timestamps,
explicit events/serialization, registry identity/reload/isolated export and bounded
labels. Redis is always a fake; env tests replace os.environ with synthetic maps.
No external request, real Redis/LLM/Telegram, secret-file reading or bot startup.
One existing langchain-community deprecation warning occurs during package import.

## Risks and deferred work

- Manual get_session/set_session read-modify-write callers still need same-session
  serialization. Helpers provide in-process locking; no cross-pod atomic claim.
- Redis operations remain synchronous, though timeout bounded; load latency is
  deferred to integration/load testing.
- Existing orchestrator exporter can write the reused LLM Counter directly.
  Its separate API is not monkeypatched; future observers must avoid incrementing
  and periodically overwriting the same values twice. Its provider names must
  remain bounded during handlers wiring. Only this module's facade rejects values.
- Prometheus lacks public collector-by-name lookup, so idempotent registration
  uses its existing name index and checks metric type/labels. No dependency change.
- Backend-rest-handlers must load the RU locale and resolve display/source keys;
  backend-rest-adapters must consume the documented event/metric APIs.
- Protected hash verification is performed independently by Orchestrator/Reviewer
  against backend_rest_core_snapshot.json; only the four allowed source files
  appear in patch.diff. No deferred source/config/data files were edited here.

## Review 1 correction

Reviewer found a baseline compatibility issue when set_session received a naive
local datetime object for created_at: attaching UTC reinterpreted local wall time.
The object is now converted using its local timezone to aware UTC, matching the
legacy naive-string interpretation. profile.set_at_iso naive parsing remains UTC.
A regression checks preserved mode immediately after write and expiry exactly
24h later. Review 1 rejection is preserved; this patch awaits review 2.
