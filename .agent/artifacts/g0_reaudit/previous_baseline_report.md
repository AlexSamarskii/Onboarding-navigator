# G0 — baseline audit

- **baseline_status: fail**
- **G0: need_info (не пройден)**
- Объект: `workspace/telegram-rag-bot` — установленное дерево PyPI с зависимостями, не исходный checkout.
- Версия **telegram-rag-bot 0.14.6** явно принята пользователем; **multi-llm-orchestrator 0.9.1**. Основание: соответствующие `*.dist-info/METADATA` в целевом каталоге.
- Только G0: исходники не изменены, зависимости не устанавливались, TZ Agent не вызывался, обращения к LLM/Telegram не выполнялись.

## Карта «как есть»

Стек: Python >=3.11, python-telegram-bot 21.x, asyncio/aiohttp, LangChain/langchain-classic, multi-LLM Router (GigaChat/YandexGPT), FAISS/OpenSearch, PyYAML/Pydantic, memory/Redis sessions, Prometheus. Зависимости: `workspace/telegram-rag-bot/telegram_rag_bot-0.14.6.dist-info/METADATA`.

CLI `telegram-bot` и `telegram-rag-bot` → `telegram_rag_bot.__main__:main` (`workspace/telegram-rag-bot/telegram_rag_bot-0.14.6.dist-info/entry_points.txt`). Команды `init/run/rebuild/version`: `workspace/telegram-rag-bot/telegram_rag_bot/__main__.py`; async bootstrap: `workspace/telegram-rag-bot/telegram_rag_bot/main.py`.

Конфигурационные точки и hotspots, пути относительно `workspace/telegram-rag-bot/`:

| Путь | Назначение / состояние |
|---|---|
| `telegram_rag_bot/config_loader.py` | YAML, подстановка переменных, обязательный `modes.directory` |
| `telegram_rag_bot/mode_loader.py` | Bundle: `mode.yaml`, `files.system_prompt`, `files.faq`, optional `files.examples` |
| `telegram_rag_bot/templates/config.yaml.template` | Поставленный шаблон: старые inline modes, **нет `modes.directory`**; текущий loader такой формат отвергает |
| `telegram_rag_bot/templates/faq_example.md` | Пример FAQ, не действующий HR bundle |
| `telegram_rag_bot/embeddings/factory.py` | local/HuggingFace, GigaChat, Yandex; `sentence-transformers` — optional extra `local` согласно METADATA |
| `telegram_rag_bot/vectorstore/factory.py` | FAISS/OpenSearch |
| `telegram_rag_bot/langchain_adapter/rag_chains.py` | RAGChainFactory, промпты, chunking, индексы |
| `telegram_rag_bot/handlers.py` | Telegram-команды, сообщения, выбор режима |

`config/config.yaml` и runtime mode bundles в целевом каталоге отсутствуют. Качественные hotspot_score в repo_map отражают связь с тематикой, не историческую частоту изменений. Ядро `orchestrator/router.py` и RAG/retrieval защищены ограничениями задачи; предложений изменений нет.

## Проверенный baseline

Использован Python **3.13.17** (системный python3=3.9.6 не соответствует требованиям). Рабочий каталог: `workspace/telegram-rag-bot`; PYTHONPATH указывает на него. Чистое ограниченное окружение, отключена запись bytecode, HuggingFace offline; лимит каждой CLI-команды 30 секунд, таймаутов не было.

| Команда | Результат |
|---|---|
| `python3.13 -B -m telegram_rag_bot --help` | pass, exit 0; CLI импортируется и показывает команды |
| `python3.13 -B -m telegram_rag_bot version` | pass, exit 0: v0.14.6 |
| `python3.13 -B -m telegram_rag_bot run` | fail, exit 1: `config/config.yaml not found`; Telegram не запускался |
| `python3.13 -B -m pytest --version` | exit 1: `No module named pytest`; suite не запускалась |
| AST parse пакетов telegram_rag_bot, orchestrator и поставленных tests | 62 Python-файла, 0 синтаксических ошибок; **не сборка и не тесты** |

Точные argv, stdout и коды: `.agent/artifacts/g0_runtime_checks.json`; AST: `.agent/artifacts/g0_syntax_check.json`. Полноценный запуск приложения не подтверждён. В installed target отсутствуют `pyproject.toml`, `setup.py`, `requirements.txt`, `Dockerfile`; штатная сборка этого каталога не выполнена.

## Тесты, покрытие и deployment

В `workspace/telegram-rag-bot/tests/` есть **11 `test_*.py`**, `conftest.py` и `load_test.py`. Принадлежность целевому пакету подтверждена `workspace/telegram-rag-bot/telegram_rag_bot-0.14.6.dist-info/RECORD`. Темы: mode/config, handlers/main/hot reload, RAG, embeddings/vectorstore, sessions, feedback, usage tracking. Фреймворк pytest + pytest-asyncio, pytest-cov объявлен dev extra. **tests.baseline_status: not_run; coverage: unknown**. Результаты тест-кейсов отсутствуют; синтаксический разбор их не заменяет.

В целевом installed target нет Docker/K8s-артефактов. `/health` и `/metrics` реализованы в `workspace/telegram-rag-bot/telegram_rag_bot/main.py`; метрики — `workspace/telegram-rag-bot/telegram_rag_bot/utils/metrics.py`. Их наличие не доказывает готовность deployment.

Reference `workspace/multi-llm-orchestrator`: отдельный v0.9.1 с `pyproject.toml`, `src/orchestrator`, `tests/test_router.py` и `src/orchestrator/retrieval/async_faiss.py`. Reference `workspace/sirchatalot-reference`: отдельный Telegram/OpenAI/ChromaDB/SQLite/MCP-стек (`requirements.txt`), `main.py`, `Dockerfile`, `tests/test_rag.py`. Reference-проверки не запускались; их тесты и Dockerfile не подменяют baseline целевого пакета.

## Недостающие данные и безопасные допущения

1. Обезличенные runtime YAML и mode bundles актуального формата (промпт/FAQ). Пока каталог считается библиотечной поставкой, offline-only; рабочий бот не подтверждён. Реальные токены не запрашиваются.
2. Подготовленное Python >=3.11 окружение с pytest/pytest-asyncio и, для покрытия, pytest-cov либо воспроизводимые исходные результаты тестов. Пока tests=not_run, coverage=unknown.
3. Исходная поставка telegram-rag-bot 0.14.6 с build manifest/инструкцией сборки; Docker/K8s-артефакты — если такой запуск входит в baseline. Пока доступен installed package, build=not_run.

G0 не объявляется pass: пробный `run` падает, тесты и сборка не подтверждены. Исключение playbook для известных падений тестов не превращает отсутствие их запуска в pass. Остановка после G0, без TZ Agent и реализации.
