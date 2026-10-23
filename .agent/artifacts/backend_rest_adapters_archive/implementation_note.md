# G2 / backend-rest-adapters

```yaml
files_changed:
  - workspace/telegram-rag-bot-src/telegram_rag_bot/citations.py
  - workspace/telegram-rag-bot-src/telegram_rag_bot/diagnostics.py
  - workspace/telegram-rag-bot-src/telegram_rag_bot/hr_adapter.py
  - integrations/__init__.py
  - integrations/ticketing.py
  - analytics/__init__.py
  - analytics/writer.py
actions: add_only
ac_covered: [AC-U01, AC-U02, AC-S6, AC-S7, AC-S4, AC-F02, AC-F03, AC-F05, AC-N02, AC-N07, AC-N11, AC-O01, AC-O02, AC-C03, AC-C04, AC-C05, AC-C06, AC-C07]
dependencies_added: []
commit_message: "feat: add isolated HR provenance diagnostic retrieval and delivery adapters"
how_to_test: "PYTHONPATH=workspace/telegram-rag-bot-src:. .venv/bin/python -B -m pytest .agent/artifacts/backend_rest_adapters_checks -q -p no:cacheprovider --basetemp=.agent/artifacts/backend_rest_adapters_checks/tmp --junitxml=.agent/artifacts/backend_rest_adapters_checks/report.xml"
```

## APIs / integration boundary

- `extract_citation(context, allowed_titles) -> Citation | None`: only source allowlist plus exact caller-provided Documents; no retrieval. **User-approved clarification**: quote is the full exact nonempty `page_content`, because this API has no query/expected-fact input. Unknown/missing source and empty/whitespace context return None. Source title is locale lookup with raw-title fallback.
- `load_graph(Path) -> Graph`: validates version, scenario/node types, keys against canonical RU catalog at bundle-relative `config/i18n/ru.yaml` without globally activating locale; every escalation, terminal FAQ anchor, path length, all-node reachability and DAG. `Graph.step` returns next question node name or terminal dictionary; terminal input returns a defensive copy. `escalate_available` accepts known node name or validated node dictionary. No session/counter dependency.
- `HRFAISSProvider(config, embeddings_provider, rag_factory=None, score_threshold=None)`: LocalFAISSProvider subclass, cached `load_index` facade forwards native attributes and supplies BaseRetriever. Exactly one native scored search, k=3. Supports only native `index.metric_type=1` (FAISS L2); invalid metric/distance/empty result fails closed at top_score=0. Valid top below threshold raises empty-candidates LowScoreFallback. Successful Documents are deep metadata copies. Both load caches and optional factory chains invalidated on save/delete. Handlers must wire this provider before chain creation with `retrieval.async_mode=false`.
- `IndexCoordinator(provider, modes_directory, chunk_size=1000, chunk_overlap=100).ingest(sources)` is async; `sources` maps Markdown Paths to mode identifiers. Paths must be within canonical matching first bundle directory, traversal and symlink escapes rejected. Existing embeddings bridge + FAISS.from_documents used off-loop, all mode indices built before publishing. Provider saves stage to sibling temporary directory, then swap with backup. Coordinator publication holds provider lock and snapshots all old modes; any save failure rolls every mode back to last-good disk state, invalidates caches. No protected provider/factory changes.
- `Ticket(user_id, mode, query, reason, top_score=None, ticket_id=UUID, timestamp=UTC)` immutable request; `TicketClient(..., transport=None, sleep=asyncio.sleep, metrics=None).create(ticket, session=None)` async returns TicketResult. Caller persists mutable session after success. Session active UUID prevents send; per-client result cache prevents repeated sends/counter increments for a completed UUID. **User-approved retry clarification**: max_attempts=3 means exactly at most 3 POSTs, sleeps 1 and 2 before attempts 2/3; tuple's 4 remains unused. Never sleep after final failure. ID/timestamp/payload stable over retries. HTTP 2xx succeeds; HTTP/OSError failures logged generically after exhaustion, only ERROR text with no payload/exception/raw ID. Timeout default 5s, trust_env=False. Error result contains existing `ticket.failed` key.
- `UnansweredEntry(mode, reason, query_redacted, top_score=None)` + `UnansweredWriter(path, fsync=False).write(entry)`: defensively redacts entry text, UTC JSONL append, only exact five fields; missing_plan and low_score supported. Parent must already exist; no directory created. Shared process thread lock and single UTF-8 bytes write. `redact` and score validation shared with ticket adapter.

## Checks / scope

Five requested test modules under artifacts cover 12 manual positive citation fixtures, negative provenance; deterministic graph paths and rejected cycles/depth/references/escalation; LCEL chain with fake document-chain proving low-score prevents generation, single search, metadata copies; inherited/subclass cache freshness and per-mode rollback including second-mode save failure; fake HTTP retry/timeout/stable JSON/dedupe/metrics/logs; concurrent JSONL redaction. No bot, ConfigLoader, handlers, Redis, real HTTP, or LLM used. Only ticket counters increment in adapters. Other retrieval/LLM/fallback metrics remain integration owner's responsibility.

## Operational limitations

- Dedupe is process/client-local; memory fallback is not shared and does not provide cross-pod dedupe. A failed UUID remains failed in the client cache; a deliberate new operation uses a fresh Ticket UUID.
- Filesystem publication locks are process-local, not crash-proof or distributed transactions. Multiple reindex writers require single-owner deployment or external coordination. Canonical source containment assumes trusted admin-owned files are not changed concurrently (filesystem TOCTOU).
- Query redaction is heuristic, not a guarantee that arbitrary sensitive data is absent. Output deliberately has no source/user_id fields.
- Root integrations/analytics packages need root import path in later packaging/wiring; this zone does not edit pyproject/main.
- Threshold gate, UI citations, diagnostic session persistence, ticket session persistence and metric observer wiring are not yet connected to Telegram handlers; this subzone does not close full G2 or establish live performance ACs.

Verification: consolidated isolated suite **50 passed**;42/42 frozen hashes match (12 protected +26 prior data/embeddings +4 accepted core). Former five deferred adapter paths are now authorized additions, not unchanged files.

## Review1 → fix for review2

Reviewer found a real cache publication race: the decorated public loader released its body lock before functools inserted the facade into cache, so a writer could publish/invalidate and the reader could reinsert the old version. Fixed only hr_adapter.py: public load_index now holds the publication lock around an inner cached helper, covering insertion into both inherited and facade caches. Public load_index.cache_clear remains available. Independent deterministic reader/writer schedule regression passes in the consolidated suite.
