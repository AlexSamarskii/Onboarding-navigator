# Onboarding Navigator — Release notes 0.1.0

## Summary

**31/35 AC ok, 4 pending_environment, 0 risk, 0 fail.** G2 verdict is `pass_with_pending_environment`, per the accepted user handoff and authoritative [g2_status.json](g2_status.json). This documentation does not close G2 or certify a production deployment.

## What works end-to-end (offline-validated)

The following application paths were exercised with fakes and local artifacts, without live Telegram/LLM/Redis/Docker/Kubernetes:

- YAML modes: `it_support`, `benefits`, `learning`, `culture`, `onboarding_plan`. New bundles require no code edits and are discovered at restart (AC-S8).
- GigaChat→YandexGPT fallback through the preserved orchestration core (AC-N03).
- FAISS RAG with similarity threshold0.65: below threshold, fallback replaces generation, with available top-three suggestions and escalation (AC-S6).
- Personalized onboarding by role/department: 24-hour profile TTL from explicit input; plan order `<role>__<department>.md`→`<role>.md`→`default.md` (AC-S4/F01).
- Citations: allowed source plus exact returned `page_content`; no repeated retrieval. Unavailable context or unknown source produces the localized unavailable message (AC-U01).
- VPN/mail diagnostics: validated YAML branches, no LLM decisions, escalation at every step (AC-U02).
- Explicit tickets and automatic tickets after two consecutive RAG fallbacks, stable retry UUID and process-local dedupe (AC-S7/F05).
- Admin-only `/reindex` and `/status`; `/reload_faq` aliases `/reindex` (AC-F03/F04).
- Metrics: `llm_requests_total`, histogram `rag_score_bucket`, `fallback_total{type="rag"|"llm"}`, `tickets_created_total`, `tickets_failed_total` (AC-N04..N07/N11).
- i18n readiness: `i18n.py`, **124 translation leaf keys** in `ru.yaml` (not240+); active-handler/mode-loader AST clean, with three marked legacy loader fallback literals. EN remains outside scope (AC-C07).
- Source suite:316 passed,3 existing skips; coverage **2238/2869=78.006%** (AC-N10). Infra:20 passed,1 skip because kubeconform unavailable. Frozen hashes44/44 plus accepted i18n8/8 unchanged.

## What is pending_environment

None of the following real-environment outcomes has been observed. See [g2_status.json → pending_environment_detail](g2_status.json) and [Reproduction](#reproduction).

| AC | Target and prerequisite |
| --- | --- |
| AC-N01 | Telegram E2E p95≤3000ms; requires real Telegram completion bridge and load environment. |
| AC-N02 | RAG p95≤200ms; **blocked**: frozen app has no `/debug/rag_latency`. Separate endpoint PR or py-spy/pyinstrument profiling required. |
| AC-N08 | Docker image build/run requires Docker daemon and runtime credentials. |
| AC-N09 | Kubernetes deployment requires real cluster, accessible image and `telegram-secrets`; target1/1 Running. |

## Reproduction

Exact commands/expected outcomes: [implementation_note.md#pending_environment_reproduction](implementation_note.md#pending_environment_reproduction), referenced by [g2_status.json](g2_status.json). Commands below are operator instructions; they were not executed.

```sh
docker build -t onboarding-navigator .
docker run --rm --env-file .env -p 8080:8080 onboarding-navigator
curl -f http://127.0.0.1:8080/health
kubectl apply -f deploy/k8s/deployment.yaml
kubectl rollout status deployment/onboarding-navigator --timeout=120s
kubectl get pods -l app=onboarding-navigator
python tests/load/run_baseline.py --target-url <REAL_URL> --rps 10 --duration 300 --samples 1000 --seed 0 --telegram-e2e --out artifacts/ac_n01
```

`<REAL_URL>` must be an external POST bridge accepting `{request_id, mode, query}` and responding with matching request_id and `telegram_e2e_completed: true` only after receiving the Telegram reply. Frozen health/metrics endpoints cannot answer queries. Webhook ACK and Bot API sendMessage ACK are insufficient for E2E measurement. Target summary: `p95_telegram_e2e_ms <= 3000`. `--rag-only` exits2 explaining the absent endpoint, without inventing latency.

## Architecture deltas from telegram-rag-bot 0.14.6

- **Keep, hash-verified:** upstream `orchestrator/router.py`, `orchestrator/retrieval/async_faiss.py`; `telegram_rag_bot/langchain_adapter/rag_chains.py`, `vectorstore/local_faiss.py`, `__main__.py`, embeddings implementation. The frozen44-file set also includes previously accepted changes; “frozen” does not mean every frozen file is upstream-as-is.
- **Adapt:** `handlers.py` (47 literal migration and HR wiring), `main.py` (`bootstrap_components`, `ProviderObserver`, `RequestScopedRouter`, authorized narrow legacy reload fix), `mode_loader.py` (optional fields, three marked legacy fallbacks), `config_loader.py` (product config), session manager (profile/diagnostics/streak/ticket UUID), metrics (five new series).
- **Add:** `hr_adapter.py` with `HRFAISSProvider(LocalFAISSProvider)`, `citations.py`, `diagnostics.py`, `i18n.py`, extracted compatibility `handlers_legacy.py`, `integrations/ticketing.py`, `analytics/writer.py`. Legacy handler is unreachable in HR runtime and coverage-omitted; real LCEL `rag_chains.py` paths remain covered with fakes.
- **Config:** product settings with env placeholders, Russian locale124 leaf keys, five mode bundles, onboarding plans and culture policies.
- **Infra:** wheel image, context exclusions, plain ConfigMap/Deployment/Service, deterministic load runner, image-only config overlay. HTTP8080 is applied to the image copy; repo config stays unchanged. Kubernetes additionally places analytics/FAISS under `/data`.

## Superseded tests (provenance)

`.agent/artifacts/backend_rest_wiring_checks/test_i18n_keys_used.py` was archived as `.py.superseded` with original body retained beneath a provenance header. Original SHA256: `81b87f6526a3c86d3dd0fa4946b454c835fc11949165c90730586cbcf6f68e63`.

Replacement: `.agent/artifacts/backend_rest_i18n_checks/test_legacy_and_ui_cyrillic.py`. A/A′ preserve the extracted legacy method's Cyrillic multiset and normalized AST logic; B rejects unapproved active UI Cyrillic; C resolves literal translation keys. The old assertion demanded literals remain in handlers and would fail after approved migration; this was intentional supersession, not a regression.

## Security & compliance

Credentials are runtime env/Secret values; configs/manifests contain placeholders/references. Accepted offline review reported no raw secrets in config, manifests, logs or tests. No secret files were read during release docs work.

**Limitations:** redaction is heuristic and does not guarantee removal of all sensitive data; ticket idempotency is process-local, not cross-pod; memory fallback is process-local, not shared state. Kubernetes emptyDir is ephemeral. Calendar, voice, EN, analytics UI, HR-auth, purchases and HR-data changes remain outside scope.

Attribution and full actual MIT notice for telegram-rag-bot0.14.6 are retained in [ATTRIBUTION.md](ATTRIBUTION.md).
