# Playbook: New Feature (добавление YAML-режима или фичи)

Сценарий: добавить новую фичу или YAML-режим в HR-бота.

## Шаги

1. TZ Agent обновляет `acceptance_criteria.yaml` (новый AC для фичи).
2. Uniqueness Agent (при необходимости) обновляет `change_proposal.md`.
3. Architect Agent обновляет `architecture_plan.md`
   и `file_change_plan.yaml` (только затронутые файлы).
4. Reuse/Adapter Agent обновляет `reuse_map.yaml`.
5. Implementer Agent пишет патч строго по плану.
6. Reviewer Agent даёт `review.json`.
7. При `reject` — Implementer исправляет по замечаниям, цикл ≤ 3.
8. Test Agent запускает тесты, обновляет `test_summary.md`.
9. QA Agent обновляет `acceptance_matrix.csv`.
10. Orchestrator проверяет G2.

## Ограничения

- Не менять ядро без эскалации к Architect.
- Не расширять scope: только AC из шага 1.
- Максимум 3 цикла review↔fix, затем — человеку.

## Выход

- Обновлённые артефакты;
- `G2=pass` или эскалация.
