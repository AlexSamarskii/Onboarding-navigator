# Playbook: Baseline Audit (G0)

Сценарий: первый запуск системы на новом репозитории.

## Шаги

1. Orchestrator подготавливает проект в `workspace/<project>`:
      ```bash
      pip install telegram-rag-bot==0.10.0 --target ./workspace/<project>
2. Вызывает Repo Auditor.
3. Repo Auditor возвращает `repo_map.json` и `baseline_report.md`.
4. Orchestrator проверяет:
    - `baseline_report.md` содержит `baseline_status`;
    - `repo_map.json.config_points` непустой;
    - есть entry points и тесты.
5. Если `baseline_status=fail` — Orchestrator пытается собрать проект
   локально (docker/build) и обновляет baseline.
6. G0 пройден → Orchestrator вызывает TZ Agent.

## Выход

- `repo_map.json`;
- `baseline_report.md`;
- статус `G0=pass`.

## Ошибки

- Нет entry points → `blocked`, запрос человеку.
- Тесты падают в baseline → зафиксировать как известное состояние,
  не блокировать G0, но пометить в `baseline_report.md`.