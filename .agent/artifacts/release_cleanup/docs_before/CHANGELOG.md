# Changelog

All notable HR-extension changes are documented following Keep a Changelog. Version0.1.0 denotes this documentation milestone; upstream package version/build metadata were not changed.

## [0.1.0] - 2026-10-23

### Added

- HR adapters: citations, deterministic diagnostics, ticketing, unanswered analytics.
- i18n mechanism and Russian locale124 leaf keys.
- Five YAML modes and onboarding plan variants/default.
- `HRFAISSProvider(LocalFAISSProvider)` with score gate0.65 and index coordination.
- Dockerfile, .dockerignore, root .gitignore, Kubernetes manifest and image config overlay.
- Reproducible standalone load runner `tests/load/run_baseline.py`.
- Offline test coverage78.006% (AC-N10≥78%).
- Release documentation and retained upstream MIT notice.

### Changed

- Handlers:47 legacy literals→translations, HR adapter wiring.
- Main:bootstrap_components, ProviderObserver, RequestScopedRouter, narrow authorized legacy reload fix.
- Mode loader:optional field validation and three marked legacy fallback literals.
- Config loader:product config validation, preserving legacy contract.
- Session manager:profile TTL, diagnostics_state, rag_fallback_streak, active_ticket_uuid.
- Metrics:five additional series within the existing registry.
- Legacy compatibility handler extracted and coverage-omitted; fake LCEL exercises real rag_chains paths.

### Fixed

- Review-found race condition in `HRFAISSProvider.load_index`.
- Review-found naive datetime in `session_manager.set_session`.
- Legacy Router reload no longer unconditionally adds HR observers.
- Fallback suggestions:dedupe and stable score/text ordering.
- Review-found duplicate legacy UI keys during approved migration.
- Infra dry-run RAG target corrected to200ms; actual retrieval measurement remains unavailable.

### Superseded

- Wiring `test_i18n_keys_used.py` archived as `.py.superseded`; original SHA256 `81b87f6526a3c86d3dd0fa4946b454c835fc11949165c90730586cbcf6f68e63`; replacement `backend_rest_i18n_checks/test_legacy_and_ui_cyrillic.py` preserves legacy logic and checks active i18n invariants.

### Pending environment

- AC-N01:real Telegram completion bridge/load environment for E2Ep95≤3000ms.
- AC-N02:blocked, missing `/debug/rag_latency`; endpoint PR or external profiling for RAGp95≤200ms.
- AC-N08:real Docker build/run.
- AC-N09:real Kubernetes deployment with image/telegram-secrets.
- These four outcomes are unobserved. See [release notes](release_notes.md), [G2 status](g2_status.json), [reproduction](implementation_note.md#pending_environment_reproduction). G2 remains conditional; docs do not close it.
