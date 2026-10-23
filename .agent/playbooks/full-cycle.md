# Playbook: Full Cycle (от репо до RC)

Сценарий: полный прогон системы на новом проекте.

## Шаги

1. Baseline Audit (`playbooks/baseline-audit.md`) → G0.
2. TZ Agent → `acceptance_criteria.yaml`.
3. Uniqueness Refactor (`playbooks/uniqueness-refactor.md`) → G1.
4. Реализация по зонам + review-циклы.
5. Test Agent + QA Agent → G2.
6. Release/Docs Agent → RC.

## Условия остановки

- 3 цикла review↔fix без прогресса → эскалация человеку.
- `max_iterations` исчерпан → эскалация.
- `acceptance_matrix.csv` содержит `fail` по `mandatory` → G2 не пройден.

## Выход

- `release_notes.md`;
- `acceptance_matrix.csv` (все `pass` или `risk` с обоснованием);
- `test_report.xml` (regression=pass, coverage ≥ 78%).