# G2 / backend-rest-i18n

```yaml
files_changed:
  - workspace/telegram-rag-bot-src/telegram_rag_bot/handlers.py
  - workspace/telegram-rag-bot-src/telegram_rag_bot/handlers_legacy.py
  - workspace/telegram-rag-bot-src/telegram_rag_bot/mode_loader.py
  - workspace/telegram-rag-bot-src/pyproject.toml
  - workspace/telegram-rag-bot-src/tests/test_hr_acceptance.py
  - workspace/telegram-rag-bot-src/tests/test_hr_adapters.py
  - config/i18n/ru.yaml
  - workspace/telegram-rag-bot-src/telegram_rag_bot/main.py
ac_covered: [AC-S1, AC-S2, AC-S3, AC-S4, AC-S5, AC-S6, AC-S7, AC-S8, AC-F01, AC-F04, AC-F05, AC-C02, AC-C03, AC-C05, AC-C07, AC-U01, AC-U02, AC-N07, AC-N10, AC-N11, AC-O01, AC-O02]
dependencies_added: []
author_context_id: /root/implementer_rest_i18n
suggested_commit_message: "feat: localize HR handlers and add offline acceptance checks"
```

## Changes and compatibility

The legacy message method is extracted as `legacy_handle_message(self, update, context)` with identical body AST and Cyrillic-literal multiset. `handlers.py` keeps its async delegating method. The legacy module's docstring identifies the pre-coordinator compatibility boundary. A separate legacy-only translation helper preserves standalone command behavior before a locale is activated; HR handlers use the normal translator and still fail if bootstrap omitted locale activation. This helper is called only when both coordinator and modes_directory are absent. The module is imported in HR runtime; its excluded legacy execution paths are unreachable there.

All remaining handler UI expressions use catalog keys. The before image contained 53 Cyrillic Constant AST nodes including f-string fragments/docstrings; the extracted method preserves 11; final handlers.py contains zero. 37 top-level literal/JoinedStr expressions were migrated. The catalog's entire original byte prefix and all existing key values are unchanged; 21 exact compatibility templates were added under legacy.*. Existing feedback.prompt, feedback.thanks, feedback.no_answer, mode.current, mode.changed, mode.unchanged, navigation.feedback and navigation.help are reused. Emoji decoration stays outside translated templates; the historical unchanged-mode text drops the final period using removesuffix, preserving prior output. Other legacy templates retain distinct exact markup, spacing, prefixes and placeholders required by prior command consumers, rather than changing their output to a similar existing HR message.

ModeLoader logic is unchanged. Its three literal marker fallbacks now carry the explicitly approved `# noqa: i18n` and backward-compat comments. The AST checker accepts only those exact _marker arguments or genuine marked logger calls, using tokenize COMMENT tokens; a quoted marker cannot suppress a violation. Negative controls cover Constant, JoinedStr, Ёё, unrelated calls and arbitrary _marker fallbacks.

The new optional-suggestion acceptance cases exposed a presentation defect: injected candidates were neither deduplicated nor ordered. Handler presentation now selects at most three unique texts, highest score first and text ascending for ties. This never creates answer context or calls retrieval. The existing frozen adapter still safely emits no candidates when none are available.

A source-suite test exposed an existing raw-router reload regression. The user separately authorized the narrow main.py amendment: new providers are wrapped only when the existing router already contains a ProviderObserver. Raw legacy routers retain their provider-list contract; HR routers retain observers and the same health cache. No other main.py behavior changed.

Coverage now includes rag_chains.py. Only the newly extracted pre-coordinator handlers_legacy.py is added to the existing omission list; __main__, tests and migrations omissions remain. Package source selection, version, dependencies, build backend, license and attribution are unchanged. Core, all adapters and product data remain frozen: 44/44 checkpoint hashes match. No infra work or commit was performed.

## Superseded tests

