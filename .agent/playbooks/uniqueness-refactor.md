# Playbook: Uniqueness Refactor (переделка каркаса под HR-тематику)

Сценарий: превратить `telegram-rag-bot` в «Onboarding Navigator».

## Шаги

1. Repo Auditor → `repo_map.json`, `baseline_report.md` (G0).
2. TZ Agent → `acceptance_criteria.yaml`.
3. Uniqueness Agent → `change_proposal.md` (4–6 стратегий,
   рекомендация 2–3).
4. **G1a: человек утверждает стратегии.**
5. Architect Agent → `architecture_plan.md`, `file_change_plan.yaml`.
6. Reuse/Adapter Agent → `reuse_map.yaml`.
7. **G1b: Orchestrator утверждает план.**
8. Implementer Agents (по зонам) → патчи.
9. Reviewer Agent → `review.json` (цикл ≤ 3).
10. Test Agent → `test_report.xml`, `test_summary.md`.
11. QA Agent → `acceptance_matrix.csv`.
12. **G2: тесты + матрица.**
13. Release/Docs Agent → `release_notes.md`, `README.delta.md`.

## Ключевые артефакты уникализации

- новые YAML-режимы (`mode.yaml`, `system_prompt.md`, `faq.md`);
- персонализация по роли/отделу (`config.yaml` → `roles:`);
- аналитика (`analytics.yaml` + модуль сбора);
- мультиязычность (`i18n/ru.yaml`, `i18n/en.yaml`).

## Ограничения

- Не менять ядро multi-LLM fallback и RAG без явной необходимости.
- Сохранять атрибуцию исходного проекта.
