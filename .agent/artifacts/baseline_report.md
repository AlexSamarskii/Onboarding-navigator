# G0 — повторный baseline audit

- **baseline_status: pass**; **G0: pass** — сборка подтверждена пользовательским результатом и проверкой wheel на диске; полный runtime не проверен.
- Версия **telegram-rag-bot 0.14.6**, orchestrator **0.9.1**; основной объект `workspace/telegram-rag-bot`, исходная поставка `workspace/telegram-rag-bot-src`.
- Проверенное окружение `.venv`: **Python 3.13.17, pytest 9.1.1, pytest-asyncio 1.4.0**. Это реальные значения, не placeholder из пользовательского сообщения.
- Исходники не изменены. Только G0; TZ Agent не вызывался, живые Telegram/LLM-запросы не выполнялись.

## Карта и конфигурация

Стек: Python >=3.11, python-telegram-bot 21.x, asyncio/aiohttp, LangChain/langchain-classic, multi-LLM fallback GigaChat/YandexGPT, FAISS/OpenSearch, YAML/Pydantic, memory/Redis, Prometheus. Основание: `workspace/telegram-rag-bot/telegram_rag_bot-0.14.6.dist-info/METADATA` и `workspace/telegram-rag-bot-src/pyproject.toml`.

Entry points `telegram-bot` и `telegram-rag-bot` → `telegram_rag_bot.__main__:main`; async bootstrap — `telegram_rag_bot.main.main`. Файлы: `workspace/telegram-rag-bot/telegram_rag_bot/{__main__,main}.py`, `workspace/telegram-rag-bot/telegram_rag_bot-0.14.6.dist-info/entry_points.txt`.

**Фактический bundle находится в корне проекта:** `config/modes/it_support/{mode.yaml,system_prompt.md,faq.md}`. В заявленном `workspace/telegram-rag-bot/config/modes/it_support` его нет. `ModeLoader` успешно загрузил `it_support`, FAQ указывает на корневой `config/modes/it_support/faq.md`. Однако и корневой `config/config.yaml`, и `workspace/telegram-rag-bot/config/config.yaml` отсутствуют; runtime-привязка через `modes.directory` не предоставлена.

Тематические hotspots, пути относительно `workspace/telegram-rag-bot/`:

| Путь | Роль |
|---|---|
| `telegram_rag_bot/config_loader.py` | YAML, переменные, обязательный `modes.directory`, разрешаемый относительно config.yaml |
| `telegram_rag_bot/mode_loader.py` | Bundles, prompt/FAQ, optional examples |
| `telegram_rag_bot/templates/config.yaml.template` | Legacy inline modes; нет обязательного `modes.directory`, несовместим с текущим loader |
| `telegram_rag_bot/handlers.py` | Telegram-команды/сообщения, режимы |
| `telegram_rag_bot/langchain_adapter/rag_chains.py` | RAG, промпты, chunking, индексы |
| `telegram_rag_bot/embeddings/factory.py` | local/HuggingFace, GigaChat, Yandex |
| `telegram_rag_bot/vectorstore/factory.py` | FAISS/OpenSearch |

Ядро fallback (`orchestrator/router.py`) и RAG/retrieval не изменены. Hotspot scores в repo_map качественные, не история churn. Optional `sentence-transformers` и модели не загружались.

## Проверки

Рабочий каталог проверок — `.agent/artifacts/g0_reaudit/run`; чистое ограниченное окружение, bytecode и pytest cache отключены. Для tests и bundle check audit hook блокировал `.env*`/`.idea` чтение, реальные socket connect/DNS и запись вне artifacts. Ограничение pytest — 120 секунд, CLI/bundle — 30 секунд; эти проверки без таймаутов.

| Проверка | Результат |
|---|---|
| `.venv/bin/python -B -m telegram_rag_bot --help` | exit 0 |
| `.venv/bin/python -B -m telegram_rag_bot version` | exit 0, v0.14.6 |
| ModeLoader корневого `config/modes` | exit 0, загружен `it_support` |
| 11 целевых `tests/test_*.py`, pytest с явно подключённым pytest-asyncio | **exit 0: 211 passed, 3 skipped, 4 warnings, 0.69 s** |
| `uv build --wheel` в `workspace/telegram-rag-bot-src` | пользователь сообщил `Successfully built`; wheel найден, разрешённые метаданные проверены |

Build manifest: `workspace/telegram-rag-bot-src/pyproject.toml`, версия 0.14.6. Пользователь сообщил успешный `uv build --wheel`; результат `workspace/telegram-rag-bot-src/dist/telegram_rag_bot-0.14.6-py3-none-any.whl` **существует**. В ZIP прочитаны только `METADATA`, `WHEEL`, `entry_points.txt`: Name=telegram-rag-bot, Version=0.14.6, Requires-Python>=3.11, Tag=py3-none-any, оба CLI ведут в `telegram_rag_bot.__main__:main`. Это подтверждает результат сборки, а не полноценный запуск Telegram. Provenance команды — **user_report**, наличие и метаданные wheel проверены локально. Evidence: `.agent/artifacts/g0_user_build_evidence.json`.

Предыдущие попытки сборки аудитора не завершились из-за отсутствующего tooling и ошибки определения macOS host Python; сырые логи сохранены как история проверок. Они больше не блокируют G0 после появления проверенного wheel. Повторная сборка и повтор suite не выполнялись.

Точные argv/коды: `.agent/artifacts/g0_reaudit/{runtime_checks,build_checks,isolated_build_checks,final_build_checks,test_checks}.json`. Лог suite: `.agent/artifacts/g0_reaudit/pytest.log`, JUnit: `.agent/artifacts/g0_reaudit/pytest_report.xml`. Вспомогательный тестовый runner — `.agent/artifacts/g0_reaudit/test_runner.py`.

## Тесты, ограничения, deployment

Тестируются именно 11 модулей `workspace/telegram-rag-bot/tests/test_*.py`; принадлежность подтверждается `workspace/telegram-rag-bot/telegram_rag_bot-0.14.6.dist-info/RECORD`. Dependency tests и `load_test.py` не запускались. **tests.baseline_status: pass**; 3 skips явно сохранены. Предупреждения: deprecation langchain-community и 3 RuntimeWarning о coroutine `_send_usage_to_platform` never awaited. **Покрытие unknown**: coverage/pytest_cov отсутствуют, измерение не выполнялось.

В целевом installed target Docker/K8s-артефактов нет; `/health` и `/metrics` реализованы в `workspace/telegram-rag-bot/telegram_rag_bot/main.py`, метрики — `utils/metrics.py`. Reference `workspace/multi-llm-orchestrator` содержит `pyproject.toml`, `src/orchestrator`, тесты; `workspace/sirchatalot-reference` содержит отдельный стек (`requirements.txt`), `Dockerfile`, `main.py`, тесты. Их проверки не подменяют целевой baseline.

## Итог G0 и ограничения

**G0 пройден:** доступны карта, entry points и конфигурационные точки, целевые тесты выполнены, результат сборки 0.14.6 подтверждён. Недостающих данных, блокирующих G0, нет.

**full_runtime: not_verified.** `config/config.yaml` по-прежнему отсутствует в корне и target, существующий корневой bundle не привязан runtime-конфигурацией. Покрытие неизвестно; 3 skips и 4 warnings сохранены. Эти ограничения не подменяются успешной сборкой, но не блокируют текущий G0.

Repo Auditor останавливается после G0. TZ Agent не вызывался; решение о следующем этапе принимает Orchestrator.