- Retired file: `.agent/artifacts/backend_rest_wiring_checks/test_i18n_keys_used.py`, renamed to `.py.superseded` with a three-line SUPERSEDED header. Original body bytes remain unchanged.
- Original SHA256: `81b87f6526a3c86d3dd0fa4946b454c835fc11949165c90730586cbcf6f68e63`.
- Replacement: `.agent/artifacts/backend_rest_i18n_checks/test_legacy_and_ui_cyrillic.py`.
- A: exact extracted legacy method body AST and its Cyrillic multiset are preserved. The user explicitly clarified that A applies to the extracted method; the other migrated UI is checked by B/C.
- B: handlers.py has no UI/docstring Cyrillic; only marked genuine logging calls are exempt. ModeLoader additionally permits the three exact, marked compatibility arguments. Deliberately injected UI, fake quoted noqa, Ёё and unrelated-marker fixtures are rejected.
- C: all literal t() and self._translate() keys in handlers/main resolve to string leaves in the RU catalog. Archive-body SHA and approved legacy preservation are checked independently.
- The archived obsolete literal-retention assertion was actually executed through runpy against the localized handler and raised the expected AssertionError. This is an intentional acceptance change, not a regression; the archive preserves provenance and no other old test was changed.

## Review fix 1

Formal review 1 identified five redundant new legacy keys. They were removed; mode.current, mode.changed, mode.unchanged, navigation.feedback and navigation.help now supply those messages. Their emoji decoration and historical unchanged-mode punctuation are preserved at presentation, and the pre-locale helper stores neutral existing-key templates. No existing catalog values, extracted legacy body, old tests or frozen files changed. Both the 276-test target aggregate and the 316-pass/3-skip source coverage run were repeated against this exact fix; coverage remains 2238/2869 (78.00627396305333%).

## Checks run

1. New acceptance plus replacement: **46 passed** (one dependency deprecation warning).
2. Final requested target aggregate, with standalone replacement additionally included: **276 passed**, two dependency deprecation warnings. JUnit: `.agent/artifacts/backend_rest_i18n_checks/test_report.xml`.
3. Full source tests with coverage and offline fakes: **316 passed, 3 skipped**, three warnings. The existing load-test runner is explicitly ignored so this unit run cannot launch a real load scenario. No HTTP/LLM/Redis/Telegram service was used by new tests.
4. Coverage threshold script: passed. Actual line coverage is **2238/2869 = 78.00627396305333%** (78.01% for display), with 631 missing lines. This is a real unrounded >=78% comparison. Data: `.agent/artifacts/backend_rest_i18n_checks/coverage.json`; full output: `coverage_run.log`.
5. Catalog original prefix preservation, legacy method AST equality, superseded original-body hash, and 44 frozen source/config hashes checked.

### Exact aggregate command

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=workspace/telegram-rag-bot-src:workspace/telegram-rag-bot:. .venv/bin/python -B -m pytest .agent/artifacts/backend_rest_core_checks .agent/artifacts/backend_rest_adapters_checks .agent/artifacts/backend_rest_wiring_checks workspace/telegram-rag-bot-src/tests/test_hr_acceptance.py workspace/telegram-rag-bot-src/tests/test_hr_adapters.py .agent/artifacts/backend_rest_i18n_checks/test_legacy_and_ui_cyrillic.py -q -p no:cacheprovider --basetemp=.agent/artifacts/backend_rest_i18n_checks/tmp --junitxml=.agent/artifacts/backend_rest_i18n_checks/test_report.xml
```

### Exact source coverage command

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=workspace/telegram-rag-bot-src:workspace/telegram-rag-bot:. COVERAGE_FILE=.agent/artifacts/backend_rest_i18n_checks/.coverage .venv/bin/python -B -m pytest workspace/telegram-rag-bot-src/tests --ignore=workspace/telegram-rag-bot-src/tests/load_test.py --cov=telegram_rag_bot --cov-config=workspace/telegram-rag-bot-src/pyproject.toml --cov-report=term-missing --cov-report=json:.agent/artifacts/backend_rest_i18n_checks/coverage.json --basetemp=.agent/artifacts/backend_rest_i18n_checks/tmp_coverage -q -p no:cacheprovider
```

## Limits and remaining work

AC-C07 is verified for the explicitly approved scan scope and three marker exceptions. AC-N10 passes the approved source denominator. Coverage has a small margin above 78%, so future code additions can require additional behavioral tests. AC-N01/N02 remain unverified e2e performance requirements; no load test, live bot, deployment or infrastructure checks ran in this zone. Existing adapters retain their documented process-local deduplication and heuristic redaction limitations. The pytest-cov tool was installed in the local virtualenv with user approval; package dependencies were not changed.

`ao provenance evidence-orphans` was not run: AgentOps integration is not part of this project handoff. The root orchestrator derives the final subject manifest for independent review. No claim is made that full G2 is complete; stop before infra.
