# G2 / backend-rest-wiring implementation

```yaml
files_changed:
  - workspace/telegram-rag-bot-src/telegram_rag_bot/main.py
  - workspace/telegram-rag-bot-src/telegram_rag_bot/handlers.py
  - workspace/telegram-rag-bot-src/pyproject.toml
ac_covered: [AC-S4, AC-S6, AC-S7, AC-S8, AC-F01, AC-F02, AC-F03, AC-F04, AC-F05, AC-N06, AC-N07, AC-N11, AC-O01, AC-O02, AC-U01, AC-U02, AC-C02, AC-C03, AC-C04, AC-C05]
risk_ac: [AC-C07, AC-N01, AC-N02]
dependencies_added: []
author_contexts:
  - /root/implementer_rest_wiring
  - /root/implementer_rest_wiring/handlers_wiring
  - /root/implementer_wiring_resume
suggested_commit_message: "feat: wire onboarding HR adapters into application"
```

## Behavior and boundaries

Product bootstrap loads locale before UI lookup, registers existing metrics, installs the HR FAISS subclass before indexing/chain construction, indexes mode-isolated Markdown, tolerates initial indexing/diagnostics failure, and registers admin commands with reload_faq aliasing reindex. RequestScopedRouter delegates routing unchanged and scopes provider observation per route; direct Yandex calls are not fallback events. Generation cancellation counts a failed attempt and propagates. Router's duplicate Prometheus exporter is not enabled.

Handlers preserve context for verbatim citations, record one retrieval score (including retrieval success followed by LLM failure), handle typed low score before broad errors, and wire explicit/automatic ticketing with process-local serialization and scoped deduplication. A confirmed ticket UUID is persisted after the core ticket event clears state; a distinct mode/query can create a distinct ticket. Onboarding and diagnostics persist their current context to avoid stale prior IT/benefit queries in tickets. Diagnostics do not change the RAG fallback streak. Onboarding profile collection validates safe role/department identifiers, prefers department-specific plans, and records missing_plan even when offering the default plan. Optional legacy platform quota checks remain before retrieval/LLM; denial returns its supplied message or the locale fallback.

No adapter/core/data/locale files changed. Existing Cyrillic constant multiset in handlers.py is unchanged (53 AST constants, including fragments and docstrings; user count47 is a different counting scope). No migration occurred. TOML project and build-system sections are semantically identical, including version/dependencies/license/attribution. Pytest artifact paths use ../../.agent from the source checkout; provisional RAG-chain coverage omission remains a review item for i18n.

## Executed checks

- `env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=workspace/telegram-rag-bot-src:workspace/telegram-rag-bot .venv/bin/python -B -m pytest .agent/artifacts/backend_rest_wiring_checks -q -p no:cacheprovider --basetemp=.agent/artifacts/backend_rest_wiring_checks/tmp --junitxml=.agent/artifacts/backend_rest_wiring_checks/test_report.xml` → **42 passed**, 1 langchain-community deprecation warning, 2.57s. Seven requested test modules plus independent reviewer boundary tests. Fakes only: startup replaces ConfigLoader.load_config, network/provider/session boundaries; runtime environment values are synthetic.
- Previous identical suite receipts: 34 passed before quota/cancellation repairs; 40 passed after quota plus observer repairs; final42 includes cancellation regressions. One intervening run stopped at collection because the new reviewer test imported its helper via collection-order-dependent module lookup; Reviewer fixed the test harness import without weakening assertions.
- Snapshot SHA-256 verification → **46/46 protected files unchanged**. The user's historical protected groups overlap and contain the currently authorized3 files; the snapshot deduplicates and excludes these three explicitly editable paths.
- AST Cyrillic constant multiset equality and TOML project/build equality → true.
- `git diff --check -- workspace/telegram-rag-bot-src/telegram_rag_bot/main.py workspace/telegram-rag-bot-src/telegram_rag_bot/handlers.py workspace/telegram-rag-bot-src/pyproject.toml` → exit0; source checkout files are untracked in root Git, so substantive patch identity comes from the frozen snapshot, not this whitespace command.

Initial sandboxed pytest attempted writes through .agent→.agents and failed with artifact directory permissions (three setup errors and JUnit PermissionError); the exact escalated command was approved and rerun successfully. No alternate artifact location was used.

## Consumers and discriminating checks

- main.main → bootstrap_components and register_command_handlers; test_main_wiring.py covers initialization order, unavailable indexing/graph, command aliases, product defaults and observer behavior without running the bot.
- existing RAGChainFactory/MultiLLMOrchestrator consumers remain unchanged; provider subclass and scoped forwarding router retain their expected interfaces. test_main_wiring.py uses the unchanged Router with fake providers; test_handlers_fallback.py and reviewer/test_handler_boundaries.py exercise real LangChain retrieval with fake retriever/document chain to prove low-score prevents document chain calls.
- TelegramHandlers command/message/callback consumers are covered by test_handlers_admin.py, test_handlers_escalation.py, test_handlers_diagnostics.py, test_handlers_onboarding.py, test_handlers_fallback.py. test_legacy_platform_quota_denial_before_chain discriminates against the interrupted implementation that bypassed configured quota checks; test_legacy_platform_quota_allow_preserves_retrieval verifies the allowed path. No RED run was captured before that repair; this evidence gap is explicit.
- ProviderObserver public failure path is covered by reviewer/test_observer_boundaries.py: generation/health cancellation and exceptions propagate, request state clears and counters remain bounded.
- AST lookup-key catalog check covers literal t() keys; dynamic mode/source labels fall back to original values.

## Not run / remaining risks

No bot, ConfigLoader execution, real Telegram/HTTP/Redis/LLM, e2e performance, wheel build/install, full legacy suite or overall coverage assertion ran in this subzone. Product startup without mocked credentials and network is intentionally unverified. AC-C07 migration remains next-subzone risk; AC-N01/N02 require infra/load tests. Provisional omission of rag_chains.py from coverage awaits the next subzone decision.

Memory/session and ticket deduplication locks remain process-local; no cross-pod guarantee is claimed. Redaction in accepted adapters is heuristic. Health cache records only the latest observed health check and is not a live probe. Missing analytics parent warns, so recording remains unavailable until the runtime volume exists. bootstrap dev indexing failure logs and continues as authorized. The overall G2 gate is not closed.

`ao provenance evidence-orphans` not run: caller confirmed ao unavailable; no invented schema validation or orphan output. Caller derives the final subject manifest at the judgment boundary. Reviewer owns review.json; Implementer does not write approval.

## Content identity (SHA-256)

```json
{
  "workspace/telegram-rag-bot-src/telegram_rag_bot/main.py": "cf5352d45b24cde5bce6869fa5c500d4797a9620d03d02c0eb91bb4ee4efe333",
  "workspace/telegram-rag-bot-src/telegram_rag_bot/handlers.py": "40b8c9769a22da622438539acb440f4b581e8a9af90c918c1b9ee31fda78eeec",
  "workspace/telegram-rag-bot-src/pyproject.toml": "558086208fc96948900db4c172488e3565aba0ccf9cd24295553363740962135"
}
```
