# G2 — backend-preflight implementation

```yaml
agent: Implementer
stage: G2/backend-preflight
status: ready_for_review
files_changed:
  - config/config.yaml
  - config/i18n/ru.yaml
  - workspace/telegram-rag-bot-src/telegram_rag_bot/i18n.py
actions: [add, add, add]
ac_covered:
  - AC-C04
  - AC-C05
  - AC-C07
  - AC-S6
  - AC-S7
  - AC-F05
  - AC-N03
  - AC-U01
  - AC-U02
coverage_scope: configuration/UI/helper readiness only; these AC are not end-to-end passed
dependencies_added: []
proposed_commit_message: "feat: add HR bot configuration and Russian locale preflight"
commit_created: false
how_to_test: >-
  .venv/bin/python -B -m pytest
  .agent/artifacts/backend_preflight_checks/test_preflight.py -q
  -p no:cacheprovider
  --basetemp=.agent/artifacts/backend_preflight_checks/tmp
  --junitxml=.agent/artifacts/backend_preflight_checks/test_report.xml
verification:
  passed: 33
  failed: 0
  duration_seconds: 0.28
  live_requests: false
  installed_dependencies: false
review_fix_iteration: 0
review_fix_limit: 3
```

## Implementation and public contract

Config contains exactly the requested preflight settings. All `${ENV_VAR}`
placeholders remain literal. No real environment values are read/substituted.
The provider list is ordered GigaChat then YandexGPT; the first-available policy
is documented here and in config, and will be wired to the existing Router in
backend-rest. `modes.directory` is relative to `config/config.yaml`.

`load_locale(path) -> dict` explicitly reads UTF-8 YAML using the existing PyYAML
dependency, validates the entire catalog, activates it, and returns an independent
deep copy. No filesystem/env read or Telegram/handlers import occurs on import.
The supported catalog shape is nonempty nested mappings with nonempty string
keys without dots and string leaves; recursive aliases/nonstring leaves are
rejected. Validation/I/O/YAML errors preserve the previously active catalog.

`t(key, **kwargs) -> str` resolves dotted keys, applies simple named
`{placeholder}` interpolation and supports escaped `{{braces}}`.
Defaults: before loading raises `RuntimeError`; missing/non-leaf keys or missing
arguments raise `KeyError`; malformed keys/catalog/templates raise `ValueError`.
YAML errors and I/O errors propagate. Extra arguments are ignored. Attribute/index
traversal, conversions and format specifications are rejected during loading.
Rendering is plain text: escaping belongs to the eventual output handler.

RU catalog includes required exact strings, mode/navigation/errors/feedback,
profile/plan fallback, citation, escalation/ticket states, reindex/status, help,
diagnostics questions/options and baseline loader markers. Diagnostic terminal
instructions/HR facts remain in the future Markdown data bundles; they are not
invented in this catalog. Stable keys under `diagnostics.vpn` and
`diagnostics.mail` allow data to reference the catalog. Legacy parser markers
under `loader` support the planned later ModeLoader adaptation. Catalog text
does not claim implemented behavior. No EN catalog is delivered.

## Meaningful offline checks

33 artifact-only pytest checks verify exact requested config, required locale
strings/sections, interpolation of every template, Unicode, nested keys,
missing/invalid arguments, returned-copy isolation, generic locale loading,
no import-time locale I/O/Telegram dependencies, failed-load atomicity, malformed
YAML/types/templates/recursive aliases and missing files. Tests and their temp
files/JUnit stay under `.agent/artifacts/backend_preflight_checks`; bytecode and
pytest cache writing are disabled.

## Deferred work and scope

Only the three authorized product files are added. No handlers, ModeLoader,
ConfigLoader, main/session/metrics/RAG/router, mode data, integrations or analytics
files are changed. The lookup mechanism is not yet connected to the application.
Baseline ConfigLoader still expects legacy telegram/orchestrator configuration;
this deliberately minimal preflight config alone does not assert application
startup. Backend-rest must reconcile that contract without real credentials.
Handlers/ModeLoader still contain Cyrillic until their authorized later migration;
the full AC-C07 AST check, coverage >=78%, 12/12 U01 positives, diagnostics paths,
load tests and full G2 acceptance remain unverified. No acceptance criteria or
plans were changed, and no G2-pass claim is made.

`patch.diff` contains exactly these three additions, independent of other existing
workspace changes. Reviewer owns `review.json`; Implementer did not write it.
Stop after this zone; data requires the user's confirmation.
