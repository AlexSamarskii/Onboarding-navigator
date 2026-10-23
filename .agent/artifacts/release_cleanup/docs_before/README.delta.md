# Onboarding Navigator — README delta

## What is this

HR extension of [telegram-rag-bot0.14.6](https://pypi.org/project/telegram-rag-bot/0.14.6/) for onboarding and HR support. See [release notes](release_notes.md) and [attribution](ATTRIBUTION.md). Status:31/35 AC ok,4 pending_environment,0 fail; [g2_status.json](g2_status.json) is authoritative. Commands below are operator instructions, not observed deployment results.

## Quick start — local

Run from the repository root so config and root packages integrations/analytics are available. Install the adapted source, not the unmodified PyPI release:

```sh
python -m venv .venv
.venv/bin/python -m pip install -e workspace/telegram-rag-bot-src/
```

Provision credentials securely into the current shell: `TELEGRAM_TOKEN`, `GIGACHAT_KEY`, `YANDEX_API_KEY`, `YANDEX_FOLDER_ID`, `ADMIN_IDS` (JSON integer list), `TICKETING_WEBHOOK_URL`, `HR_CHAT_ID`. Export already provisioned values and start:

```sh
export TELEGRAM_TOKEN GIGACHAT_KEY YANDEX_API_KEY YANDEX_FOLDER_ID
export ADMIN_IDS TICKETING_WEBHOOK_URL HR_CHAT_ID
PYTHONPATH=. .venv/bin/python -m telegram_rag_bot run
```

Local `run` does **not** automatically load `.env`. An operator may privately provision such a file for Docker; never commit it. No-argument module invocation prints help, so `run` is required. CWD supplies `config/config.yaml`. Local unchanged config uses HTTP8000 by default; the built image overlays HTTP8080.

In Telegram: `/start`, `/mode` to list choices, `/mode onboarding_plan`, then send a message to begin profile collection. Reply with lowercase path-safe role and department when prompted (for example `developer`, then `engineering`). `/start` alone does not collect the profile. Other choices: `/mode it_support`, `/mode benefits`, `/mode learning`, `/mode culture`.

## Quick start — Docker

AC-N08 is pending. Prerequisites: daemon and private runtime env file. Commands were not run:

```sh
docker build -t onboarding-navigator .
docker run --rm --env-file .env -p 8080:8080 onboarding-navigator
```

From another terminal:

```sh
curl -f http://127.0.0.1:8080/health
docker run --rm onboarding-navigator python -c "import yaml; c=yaml.safe_load(open('/app/config/config.yaml')); assert c['http_server']['port']==8080"
```

Expected, not observed: HTTP200/container healthy. CMD is `python -m telegram_rag_bot run`, uid1000. `deploy/build_config_overlay.py` changes only the image config copy to HTTP8080; repository config is unchanged.

## Quick start — Kubernetes

AC-N09 is pending. Prerequisites: real cluster, built image available to its nodes (or operator-adjusted image reference), and seven variables already securely injected into the operator shell. The following creates the required Secret; use an approved secret workflow if process-argument exposure is unacceptable:

```sh
kubectl create secret generic telegram-secrets \
  --from-literal=TELEGRAM_TOKEN="$TELEGRAM_TOKEN" \
  --from-literal=GIGACHAT_KEY="$GIGACHAT_KEY" \
  --from-literal=YANDEX_API_KEY="$YANDEX_API_KEY" \
  --from-literal=YANDEX_FOLDER_ID="$YANDEX_FOLDER_ID" \
  --from-literal=ADMIN_IDS="$ADMIN_IDS" \
  --from-literal=TICKETING_WEBHOOK_URL="$TICKETING_WEBHOOK_URL" \
  --from-literal=HR_CHAT_ID="$HR_CHAT_ID"
kubectl apply -f deploy/k8s/deployment.yaml
kubectl rollout status deployment/onboarding-navigator --timeout=120s
kubectl get pods -l app=onboarding-navigator
```

Expected, not observed:1/1 Running. Manifest creates ConfigMap+Deployment+Service. Read-only subPath overlays only `/app/config/config.yaml`; modes/locale stay baked. HTTP8080, writable `/data` emptyDir, read-only root, uid1000; requests1CPU/2Gi, limits2CPU/4Gi, one replica. Secret values are not in the manifest. Baked bundle/locale changes require rebuild/redeploy.

## Add a YAML mode (AC-S8)

```sh
mkdir -p config/modes/my_mode
```

Create `config/modes/my_mode/mode.yaml`:

```yaml
name: my_mode
display_name: My mode
description: Answers for the new mode
enabled: true
files:
  system_prompt: system_prompt.md
  faq: faq.md
timeout_seconds: 30
source_titles:
  faq.md: My mode FAQ
```

Add UTF-8 `system_prompt.md` and verified facts in `faq.md`. Display/source names can be literal fallback strings or existing locale keys. Keep all referenced paths inside the bundle. Optional `diagnostics_file` is a validated graph; optional `plans_directory` is a safe single directory name.

**Restart to discover a new bundle.** Admin `/reindex` refreshes Markdown for modes already in runtime config; it does not discover new definitions. Existing FAQ/plan/policy content can be reindexed. For baked container modes rebuild/redeploy. No code changes required.

## Check pending AC

Use [g2_status.json → pending_environment_detail](g2_status.json) and [exact reproduction commands](implementation_note.md#pending_environment_reproduction).

- AC-N08: Docker commands above; target HTTP200/healthy.
- AC-N09: Kubernetes commands above; target1/1 Running.
- AC-N01: real external Telegram completion bridge required, then:

```sh
python tests/load/run_baseline.py --target-url <REAL_URL> --rps 10 --duration 300 --samples 1000 --seed 0 --telegram-e2e --out artifacts/ac_n01
```

Bridge contract: POST `{request_id, mode, query}` → matching request_id and `telegram_e2e_completed: true` only after receipt of the Telegram reply. A webhook/Bot API ACK is insufficient. Frozen app does not expose this bridge. Target `artifacts/ac_n01/summary.json`: `p95_telegram_e2e_ms <= 3000`.

- AC-N02 is blocked: no `/debug/rag_latency`; separate endpoint PR or out-of-band py-spy/pyinstrument profiling required for RAGp95≤200ms. `--rag-only` exits2, never fabricates a result.

Network-free preview: `python tests/load/run_baseline.py --dry-run --seed 0 --out artifacts/dry_run`. It creates a deterministic1000-of3000 sample manifest, not latency evidence.

## Differences from upstream

Preserved routing/RAG core plus HR modes, score gate, context citations, deterministic diagnostics, profile plans, tickets, analytics, locale and infra. Full keep/adapt/add list: [release_notes.md](release_notes.md).

## Known limitations

- Process-local ticket dedupe; no cross-pod idempotency guarantee.
- Heuristic redaction; no guarantee all sensitive data is removed.
- Memory fallback is process-local, not shared state.
- Kubernetes emptyDir is ephemeral; retention needs durable storage.
- Calendar, voice, EN, analytics UI are outside scope.
- Missing `/debug/rag_latency` blocks AC-N02.
- Live Docker/Kubernetes compatibility and Telegram latency remain pending.

## Testing

Accepted coverage78.006% (2238/2869); guard≥78%. Reproduce fake-only source checks from repo root with existing development environment/pytest-cov:

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=workspace/telegram-rag-bot-src:workspace/telegram-rag-bot:. COVERAGE_FILE=/tmp/onboarding-navigator.coverage .venv/bin/python -B -m pytest workspace/telegram-rag-bot-src/tests --ignore=workspace/telegram-rag-bot-src/tests/load_test.py --cov=telegram_rag_bot --cov-config=workspace/telegram-rag-bot-src/pyproject.toml --cov-report=term-missing --cov-fail-under=78 -q -p no:cacheprovider
```

Historical `tests/load_test.py` is excluded because it accesses credential files at import time; do not run it as a unit test. No tests or live-environment commands were run during this docs-only change.
