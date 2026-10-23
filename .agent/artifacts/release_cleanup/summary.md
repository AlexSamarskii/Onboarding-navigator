# Release hygiene и publication prep — итог выполненных действий

## Решения пользователя

Cleanup C/D подтверждены; B2 выбран C; B3 выбран «оставить локально, индекс не трогать». Рабочий конфиг Codex не удалялся; к моменту B3 он уже отсутствовал в актуальном индексе. Git-корень теперь hr_bot; относительно ранней инвентаризации он изменился вне действий агента. Родительский общий индекс и индекс hr_bot не изменялись нашими командами.

## .gitignore

Применена выбранная C-версия: байт-в-байт [gitignore_applied.txt](gitignore_applied.txt). Секретные/runtime/IDE/reference/tool-settings маски сохранены; .env.example разрешён исключением. Вложенный artifact coverage и acceptance/provenance не скрываются. Семь точечных temp/build-исключений B2 не удаляют содержимое; фиксируют0symlink в публичном индексе.

## Удалено C

Перед удалением повторныйdu всех15 целей точно совпал с proposal; [preflight_recheck.json](preflight_recheck.json). Размеры в таблице — до удаления. Дополнительных целей не удаляли.

| Путь | Размер до удаления |
| --- | --- |
| `.agent/artifacts/backend_rest_adapters_checks/reviewer_tmp` | 164K |
| `.agent/artifacts/backend_rest_adapters_checks/tmp` | 168K |
| `.agent/artifacts/backend_rest_wiring_checks/tmp` | 0B |
| `.agent/artifacts/g0_reaudit/tmp` | 0B |
| `.agent/artifacts/backend_rest_i18n_checks/tmp_acceptance` | 44K |
| `.agent/artifacts/backend_rest_i18n_checks/tmp_adapters` | 28K |
| `.agent/artifacts/backend_rest_i18n_checks/tmp` | 632K |
| `.agent/artifacts/backend_rest_i18n_checks/tmp_coverage` | 356K |
| `.agent/artifacts/backend_rest_i18n_checks/.coverage` | 52K |
| `.agent/artifacts/backend_rest_i18n_checks/coverage_run.log` | 8.0K |
| `.agent/artifacts/backend_rest_core_checks/tmp` | 676K |
| `.agent/artifacts/infra_checks/tmp` | 780K |
| `.agent/artifacts/backend_preflight_checks/reviewer_tmp` | 72K |
| `.agent/artifacts/backend_preflight_checks/tmp` | 72K |
| `/tmp/trb-sdist` | 120K |

Детальная запись и внешний backup: [deletions.json](deletions.json). Backup проверен по508 обычным файлам и157link-targets; полный B2-backup отдельно сохранён в /tmp. Восстановление не потребовалось.

## Сохранено

Forked source, runtime Python/config/deploy, все acceptance `.py`, snapshots/manifests, coverage/review/patch, release-документы и framework roles/playbooks/prompts/skills на месте. Reference-клоны/audit copy/.codex/.claude оставлены на диске и только игнорируются. Skills43файла в9директориях и root skills-lock.json сохранены. Тексты четырёх публичных Release/Docs-файлов на русском; MIT notice и команды не переводились.

## Проверки

- Все15 C-целей отсутствуют. Проверено отсутствие новых tmp*/reviewer_tmp*/pycache/coverage-runtime целей из оговорённых масок; расширения списка удаления не было.
- Source frozen44/44 unchanged. Из исторического i18n-набора8файлов7unchanged; `test_hr_adapters.py` намеренно изменён по явно разрешённому B1, который снял freeze именно с него. Не выдаём это за8/8unchanged. `test_hr_acceptance.py` отдельно SHA-verified unchanged. Из11infra-субъектов10unchanged, разрешённый .gitignore изменён.
- Локально и в чистом code-slice **317 passed,3 skipped**. Ранее316 сохранены; +1 — новый B1negative-control.
- Coverage **2238/2869=78.006273963%**, unchanged. Отчёт [coverage_after_cleanup.json](coverage_after_cleanup.json).
- B1: локальные4hash checks pass; без audit copy installed-orchestrator4pass; при блокировке отсутствующей зависимости2sourcepass+2dependency skip; mutation-control passes. Для изолированного отсутствия orchestrator нужен `--noconftest`, поскольку общий conftest импортирует приложение с обязательной зависимостью.
- Финальная публичная модель `/tmp/hr_bot_clone_test`:393staged-записи,0symlinkmode120000, real.agent, нет .agents/venv/audit/reference/.codex. .git=2.03515625MiB. Только в копии выполненgitadd. Env-pattern пути не читались/не копировались, поэтому это модель для проверки кода, не автоматически публикуемый архив. [final_clone_report.json](final_clone_report.json).
- Git status/check-ignore после применения: [inventory_after.json](inventory_after.json),30ignored-групп на момент снимка. Это фактическое состояние нового Git-корня, не исходные staged-статусы из старого общего репозитория.

## Env-проверка

Из-за ограничения среды агент не обращался к .env/.env.* и не создавал пример. Пользователь явно подтвердил вручную готовность примера со всеми7именами и исключение рабочих env-файлов из публикации: [env_manual_confirmation.json](env_manual_confirmation.json). Это внешнее подтверждение пользователя, не результат чтения агентом. Правила whitelist проверены по тексту предложенного/применённого ignore.

## B1/B2/B3 как pre-publication gate

- B1: выполнен в тестовом scope; JSON содержит исходные baseline-константы, не live-generated hashes. Проверка clean clone прошла.
- B2: выполнен C; структура переносима без корневого symlink. Исторические строки старого имени в inventory/proposals сохранены; глобальный sed не применялся. Локальные ignored fixtures содержат143symlink, публичный индекс —0. Внешний discovery навыков и запуск Windows не проверялись и не объявляются доказанными.
- B3: выполнен LOCAL/UNSTAGE-noop по выбору пользователя; конфиг не менялся и не публикуется, gitrmcached не нужен при отсутствующей записи. Только generic-классификация без значений.

G2 не закрыт. AC-N01/N02/N08/N09 остаютсяpending_environment. Docker/K8s/Telegram/HTTP/LLM не запускались; установку клона выполнялиoffline. Коммитов/push/staging в оригинале нет.

После независимого ревью оба временных клона и временное виртуальное окружение удалены. Внешние backup-архивы сохранены. Следующий шаг — ручные `git add -A` и `git status` в подтверждённом корне hr_bot после просмотра результата; агент этого не выполняет.
