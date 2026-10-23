# Предложение release-cleanup — требуется подтверждение C и D

**Статус: approval_required.** Изменений исходного `.gitignore`, удаления, git add/commit/push нет. Разрешённый перевод четырёх Release/Docs-документов на русский выполнен отдельно; оригиналы сохранены в `docs_before/`. Код/config/tests/deploy не редактировались.

## 1. Предлагаемый полный .gitignore

Глобальные `artifacts/` и `coverage.json` заменяются на корневые `/artifacts/` и `/coverage.json`: иначе исчезают acceptance/provenance и сохранённый artifact coverage. Реальное хранилище `.agents` и его alias `.agent` учтены. Reference и tool-settings строки — часть ожидаемого решения D.

```gitignore
# Секреты: шаблон примера разрешён, рабочие значения не публикуются.
.env
.env.*
!.env.example
!**/.env.example
*.pem
*.key
secrets/

# Python: окружения, кэши и результаты сборки.
.venv/
__pycache__/
*.pyc
*.pyo
*.egg-info/
build/
dist/
.pytest_cache/
.mypy_cache/
.ruff_cache/
htmlcov/
*.coverage
/.coverage
/.coverage.*
/coverage.json
*.whl
*.tar.gz

# Локальные результаты прогонов и FAISS; product analytics/*.py остаются.
/artifacts/
/.faiss_indices/
analytics/unanswered.jsonl

# Транзиентные agent-файлы. .agent -> .agents: учитываем оба написания.
.agent/artifacts/**/tmp*/
.agent/artifacts/**/reviewer_tmp*/
.agent/artifacts/**/__pycache__/
.agent/artifacts/**/*.pyc
.agent/artifacts/**/.coverage*
.agent/artifacts/**/test_report.xml
.agent/artifacts/**/coverage_run.log
.agent/artifacts/**/*.log
.agents/artifacts/**/tmp*/
.agents/artifacts/**/reviewer_tmp*/
.agents/artifacts/**/__pycache__/
.agents/artifacts/**/*.pyc
.agents/artifacts/**/.coverage*
.agents/artifacts/**/test_report.xml
.agents/artifacts/**/coverage_run.log
.agents/artifacts/**/*.log

# Reference-клоны остаются локально. Forked source здесь не исключается.
/workspace/telegram-rag-bot/
/workspace/multi-llm-orchestrator/
/workspace/sirchatalot-reference/

# IDE/OS и локальные настройки инструментов; решение D перед применением.
.idea/
.vscode/
.DS_Store
*.swp
*.swo
/.codex/
/.claude/
```

## 2. Конкретные цели C: пока только список

`du -sh` запущен с исключениями закрытых имён (`-I .env -I '.env.*' -I .idea`), без чтения их содержимого. Logical bytes в последней колонке получены безопасным обходом без следования симлинкам. Размеры будут повторно проверены перед любой разрешённой операцией; если набор изменится, потребуется новое решение. Восстановительные копии не считаются автоматически существующими: временные данные не удаляются до подтверждения списка.

| Путь | du -sh | Logical bytes |
| --- | --- | ---: |
| `.agent/artifacts/backend_rest_adapters_checks/reviewer_tmp` | 164K | 103163 |
| `.agent/artifacts/backend_rest_adapters_checks/tmp` | 168K | 103157 |
| `.agent/artifacts/backend_rest_wiring_checks/tmp` | 0B | 0 |
| `.agent/artifacts/g0_reaudit/tmp` | 0B | 0 |
| `.agent/artifacts/backend_rest_i18n_checks/tmp_acceptance` | 44K | 18996 |
| `.agent/artifacts/backend_rest_i18n_checks/tmp_adapters` | 28K | 470 |
| `.agent/artifacts/backend_rest_i18n_checks/tmp` | 632K | 148004 |
| `.agent/artifacts/backend_rest_i18n_checks/tmp_coverage` | 356K | 25043 |
| `.agent/artifacts/backend_rest_i18n_checks/.coverage` | 52K | 53248 |
| `.agent/artifacts/backend_rest_i18n_checks/coverage_run.log` | 8.0K | 7102 |
| `.agent/artifacts/backend_rest_core_checks/tmp` | 676K | 13199 |
| `.agent/artifacts/infra_checks/tmp` | 780K | 779210 |
| `.agent/artifacts/backend_preflight_checks/reviewer_tmp` | 72K | 189 |
| `.agent/artifacts/backend_preflight_checks/tmp` | 72K | 189 |
| `/tmp/trb-sdist` | 120K | 122785 |

Итого 15 конкретных целей (14 в artifact storage и 1 вне проекта), 1 374 755 logical bytes. Временные тестовые bundles не являются продуктовым `config/`. Свежие JSON coverage, snapshot, acceptance `.py`, review/patch и release-документы сохраняются. Не-C XML/обычные логи будут только игнорироваться, не удаляться.

## 3. Вложенные Git и другие решения D

