# G2/data — implementation note

```yaml
agent: Implementer/data
status: ok
scope: 8 data plan entries, 20 product files
files_changed:
  - config/modes/it_support/mode.yaml
  - config/modes/it_support/system_prompt.md
  - config/modes/it_support/faq.md
  - config/modes/it_support/diagnostics.yaml
  - config/modes/benefits/mode.yaml
  - config/modes/benefits/system_prompt.md
  - config/modes/benefits/faq.md
  - config/modes/learning/mode.yaml
  - config/modes/learning/system_prompt.md
  - config/modes/learning/faq.md
  - config/modes/culture/mode.yaml
  - config/modes/culture/system_prompt.md
  - config/modes/culture/faq.md
  - config/modes/culture/policies/example.md
  - config/modes/onboarding_plan/mode.yaml
  - config/modes/onboarding_plan/system_prompt.md
  - config/modes/onboarding_plan/faq.md
  - config/modes/onboarding_plan/plans/developer.md
  - config/modes/onboarding_plan/plans/developer__engineering.md
  - config/modes/onboarding_plan/plans/default.md
ac_covered:
  - AC-S1
  - AC-S2
  - AC-S3
  - AC-S4
  - AC-S5
  - AC-S8
  - AC-F01
  - AC-F02
  - AC-C04
  - AC-U01
  - AC-U02
how_to_test: >-
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest
  .agent/artifacts/data_checks -v -p no:cacheprovider
  --junitxml=.agent/artifacts/data_checks/test_report.xml
dependencies_added: []
checks: 24 passed, 0 failed (Python 3.13.17)
commit_message_proposal: 'feat(data): add anonymized HR bundles and YAML IT diagnostics'
commit_created: false
```

## Changes and compatibility

All five bundles use existing baseline fields and only approved optional fields.
IT `mode.yaml` retains `name`, `description`, `enabled`, `files` and
`timeout_seconds` values and all baseline field types. `display_name` necessarily
changes from `IT Support FAQ` to existing locale key `mode.it_support` to meet the
explicit UI-key-only rule. Runtime translation of this key belongs to backend-rest;
this data check does not claim untranslated baseline ModeLoader already resolves it.
The only new IT fields are `source_titles` and `diagnostics_file`.

IT FAQ and original prompt remain unchanged prefixes. Exactly three new IT FAQ
sections cover VPN, mail and Git, with stable `vpn-connect`, `mail-delivery` and
`git-access` ASCII anchors. The old password-reset FAQ is retained. Each new
benefits/learning/culture FAQ has three required control facts. Onboarding has
three minimal explanatory facts and differentiated role/department/default
checklists; it does not implement session selection logic.

Contacts, links, benefit amounts, schedule and limits are clearly marked fictional,
anonymized demonstration fixtures, not real employer policy. URLs/email contacts
use example.invalid. Prompts prohibit unsupported facts, commands, credentials and
unconfirmed ticket-success claims. Existing attribution is retained.

## YAML diagnostics and UI contract

Proposed **data schema for backend-rest consumption**, not an already implemented
loader API: `version: 1`, `scenarios.{vpn,mail}.{title_key,start,nodes}`.
Question nodes have `type: question`, `question_key`, choices (`label_key`, `next`)
and `escalation`; terminal nodes have `type: terminal`, `label_key`, `faq_ref` and
`escalation`. Explicit escalation is an out-of-graph action `escalate` with a
localized `label_key`, available on every node including terminals. It is not a
cycle or a fabricated terminal command. Each scenario has three reachable terminal
nodes and maximum two questions per path; all terminal nodes reference approved
FAQ anchors. Terminal content is the referenced Markdown fact, not a new UI literal.

Every UI field uses an existing dotted RU key: `mode.*`, `diagnostics.vpn.*`,
`diagnostics.mail.*`. `source_titles` also uses existing `mode.*` keys; backend-rest
must resolve these allowlisted source titles before rendering citations.
No locale key was added or changed; all referenced keys exist.
Baseline `description` prose is preserved under the explicit exception.
`plans_directory: plans` is used only in onboarding and was already approved.
Culture policy/source titles and plan source titles are enumerated without adding
unapproved schema fields such as `sources`.

## Verification and limits

The four requested static test files live solely in `.agent/artifacts/data_checks/`:
`test_bundles_structure.py`, `test_diagnostics_keys.py`, `test_faq_facts.py`,
`test_no_ui_literals_in_yaml.py`. They use `yaml.safe_load`, plain mapping lookups,
path/anchor checks and assertions; all 24 tests passed. All 12 FAQ control pairs
have expected facts checked locally. Graph traversal enumerates every path,
rejects cycles/unreachable nodes/unknown references, requires escalation at every
step and enforces at most three questions. Baseline/preflight/core hashes in the
scope snapshot remain identical (12 protected files).

`patch.diff` contains only the 20 authorized product-file changes against
`data_scope_snapshot.json`; checks and this note are separate artifacts.
No ConfigLoader, ModeLoader, bot, index, live API, LLM, network or dependency
installation was invoked. Backend and preflight files, locales, integrations,
analytics and protected core were not edited. `review.json` is reserved for Reviewer.

These checks establish the **data portion** of linked AC only. Backend integration,
12/12 generated-answer citations, live routing, profile TTL, ticket creation,
metrics, performance, coverage and all-35-AC acceptance remain unverified and are
not claimed passed. Runtime diagnostics must later preserve the existing AC-S7
RAG-only counter semantics. Missing-plan JSONL and locale rendering also remain
backend-rest work. Stop before backend-rest; no G2 gate completion is claimed.

## Review fix cycle 1

Minor review finding resolved only in `test_faq_facts.py`: AC-S3 now checks an HTTPS link and the catalog meaning rather than a hardcoded demonstration URL. The separate example.invalid-domain privacy check remains. Product files and `patch.diff` are unchanged. Fix cycles: 1. Static checks rerun: 24 passed.
