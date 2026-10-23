# Классификация публичного среза — проект до approval

Это предложение, а не результат удаления. Каждая наблюдаемая запись в `path_classification.json` отнесена ровно к одной категории. Директории reference/venv/tool-settings представлены группой без обхода содержимого. Закрытые пути не перечислялись. Логические пути `.agent/...` обозначают единственное физическое дерево `.agents/...`, а не вторую копию.

Пересечения исходного запроса разрешены явно: временные файлы из C НЕ дублируются в B; для них после удаления всё равно предлагаются защитные ignore-маски. Reference-клоны с ожидаемым решением относятся только к D; рекомендация — после подтверждения перевести в B. Acceptance-тесты уже явно велено оставить: это A, не повторный вопрос D. Сборочные/секретные/runtime-исключения внутри продуктовых деревьев относятся к B, остальные исходники к A.

## A — сохранить для публикации

- `workspace/telegram-rag-bot-src/`: продуктовые исходники и все исходные `tests/test_*.py`, включая HR; исключая только runtime/build-маски B. Собственного `.git` не найдено.
- `integrations/`, `analytics/__init__.py`, `analytics/writer.py`.
- `config/config.yaml`, `config/i18n/ru.yaml`, все `config/modes/` bundles и Markdown.
- `deploy/build_config_overlay.py`, `deploy/k8s/deployment.yaml`, `tests/load/run_baseline.py`.
- `Dockerfile`, `.dockerignore`, `.gitignore`, `AGENTS.md`, существующий `workspace/README.md`.
- Ссылка `.agent -> .agents` и фактические `.agents/{roles,playbooks,prompts}`; оставшиеся артефакты `.agents/artifacts/`, кроме явно B/C.
- Обязательные `review.json`, `g2_status.json`, `coverage.json`, `release_notes.md`, `README.delta.md`, `CHANGELOG.md`, `ATTRIBUTION.md`, `patch.diff` внутри artifact storage.
- Acceptance `*_checks/*.py`, `.superseded` с provenance, `*_snapshot.json`, `*_subject_manifest.json`, `*_inventory.json`, baseline/hash JSON, XML/JSON и старые отчёты, не попавшие под явно перечисленные транзиентные маски. JSON coverage в артефактах сохраняется.
- Публичный пример переменных окружения — требование A; его фактическое наличие/содержимое не проверено из-за ограничения на `.env.*`. Шаблон семи имён дан в proposal для ручного создания оператором.

Это MUST COMMIT, а не утверждение, что файлы уже tracked: сейчас в проекте tracked только `.codex/config.toml` и `workspace/README.md`. Никакого staging не выполнено.

## B — исключить, оставить на диске

- Защитные маски секретов `.env`, `.env.*` с исключением `!.env.example`, `*.pem`, `*.key`, `secrets/`. Это правила, не результат чтения файлов.
- `.venv/`, Python-кэши, `*.pyc`, `*.pyo`, egg-info, build/dist, pytest/mypy/ruff cache, `htmlcov/`, корневые coverage-runtime-файлы, wheel/sdist; внутри `.agent/artifacts/` конкретные C имеют приоритет.
- Вложенные `test_report.xml` и обычные agent `.log`, кроме конкретного `coverage_run.log` в C. Сохранение на диске обязательно, удаление этих отчётов не предлагается.
- `workspace/telegram-rag-bot/`: installed audit copy. Оставить локально; исходные hash-тесты зависят от двух файлов внутри неё.
- IDE/OS-маски `.idea/`, `.vscode/`, `.DS_Store`, `*.swp`, `*.swo`; закрытые IDE-пути не обследовались.
- `analytics/unanswered.jsonl`, корневые `/artifacts/`, `/.faiss_indices/`.
- Пути `/tmp/trb-*` относятся только к C и находятся вне действия репозиторного `.gitignore`.

## C — предложено удалить только после отдельного подтверждения

- Наблюдаемые pytest `tmp*/`, reviewer `reviewer_tmp*/` под artifact storage.
- Agent `__pycache__/`, `*.pyc`, `.coverage*`, `coverage_run.log`; фактические цели перечислены в `delete_candidates.json` и proposal с индивидуальным `du -sh`.
- Обнаруженный внешний `/tmp/trb-sdist`. Удаление также требует подтверждения; других `/tmp/trb-*` в инвентаризации нет.

Рабочие secret-env файлы не включены в C: их нельзя читать/определять по содержимому в этой среде. Ничего из этой категории не удалено.

## D — решения пользователя

- `workspace/multi-llm-orchestrator/` и `workspace/sirchatalot-reference/`: nested Git, рекомендуем оставить локально и исключить из публичного Git. Не удалять.
- `/.codex/`, `/.claude/`: рекомендуем оставить локально и исключить личные настройки инструментов. Внимание: `.codex/config.toml` уже tracked, одна ignore-маска не снимет tracking; изменение индекса не входит в текущую задачу.
- `.agents/skills/`, `skills-lock.json`, `CLAUDE.md`: дополнительные agent-материалы вне явно заданного списка. Предложение — оставить на диске и в публичном срезе как дополнительные инструкции; содержимое не проходило отдельный аудит публикации. Подтвердить сохранение либо отдельно согласовать исключения. В текущем proposed ignore эти три записи НЕ исключаются.
- Git-корень — не отдельный файл: проект находится внутри `/Users/alesamarskij/projects/.git`. Рекомендация — будущий публичный срез оформлять отдельной копией/repo с корнем hr_bot; не менять общий Git и не staging соседних проектов. Это решение структуры публикации, а не автоматический git init исходной папки.

Корневого README.md нет: дополнять нечего, русский README.delta сохранён. Создание root README — отдельное расширение scope. Вложенного Git у source of truth нет; submodule/subtree/squash для него сейчас не требуется.

## Текущий счётчик наблюдаемых записей

{"D": 49, "B": 70, "A": 993, "C": 664}

Полная файловая привязка: `path_classification.json`; для неизвестных/закрытых данных нет заявления «без секретов».