**Явное предупреждение:** в `workspace/multi-llm-orchestrator/.git` и `workspace/sirchatalot-reference/.git` обнаружены вложенные репозитории. При добавлении без исключений Git может записать embedded repo как gitlink; без корректного submodule-оформления публичный клон не получит его содержимое. Доступ к upstream может потребоваться, но не обязательно SSH: оба проверенных origin используют публичный HTTPS. Само `git add` не склеивает истории автоматически.

Рекомендуем reference clone, not source of truth: оставить оба локально, исключить из Git; **не удалять**. Upstream URLs отражены в русском ATTRIBUTION.md:

- https://github.com/MikhailMalorod/Multi-LLM-Orchestrator.git
- https://github.com/sazonovanton/SirChatalot.git

У `workspace/telegram-rag-bot-src/` собственного .git не найдено; исходники сохраняются обычным деревом. У installed audit copy `.git` также не найдено.

Дополнительно нужны решения:

1. Подтвердить ignore-only для двух reference-клонов и installed audit copy; директории оставить.
2. Подтвердить `.codex/`, `.claude/` как локальные tool-settings. Уже tracked `.codex/config.toml` не исчезнет из индекса от нового ignore. Индекс не меняю; перед будущей публикацией нужен отдельный явный выбор пользователя, что делать с этой записью.
3. Подтвердить сохранение `.agents/skills/`, `skills-lock.json`, `CLAUDE.md` как дополнительных agent-материалов, либо отдельно согласовать исключения.
4. Git-корень сейчас `/Users/alesamarskij/projects`, проект — подпапка hr_bot. Рекомендация: публичный Git создать в отдельной копии проекта после отдельного подтверждения, не выполнять `git add -A` в общем репозитории. Текущее задание не переинициализирует исходный Git.
5. Acceptance-тесты `*_checks/*.py` остаются на месте (вы уже явно выбрали оставить). Корневого README.md нет; переведённый README.delta остаётся основой будущего root README, без неразрешённого создания нового файла.

## 4. Git status: исходный и preview

Исходный project-scoped `git status --short -- .` (закрытые имена скрыты; содержимое не обследовалось):

```text
AM .codex/config.toml
AM workspace/README.md
?? .agent
?? .agents/
?? .dockerignore
?? .gitignore
?? AGENTS.md
?? CLAUDE.md
?? Dockerfile
?? analytics/
?? config/
?? deploy/
?? integrations/
?? skills-lock.json
?? tests/
?? workspace/multi-llm-orchestrator/
?? workspace/sirchatalot-reference/
?? workspace/telegram-rag-bot-src/
?? workspace/telegram-rag-bot/
```

`git ls-files -- .`: 2 записи. До cleanup tracked только `.codex/config.toml` и `workspace/README.md`; остальные A — кандидаты на последующее добавление, не уже tracked. Внешние соседние проекты не перечисляются и не меняются.

Изолированная модель будущего публичного Git: `/tmp/hr_bot_ignore_preview_gvdzn2l8`. Созданы только пустые модели безопасных имён и относительная ссылка `.agent -> .agents`, записан предложенный ignore; ни один исходный файл не скопирован и staging не выполнялся. `git status --short --ignored` в этой модели:

```text
?? .agent
?? .agents/
?? .dockerignore
?? .gitignore
?? AGENTS.md
?? CLAUDE.md
?? Dockerfile
?? analytics/
?? config/
?? deploy/
?? integrations/
?? skills-lock.json
?? tests/
?? workspace/
!! .agents/artifacts/backend_preflight_checks/reviewer_tmp/
!! .agents/artifacts/backend_preflight_checks/test_report.xml
!! .agents/artifacts/backend_preflight_checks/tmp/
!! .agents/artifacts/backend_rest_adapters_checks/reviewer_tmp/
!! .agents/artifacts/backend_rest_adapters_checks/tmp/
!! .agents/artifacts/backend_rest_core_checks/test_report.xml
!! .agents/artifacts/backend_rest_core_checks/tmp/
!! .agents/artifacts/backend_rest_i18n_checks/.coverage
!! .agents/artifacts/backend_rest_i18n_checks/coverage_run.log
!! .agents/artifacts/backend_rest_i18n_checks/test_report.xml
!! .agents/artifacts/backend_rest_i18n_checks/tmp/
!! .agents/artifacts/backend_rest_i18n_checks/tmp_acceptance/
!! .agents/artifacts/backend_rest_i18n_checks/tmp_adapters/
!! .agents/artifacts/backend_rest_i18n_checks/tmp_coverage/
!! .agents/artifacts/backend_rest_wiring_checks/test_report.xml
!! .agents/artifacts/backend_rest_wiring_checks/tmp/
!! .agents/artifacts/data_checks/test_report.xml
!! .agents/artifacts/g0_reaudit/build_source/telegram_rag_bot.egg-info/
!! .agents/artifacts/g0_reaudit/build_tools_install.log
!! .agents/artifacts/g0_reaudit/build_venv.log
!! .agents/artifacts/g0_reaudit/ensurepip.log
!! .agents/artifacts/g0_reaudit/pure_build_tools.log
!! .agents/artifacts/g0_reaudit/pytest.log
!! .agents/artifacts/g0_reaudit/pytest_runtime.log
!! .agents/artifacts/g0_reaudit/tools.log
!! .agents/artifacts/g0_reaudit/wheel_build.log
!! .agents/artifacts/infra_checks/test_report.xml
!! .agents/artifacts/infra_checks/tmp/
!! .claude/
!! .codex/
!! .venv/
!! workspace/multi-llm-orchestrator/
!! workspace/sirchatalot-reference/
!! workspace/telegram-rag-bot-src/build/
!! workspace/telegram-rag-bot-src/dist/
!! workspace/telegram-rag-bot-src/telegram_rag_bot.egg-info/
!! workspace/telegram-rag-bot/
```

Количество `!!` в модели: 37. Это **не** фактический статус исходного репозитория после применения: его индекс содержит ранее staged/tracked данные, а закрытые имена не моделировались. Не обещаем, что после реального применения число совпадёт без учёта этих различий.

`git check-ignore --no-index -v --stdin` в модели подтвердил:

```text
.gitignore:53:/workspace/telegram-rag-bot/	workspace/telegram-rag-bot/preview_sentinel.txt
.gitignore:54:/workspace/multi-llm-orchestrator/	workspace/multi-llm-orchestrator/preview_sentinel.txt
.gitignore:55:/workspace/sirchatalot-reference/	workspace/sirchatalot-reference/preview_sentinel.txt
.gitignore:11:.venv/	.venv/preview_sentinel.txt
.gitignore:43:.agents/artifacts/**/tmp*/	.agents/artifacts/backend_rest_core_checks/tmp/sample.py
.gitignore:32:analytics/unanswered.jsonl	analytics/unanswered.jsonl
```

Не игнорируются: `.agents/artifacts/coverage.json`, `.agents/artifacts/review.json`, acceptance `.py`, `.agents/roles/orchestrator.md`, `config/modes/it_support/faq.md`, forked `main.py`. Для Git фактические пути acceptance идут через `.agents`: проход за символическую ссылку `.agent` не используется как доказательство Git-tracking.

## 5. Что обязано остаться в публичном срезе

Полный список A: `path_classification.json`, сводка `classification.md`. Особо сохраняются forked source/tests, root integrations/analytics Python, config/bundles/locale, deploy/load runner, Dockerfile/.dockerignore/.gitignore, AGENTS, `.agent` + `.agents/{roles,playbooks,prompts}`, обязательные release/G2/review/coverage/patch файлы, acceptance `.py`, superseded provenance, snapshots/manifests/inventories/baseline JSON. Ни одна маска не скрывает `config/modes/` или `.agents/roles/`. Фактического staging нет.

## 6. Ограничения env-проверки и безопасный шаблон

Высокоприоритетное ограничение среды запрещает доступ к `.env` и `.env.*`, включая пример по совпадению маски. Их наличие, содержимое, действительность секретов и текущий ignore-статус не проверены; нельзя заявить «реальных секретов нет» или «публичный срез безопасен». Ни один такой файл не удаляется. Предупреждение о **конкретном** существующем .env без проверки дать невозможно. Проверку должен выполнить оператор вне этой среды. Шаблон для ручного создания/сверки примера (не реальные значения):

```dotenv
TELEGRAM_TOKEN=
GIGACHAT_KEY=
YANDEX_API_KEY=
YANDEX_FOLDER_ID=
ADMIN_IDS=
TICKETING_WEBHOOK_URL=
HR_CHAT_ID=
```

В proposed ignore есть `.env`/`.env.*` и явное исключение `!.env.example`; фактический файл не открывался и не создавался. Если пример уже есть, не перезаписывать его автоматически.

## 7. Ограничение воспроизводимости публичных тестов

`workspace/telegram-rag-bot-src/tests/test_hr_adapters.py:155` и `:157` проверяют hash двух файлов из installed audit copy. Локальная ignore-only операция оставит их на месте, поэтому не должна сломать локальный прогон. Но после исключения audit copy из Git два теста в чистом публичном клоне потребуют отдельно подготовленной audit copy с исходными хешами. **Самодостаточность чистого клона не подтверждена.** Код/тесты не меняются; решение bootstrap/provenance — отдельная задача, не скрытый fix cleanup. До публикации это нужно принять как явную предпосылку либо отдельно устранить вне текущего scope.

## 8. Проверки и точка остановки

Сделано: инвентаризация без закрытых путей; безопасные размеры; nested Git/origin; read-only исходный статус; изолированная ignore-модель без git add; защитные и сохраняемые пути; перевод документации. Ничего из C не удалено, исходный .gitignore неизменён.

**После подтверждения** допустимы только согласованные C/D действия и замена ignore на полный текст выше. Затем frozen44+8 re-check, тесты316/3 и coverage78.006%, независимый reviewer и simulated clone с отдельно согласованным staging только в копии. В этой фазе тесты/coverage и настоящий simulated clone ещё **не выполнялись**; ignore preview не выдаётся за clone test. Никогда не staging оригинал, не commit/push, не закрывать G2.

**STOP: ожидаются решения по C и D.**
