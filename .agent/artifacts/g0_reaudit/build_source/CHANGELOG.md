# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.14.6] - 2026-03-16

### Fixed

- `AttributeError: 'UsageData' object has no attribute 'telegram_user_id'` — `UsageData` from
  `orchestrator` does not carry `telegram_user_id` (Telegram context, not LLM data). Use
  `getattr(data, "telegram_user_id", None)` instead of direct attribute access; `None` is
  acceptable per Issue #15 comment and matches the `usage_logs.telegram_user_id` nullable column.

## [0.14.5] - 2026-03-16

### Fixed

- `AttributeError: 'UsageData' object has no attribute 'get'` in `_send_usage_to_platform` —
  `telegram_user_id` field was using plain `data.get()` without `isinstance(data, dict)` guard,
  while all other fields in the same function already used the correct dual-access pattern.
  Regression introduced when platform 2a0910d (Trial & Quota Enforcement Week 12) changed
  `UsageData` from TypedDict to a typed object. Fixes `usage_logs` not writing since 2026-03-15.

## [0.14.3] - 2026-03-07

### Fixed

- Usage tracking POST to Platform API not executing when bot runs in `asyncio.to_thread()` worker context (ensure_future + shield + wait_for pattern). Postmortem: POSTMORTEM_usage_tracking_2026-03.md

## [0.14.1] - 2026-03-05

### Fixed
- fix(#18): asyncio background tasks теряются GC в Python 3.11+ —
  Task объект теперь сохраняется в _background_tasks set до завершения
  (официальный паттерн из Python docs / asyncio.create_task)

## [0.14.0] - 2026-03-04

### Fixed
- fix(#17): usage_callback не вызывался в Shared Bot Pool —
  `create_track_usage_callback` недоступна в public API пакета

### Added
- Новый модуль `telegram_rag_bot/usage_tracking.py`
- `create_track_usage_callback` теперь доступна как
  `from telegram_rag_bot import create_track_usage_callback`
- Shared Bot Pool теперь может передавать usage_callback в Router
  без зависимости от внутренностей main.py

## [0.13.4] - 2026-03-01

### Fixed
- **[CRITICAL] Stale session mode KeyError (Issue #16)**: Bot no longer crashes when user session contains a mode (e.g. `it_support`) that was removed from `config/modes/` after Bundle Architecture migration.
  - **handlers.py**: `DEFAULT_MODE` now resolved dynamically from `config["modes"].keys()[0]` (instance variable in `__init__`); removed hardcoded class constant. `mode_display_names` built from config.
  - **session_manager.py**: `_default_session()` no longer sets `"mode": "it_support"`; mode is resolved by handler via `DEFAULT_MODE`.
  - **handlers.py**: Defensive `.get()` for `timeout_seconds` and `faq_file` when reading mode config (fallback to `DEFAULT_MODE` or empty).
- **main.py**: Startup logging of available modes and default mode for easier tenant/deploy debugging.

### Added
- **Test**: `test_stale_mode_falls_back_to_default` (4 assertions: no KeyError, reply sent, session mode updated to first config mode, RAG chain created with resolved mode).
- **Fixture**: `mock_config_single_unknown_mode` in `conftest.py` for stale-session fallback tests.

Closes #16.

## [0.13.0] - 2026-02-22

### Fixed
- **[CRITICAL] gigachat.py**: Lazy `httpx.AsyncClient` initialization —
  moved from `__init__` to `_get_client()` async method.
  Fixes `RuntimeError: Event loop is closed` on `/reload_faq`
  in Platform SaaS subprocess architecture (#BUG1, Issue #11).
- **[HIGH] gigachat.py**: OAuth2 auth scheme corrected —
  `Bearer {api_key}` → `Basic {base64(api_key)}`.
  Fixes HTTP 401 on GigaChat `/api/v2/oauth` endpoint (#BUG2, Issue #11).
- **[HIGH] yandex.py**: Same lazy `httpx.AsyncClient` initialization fix
  applied to prevent identical `Event loop is closed` regression
  for Yandex embeddings tenants (#BUG1-Yandex).

### Tests
- Updated 2 tests: `verify_to_httpx` → `lazy_init_passes_verify_to_httpx`
- Fixed 4 existing async tests: added `mock_client.is_closed = False`
- Added 5 new tests covering lazy init and Basic auth correctness

## [0.12.0] - 2026-02-07

### Changed
- **UX improvement**: Removed "📌 Режим: Default Mode" line from `/start` welcome message for single-mode bots (95% of deployments). Multi-mode bots still show "📌 Текущий режим: ..." for mode selection. Fixes [#10](https://github.com/MikhailMalorod/telegram-bot-universal/issues/10).

### Added
- **Test**: `test_cmd_start_single_mode_no_mode_line` to prevent regression of Issue #10.

## [0.11.3] - 2026-02-01

### Fixed

#### SSL verification propagation to ProviderConfig (#9) [CRITICAL]
- **Issue #9**: `verify_ssl_certs` from config.yaml now correctly propagates to Multi-LLM-Orchestrator `ProviderConfig`
- **Production fix**: Chat API requests no longer fail with `SSL: CERTIFICATE_VERIFY_FAILED` when `verify_ssl_certs: false` is set
- **Affected components**: `main.py` (create_router, build_providers_list), `__main__.py` (CLI rebuild)
- **Details**:
  - 6 code locations updated (GigaChat + YandexGPT providers in 3 functions)
  - Normalization: `None → True` (secure by default)
  - Backward compatible: old configs without `verify_ssl_certs` continue to work (default `True`)
- **Testing**: Added regression test `test_provider_config_propagates_verify_ssl_false()`

**Full Changelog**: https://github.com/MikhailMalorod/telegram-bot-universal/compare/v0.11.2...v0.11.3

## [0.11.2] - 2026-01-26

### 🐛 Bug Fixes

#### GigaChat OAuth2 Authentication (#8)
- **Changed**: OAuth2 authentication from `Basic` to `Bearer` method
- **Reason**: Match Multi-LLM-Orchestrator implementation and GigaChat API best practices
- **Impact**: Eliminates 400 Bad Request errors during authentication
- **Files**: `telegram_rag_bot/embeddings/gigachat.py`
- **Details**:
  - Replace `base64.b64encode(api_key)` with direct `api_key` usage
  - Add `uuid.uuid4()` for unique RqUID per request (OAuth2 spec compliance)
  - Remove unused `import base64`
- **Testing**: ✅ OAuth2 token: 200 OK, Embeddings API: 200 OK

#### FAISS Index Search TypeError (#8)
- **Fixed**: `TypeError: 'str' object is not callable` when querying FAISS index
- **Root cause**: FAISS expected callable `embed_query()` but received string
- **Solution**: Created `LangChainEmbeddingsWrapper` class
- **Files**: 
  - `telegram_rag_bot/langchain_adapter/rag_chains.py`
  - `telegram_rag_bot/vectorstore/local_faiss.py`
- **Details**:
  - Implement `langchain_core.embeddings.Embeddings` interface
  - Sync wrappers for async embeddings providers (GigaChat/Yandex)
  - Handle event loop correctly (`asyncio.run` + `ThreadPoolExecutor` fallback)
  - Use wrapper in both `rebuild_index()` and `load_index()`
- **Testing**: 
  - ✅ `/reload_faq`: Index creation works
  - ✅ User queries: Bot responds correctly (no errors)
  - ✅ FAISS search: Embeddings computed successfully

### 📚 Documentation
- Updated PROJECT-TRUTH.md: Removed Issue #8 from KNOWN ISSUES, added Week 5 Day 35 completion

### 🧪 Testing
- Validated with production FAQ files (hr_support, it_support, sales_faq)
- Confirmed bot responds to user queries without errors
- All FAISS indices created and loaded successfully

### 🚀 Deployment Notes
- **Breaking changes**: None
- **Migration required**: Rebuild FAISS indices after update (run `/reload_faq` in Telegram)
- **Backward compatibility**: Full (fallback to sync retriever if needed)

### 📊 Metrics
- Error rate: 0% (previously 100% on queries)
- Index rebuild: ✅ All modes working
- Response latency: ~1-2s per query (as expected)

**Full Changelog**: https://github.com/MikhailMalorod/telegram-bot-universal/compare/v0.11.1...v0.11.2

## [0.11.1] - 2026-01-22

### Fixed

- **Issue #7**: Added `verify_ssl_certs` support for GigaChat and Yandex embeddings providers
  - `GigaChatEmbeddingsProvider` now respects `verify_ssl_certs` config parameter
  - `YandexEmbeddingsProvider` now respects `verify_ssl_certs` config parameter
  - Fixes SSL certificate verification errors on Yandex Cloud with Russian CA

### Added

- **Issue #6**: Custom greeting support from `system_prompt.md`
  - `ModeLoader` now parses `# ПРИВЕТСТВИЕ` section from system_prompt.md
  - `/start` command handler uses custom greeting if available
  - Falls back to default greeting if no custom greeting provided

### Tests

- Added 4 unit tests for embeddings `verify_ssl_certs` support
- Added 3 unit tests for custom greeting parsing and usage

**Full Changelog**: https://github.com/MikhailMalorod/telegram-bot-universal/compare/v0.11.0...v0.11.1

## [0.11.0] - 2026-01-18 (Platform SaaS Integration - Shared Bot Pool)

### Added

**HTTP Server Configuration** ([#3](https://github.com/MikhailMalorod/telegram-bot-universal/issues/3))
- `http_server.enabled` config option (default: `true`)
- `http_server.port` config option (default: `8000`, customizable)
- Disable HTTP server for Shared Bot Pool deployments
- Prevents port conflicts when running 100+ bots in single process

**Pre-initialized Embeddings Instance** ([#4](https://github.com/MikhailMalorod/telegram-bot-universal/issues/4))
- `embeddings_instance` optional parameter in `RAGChainFactory.__init__`
- Enables shared embeddings across multiple bot instances
- **10x memory reduction**: 20GB → 2GB for 100 bots (Shared Pool)
- **8s faster startup** per bot (no model loading)
- **10x cost reduction**: ₽15,000/mo → ₽2,000/mo (VPS)

**Async FAISS Retrieval Support** ([#5](https://github.com/MikhailMalorod/telegram-bot-universal/issues/5))
- `retrieval.async_mode` config option for GIL mitigation
- Integrates with Multi-LLM-Orchestrator v0.9.0 `AsyncFAISSRetriever`
- **p99 latency: 4ms** for 10 concurrent queries (1247x better than sync blocking)
- Supports 100+ concurrent bots without performance degradation

### Changed

- `RAGChainFactory.__init__`: `embeddings_config` now optional (can use `embeddings_instance` instead)
- `requirements.txt`: Updated `multi-llm-orchestrator` dependency to `>=0.9.0,<1.0.0` with `[retrieval]` extra
- `main.py`: HTTP server creation now conditional (respects `http_server.enabled` config)

### Breaking Changes

**None** - All changes are opt-in and backward compatible.

### Migration Guide

**No migration required**. Existing configurations continue to work unchanged.

**To enable new features**:

1. **Shared Pool mode** (optional):
```python
from telegram_rag_bot.embeddings.factory import EmbeddingsFactory

shared_embeddings = EmbeddingsFactory.create(config["embeddings"])
rag_factory = RAGChainFactory(..., embeddings_instance=shared_embeddings)
```

2. **Disable HTTP server** (optional):
```yaml
http_server:
  enabled: false  # For Shared Pool deployments
```

3. **Async FAISS** (optional):
```yaml
retrieval:
  async_mode: true  # For 10+ concurrent bots
```

### Performance Impact

**Shared Pool mode** (100 bots):
- Memory: 20GB → 2GB (10x reduction)
- Startup: 800s → 80s (10x faster)
- Cost: ₽15,000/mo → ₽2,000/mo (10x cheaper)

**Async FAISS** (100 concurrent queries):
- p99 latency: 10s+ → 5s (50% improvement)
- GIL contention: eliminated
- CPU utilization: 1 core → multi-core

### Dependencies

- **Required**: `multi-llm-orchestrator[langchain,retrieval]>=0.9.0,<1.0.0`
- **Optional**: For GPU acceleration use `faiss-gpu` instead of `faiss-cpu`

### Notes

- Shared Pool mode designed for Platform SaaS multi-tenant deployments
- HTTP server can be disabled when monitoring managed externally (e.g., Kubernetes liveness probes)
- Async FAISS recommended for 10+ concurrent bots (GIL mitigation)
- Coverage maintained at 76.73% (1.73% margin above 75% threshold)

**Issues**: Closes #3, #4, #5  
**Pull Request**: #XX (will be added when PR is created)

## [0.10.0] - 2026-01-14

### Changed
- **Optional dependencies for local embeddings** (addresses Platform SaaS request)
  - Core dependencies: ~500 MB (telegram, langchain, faiss, multi-llm-orchestrator)
  - Local embeddings: ~20 GB (torch, transformers, sentence-transformers) — optional extra
  - **Default install** (`pip install telegram-rag-bot`): API-only, no torch
  - **Local install** (`pip install telegram-rag-bot[local]`): includes torch/transformers
  - **Backward compatible**: existing users with API embeddings (gigachat/yandex) не пострадают

### Migration Guide
If you use local embeddings (`embeddings.type: "local"`):
```bash
pip install telegram-rag-bot[local]
```
If you use API embeddings (`gigachat`/`yandex`), no changes needed.

### Benefits
- ✅ CI/CD pipelines: no "No space left on device" errors (500 MB vs 20 GB)
- ✅ Docker images: 16x smaller (500 MB vs 8 GB)
- ✅ Serverless: fits in AWS Lambda 250 MB limit
- ✅ Production RAM: 200 MB per tenant (API) vs 1.5 GB (local models)

### Technical Details
- Lazy import in `EmbeddingsFactory.create()` with `RuntimeError` for missing dependencies
- Lazy import in `LocalEmbeddingsProvider._ensure_model_loaded()` with error handling
- User-friendly error messages with installation instructions
- `sentence-transformers>=2.2.0` moved to `[project.optional-dependencies]` → `local`
- `torch` and `transformers` are transitive dependencies (installed automatically)

## [0.9.1] - 2026-01-14

### Changed
- **Dependency constraint relaxed**: `multi-llm-orchestrator>=0.7.6,<0.9.0` (was `<0.8.0`)
  - Enables compatibility with multi-llm-orchestrator 0.8.x (API key validator feature)
  - Resolves dependency conflict with Platform SaaS integration
  - **multi-llm-orchestrator 0.8.1** is fully backward compatible with 0.7.6
  - Only addition in 0.8.1: `validate_api_key()` method (optional, non-breaking)
  - Future-proof: Supports 0.8.x line while protecting from 0.9.0 breaking changes

### Technical Details
- No breaking changes for existing users
- All existing functionality unchanged
- Tested with multi-llm-orchestrator 0.7.6, 0.7.7, 0.8.0, 0.8.1
- Platform SaaS CI/CD now unblocked

### For Platform SaaS Users
- You can now install `telegram-rag-bot==0.9.1` alongside `multi-llm-orchestrator==0.8.1`
- Dependency conflict resolved: `pip install telegram-rag-bot==0.9.1` works with 0.8.1
- Update your `requirements.txt`: `telegram-rag-bot>=0.9.1`

## [0.9.0] - 2026-01-XX

### Added
- **HTTP POST usage tracking** to Platform SaaS API for real-time billing
  - Automatic usage reporting after each LLM request (when `platform.callback_url` is set)
  - Retry logic with exponential backoff (3 attempts: 0.5s → 1s)
  - 2 seconds timeout per request
  - Fail-silent pattern: bot continues working if Platform API is unreachable
- **Platform config section** in `config.yaml`:
  - `platform.tenant_id`: Platform tenant ID (required if `callback_url` is set)
  - `platform.callback_url`: Platform API base URL (optional)
  - `platform.platform_key_id`: Platform key ID for Managed tier (optional, None for BYOK)
- **429 Quota Exceeded handling**: NO retry, ERROR log (prevents quota exhaustion)
- **ConfigLoader validation**: Validates `platform` section (URL format, required fields)

### Changed
- `create_router()` now accepts optional `usage_callback` parameter (backward compatible)
- `track_usage()` now supports HTTP POST to Platform API (backward compatible: if `callback_url` not set → only logging)
- Updated `aiohttp` usage: Added `ClientSession` lifecycle management in `main()`

### Technical
- Closure factory pattern: `create_track_usage_callback()` for configurable usage tracking
- HTTP POST payload includes: `tenant_id`, `provider`, `model`, `tokens`, `prompt_tokens`, `completion_tokens`, `cost`, `latency_ms`, `success`, `timestamp`, `platform_key_id`
- Retry backoff formula: `0.5 * (2 ** attempt)` seconds
- Network errors trigger retry, 429 errors do NOT retry

### Notes
- Backward compatible: If `platform.callback_url` is not set, bot works as v0.8.9 (structured logs only)
- HTTP session created at bot startup, closed gracefully on shutdown
- All usage tracking errors are logged but don't interrupt bot operation

***

## [0.8.9] - 2025-12-29

### Added
- **Usage tracking callback** integration with Multi-LLM-Orchestrator v0.7.6
  - Structured logs (JSON) for token usage, cost, latency tracking
  - Fail-silent pattern for production stability
  - **Platform SaaS integration**: Logs ready for Week 4+ HTTP POST to billing API

### Changed
- Updated `multi-llm-orchestrator` dependency: `0.7.5` → `>=0.7.6,<0.8.0` (PEP 508 compliant)
  - Adds `UsageData` dataclass and `usage_callback` parameter support

### Fixed
- **Hotfix**: Fixed `pyproject.toml` dependency syntax error
  - Changed `^0.7.6` (npm/yarn syntax) → `>=0.7.6,<0.8.0` (PEP 508 compliant)
  - Resolved GitHub Actions build failure: `configuration error: project.dependencies must be pep508`
  - All quality gates passed: pip install, build, pre-commit, pytest (161 passed, coverage 77.43%)

### Notes
- Callback function hardcoded in `main.py` (not configurable via config.yaml)
- Future releases will add HTTP POST to Platform API for real-time billing

***

## [0.8.8] - 2025-12-28

### Fixed
- **Critical**: RuntimeWarning при SIGHUP config reload (async/await bug)
  - Исправлен вызов `Router.update_providers()` без `await` в `_reload_config_async()`
  - Обновлены тесты для использования `AsyncMock` вместо `MagicMock`
  - Zero-downtime hot-reload теперь работает корректно без warnings

### Changed
- Docstring `_reload_config_async()` уточнён: "Call" → "Await" для ясности
- Тесты `test_config_hotreload.py`: assertion обновлён на `assert_awaited_once_with()`

### Testing
- ✅ Docker integration test: SIGHUP reload без RuntimeWarning
- ✅ Unit tests: 9/9 PASS
- ✅ Linters: ruff check clean

***

## [0.8.7] - 2025-12-27

### Added
- **Config Hot-reload (SIGHUP handler)** — zero-downtime provider updates
  - SIGHUP signal handler для перезагрузки `config.yaml` без остановки бота
  - Интеграция с `Router.update_providers()` из Multi-LLM-Orchestrator v0.7.5
  - Debounce mechanism (5 секунд) для защиты от spam reloads
  - Автоматическая очистка RAG chains cache после обновления providers
  - Graceful error handling (бот продолжает работу при ошибках reload)
  - Use case: Platform SaaS Managed → BYOK migration (0 секунд downtime)
- **Helper function `build_providers_list()`** — построение списка providers из config
- **9 unit tests** для Config Hot-reload (`tests/test_config_hotreload.py`)

### Changed
- **Multi-LLM-Orchestrator dependency**: обновлена с `0.7.4` → `0.7.5`
  - Требуется для `Router.update_providers()` API

### Technical Details
- Новые функции в `telegram_rag_bot/main.py`:
  - `build_providers_list()` — helper function для построения providers
  - `_reload_config_async()` — async reload function
  - `_handle_sighup()` — SIGHUP signal handler
- Глобальные переменные для SIGHUP handler:
  - `reload_lock` — предотвращение concurrent reloads
  - `last_reload_time` — debounce tracking
  - `shutdown_in_progress` — игнорирование SIGHUP во время shutdown

### Edge Cases Handled
- Reload во время активного LLM request → thread-safe update
- Invalid config.yaml → log error, continue with old config
- Несколько SIGHUP подряд → debounce (5 секунд)
- SIGHUP во время shutdown → игнорирование
- Empty providers list → validation, skip reload

### Testing
- **Новые тесты**: 9 тестов для Config Hot-reload
- **Coverage**: 77.43% (maintained >= 75%)
- **All tests pass**: 159 passed, 3 skipped

## [0.8.6] - 2025-12-27

### Added
- **Self-Contained Bundle Architecture** — Modes теперь хранятся как независимые bundles
  - Структура: `config/modes/<mode_name>/mode.yaml`, `system_prompt.md`, `faq.md`
  - Преимущества: независимые modes, версионирование через Git, масштабируемость
- **ModeLoader** — новый класс для динамической загрузки modes из директорий
  - Автоматическая валидация обязательных файлов (mode.yaml, system_prompt.md, faq.md)
  - Опциональная поддержка examples.yaml для few-shot examples
  - Graceful degradation (пропуск disabled modes)
  - Расположение: `telegram_rag_bot/mode_loader.py`
- **Автосоздание FAISS индексов** — индексы создаются автоматически при старте бота
  - Проверка существующих индексов (не пересоздаёт если уже есть)
  - Параллельная обработка всех modes
  - Подробное логирование (количество chunks для каждого mode)
- **Прогрев Embeddings модели** — модель загружается при старте (не при первом запросе)
  - Первый запрос пользователя работает быстро (~3 сек вместо 2.5 мин)
  - HuggingFace cache volume в Docker для сохранения моделей между пересборками
  - Graceful degradation если warmup упадёт (модель загрузится при первом запросе)
- **SSL сертификаты** — добавлены ca-certificates в Dockerfile
  - Исправляет SSL ошибки для GigaChat/Yandex APIs
  - Решает CERTIFICATE_VERIFY_FAILED ошибки

### Changed
- **config.yaml формат** — новый формат modes конфигурации
  ```yaml
  # БЫЛО (v0.8.5)
  modes:
    it_support:
      faq_file: "faqs/it_support.md"
      system_prompt: "You are IT support..."
  
  # СТАЛО (v0.8.6)
  modes:
    directory: "modes"
  ```
- **config_loader.py** — интеграция ModeLoader
  - Динамическая загрузка modes из bundles
  - Поддержка относительных и абсолютных путей
  - Функция `reload_config()` для hot updates
- **handlers.py** — обновлённые handlers
  - Автовыбор mode если только 1 активный (при `/start`)
  - Кнопки выбора для множественных modes
  - `/reload_faq` обновляет modes без перезапуска бота
- **main.py** — автосоздание FAISS индексов и прогрев embeddings
  - Индексы создаются для всех modes при старте
  - Embeddings модель прогревается перед запуском бота

### Fixed
- **FAISS индексы не создавались для новых modes** — теперь создаются автоматически
- **Дублирование пути** — исправлено `/app/config/config/modes` → `/app/config/modes`
- **Первый запрос timeout** — исправлено через прогрев embeddings модели при старте
- **Старые тесты не поддерживали новый формат** — обновлены test_config_loader.py и test_handlers.py

### Breaking Changes
- **Формат config.yaml изменён** — старый формат `modes: {it_support: {...}}` НЕ поддерживается
  - Обязательно использовать `modes.directory: "modes"`
- **Структура файлов изменена** — FAQ файлы должны быть в `config/modes/<mode_name>/faq.md`
  - System prompts в `config/modes/<mode_name>/system_prompt.md`
- **FAISS индексы пересоздаются** — при миграции удалить старые: `rm -rf .faiss_indices/*`
  - Новые создадутся автоматически при старте

### Migration
1. Обновить структуру modes:
   ```bash
   mkdir -p config/modes/it_support
   mv faqs/it_support.md config/modes/it_support/faq.md
   # Создать system_prompt.md и mode.yaml
   ```
2. Обновить config.yaml:
   ```yaml
   modes:
     directory: "modes"
   ```
3. Пересобрать Docker:
   ```bash
   docker-compose down -v
   docker-compose build --no-cache
   docker-compose up -d
   ```
4. Индексы создадутся автоматически при старте

### Tests
- **Новые тесты**: 14 тестов для ModeLoader (`tests/test_mode_loader.py`)
- **Обновлённые тесты**: test_config_loader.py, test_handlers.py (поддержка нового формата)
- **Coverage**: 76.11% (150 passed, 3 skipped, target 75% exceeded)

### Technical Details
- Новый файл: `telegram_rag_bot/mode_loader.py` (200+ строк)
- Изменённые файлы: config_loader.py, handlers.py, main.py, config.yaml
- Docker: добавлен huggingface_cache volume, ca-certificates в Dockerfile

## [0.8.5] - 2025-12-24

### Fixed
- **Critical**: Fixed `ValueError: Prompt must accept context` in RAG chains
  - Added `{context}` variable to prompt template in `RAGChainFactory.create_chain()`
  - LangChain's `create_stuff_documents_chain` requires explicit `{context}` variable
  - Context is automatically formatted from retrieved documents
  - Empty context is handled gracefully (LLM receives empty string)
  - Prompt template now includes `{context}` in human message
  - Format: "Контекст из базы знаний:\n\n{context}\n\nВопрос пользователя: {input}\n\nОтветь на основе контекста выше."
  - No breaking changes for end users
  - Existing chains will be recreated with new prompt on next `create_chain()` call

### Changed
- **Embeddings model**: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` → `sberbank-ai/sbert_large_nlu_ru`
  - Dimension: 384 → 1024
  - Reason: HuggingFace CDN blocked in Russia; Russian-optimized model yields higher FAQ accuracy
  - Benefit: Better relevance on Russian FAQs; accessible without VPN
- Auto-detect embeddings dimension instead of hardcoding; log model/dimension/device/size on load
- FAISS: Fail-fast dimension check on load with user-friendly guidance to run `/reload_faq`
- Error handling: Network/OOM specific messages for model loading

### Breaking Changes
- Existing FAISS indices built with 384-dim are incompatible (stored vs model dimension mismatch)
- Admin must run `/reload_faq` after updating to rebuild all indices with the new 1024-dim model

### Migration
1. Update to v0.8.5
2. Restart bot (`docker-compose restart bot`) and allow model download (~1.1 GB)
3. Run `/reload_faq` in Telegram to rebuild indices
4. Verify FAQ query (e.g., "Как сбросить пароль VPN?") returns relevant answer

## [0.7.0] - 2025-12-20

### Added
- Initial release
- Multi-LLM Orchestrator integration (GigaChat, YandexGPT)
- LangChain RAG chains with FAISS/OpenSearch vector stores
- Flexible embeddings (Local HuggingFace, GigaChat API, Yandex AI Studio)
- Telegram bot with /start, /mode, /reload_faq commands
- Session management (Redis + memory fallback)
- Config-driven FAQ modes (YAML)
- Health check endpoint for Docker/Kubernetes
- Structured logging (JSON/text formats)
- Prometheus metrics collection (query latency, active users, errors)
- CLI tool for project management

### Week 1 MVP Features
- Production-ready monitoring (health check + metrics)
- Graceful degradation patterns
- Comprehensive error handling
- Async/await architecture

### Fixed
- Environment variable validation for embeddings/vectorstore
- Graceful shutdown for OpenSearch connections
- Router providers type checking

## [0.8.0] - 2025-12-20

### Changed
- Migrated to LangChain 1.x compatibility
- Updated import paths for `create_retrieval_chain` and `create_stuff_documents_chain`
- Updated dependency: `langchain>=1.0`

### Technical Details
- No breaking changes for end users
- Backward compatible with existing configurations
- FAISS/OpenSearch indices remain unchanged

## [0.8.1] - 2025-12-20

### Fixed
- Fixed LangChain 1.x imports: using `langchain-classic` package for `create_retrieval_chain` and `create_stuff_documents_chain`
- Added `langchain-classic>=1.0,<2.0` dependency
- Синхронизирован requirements.txt с pyproject.toml (добавлены langchain>=1.0 и langchain-classic>=1.0,<2.0)
- Исправлены устаревшие пути bot/ → telegram_rag_bot/ в документации (Docs/)
- Исправлена версия prometheus-client в requirements.txt (==0.20.0 → >=0.19.0,<0.20.0)
- Исправлен устаревший импорт в тестах (bot.vectorstore → telegram_rag_bot.vectorstore)

### Technical Details
- In LangChain 1.0.x, retrieval chain functions are in separate `langchain-classic` package
- No breaking changes for end users
- Backward compatible with existing configurations

## [0.8.2] - 2025-12-21

### Added
- Docker infrastructure for staging deployment
  - `Dockerfile` with health check using curl
  - `docker-compose.yml` with bot + Redis services
  - `.dockerignore` for build optimization
- Environment templates for Docker and local development
  - `.env.example` (root) for Docker deployment
  - `telegram_rag_bot/templates/.env.example` for CLI init

### Fixed
- Corrected `.gitignore` path for FAISS indices (`.faiss_indices/` instead of `faiss_indices/`)

## [0.8.3] - 2025-12-21

### Fixed
- **Critical bug: Fixed python-telegram-bot v21+ compatibility**
  - Replaced deprecated `application.idle()` with asyncio.Event + signal handlers
  - Fixed shutdown sequence to prevent "This Updater is still running!" error
  - Added proper SIGTERM/SIGINT handling for graceful Docker shutdown
  - Added defensive checks before shutdown operations
  - Improved shutdown logging for better diagnostics
- Pinned `python-telegram-bot>=21.0,<22.0` to prevent breaking changes in v22

### Added
- Graceful shutdown support in Docker (SIGTERM handling)
- Detailed shutdown logging with emoji indicators

### Tested
- Docker deployment (startup + shutdown): ✅
- Container stability (no restart loops): ✅
- Health check endpoint: ✅
- Telegram polling: ✅

### Technical Details
- Fixed `AttributeError: 'Application' object has no attribute 'idle'`
- Fixed `RuntimeError: This Updater is still running!`
- Eliminated Docker restart loop (bot crashed every 3-4 seconds before fix)
- Shutdown sequence now: updater.stop() → app.stop() → app.shutdown()
- Signal handlers added for SIGTERM (Docker) and SIGINT (Ctrl+C)

## [0.8.4] - 2025-12-22

### Added
- **Pre-commit Tools** — Local quality checks before push
  - `scripts/pre-commit-check.sh` (bash, Linux/Mac/Git Bash)
  - `scripts/pre-commit-check.ps1` (PowerShell, Windows)
  - `Makefile` with 9 commands (help, format, lint, test, mypy, check, pre-commit, clean, install)
- **Developer Workflow** — One command (`make pre-commit`) runs all checks locally (10-20 seconds)
- **Documentation** — Updated README.md with "Development Setup" section
- **New Badges** — Added Tests, Coverage, Ruff, Pre-commit badges to README.md
- **Development Guide** — Created `Docs/DEVELOPMENT.md` with comprehensive development workflow

### Fixed
- **Technical Debt Resolution** — ruff 0 warnings (was 1), mypy 67 errors (was 87, 23% improvement)
  - `handlers.py`: Null checks for `update.message` and `effective_user` ([`638522d`](https://github.com/MikhailMalorod/telegram-bot-universal/commit/638522d))
  - `config_loader.py`: `ProviderConfig` TypedDict for type safety ([`b7a4223`](https://github.com/MikhailMalorod/telegram-bot-universal/commit/b7a4223))
  - `session_manager.py`: `get_session` return type → `Optional` ([`e5671a9`](https://github.com/MikhailMalorod/telegram-bot-universal/commit/e5671a9))
  - `handlers.py`: LangChain response None checks ([`f12ab89`](https://github.com/MikhailMalorod/telegram-bot-universal/commit/f12ab89))
  - `handlers.py`: Missing `await` for `rebuild_index` async call ([`f9be59d`](https://github.com/MikhailMalorod/telegram-bot-universal/commit/f9be59d))
  - `__main__.py`: Removed f-string without placeholders ([`aa23405`](https://github.com/MikhailMalorod/telegram-bot-universal/commit/aa23405))
- **Black Formatting** — 21 files auto-formatted ([`ff345f2`](https://github.com/MikhailMalorod/telegram-bot-universal/commit/ff345f2))

### Changed
- **Quality Standards** — New/modified files MUST have type hints, null checks, docstrings, async/await
- **CI/CD Status** — All checks passing except mypy (non-blocking, 67 errors deferred to v0.9.0)

### Developer Experience
- **Time Saved** — 5-10 min per push (no CI/CD wait for trivial errors)
- **Fast Feedback** — Local checks in 10-20 seconds (vs 2-3 min CI/CD)
- **Auto-fix** — Black formatting runs automatically in pre-commit

### Non-Breaking Changes
- Remaining 67 mypy errors are non-critical (Dict[str, Any] generics, Optional imports)
- All functionality unchanged, only type annotations and guard clauses added
- Backward compatible with existing configurations

### Documentation
- `README.md` — Added "Development Setup" section with pre-commit workflow
- `PROJECT-TRUTH.md` — Updated with Day 20 achievements (pre-commit tools + technical debt)
- `Docs/DEVELOPMENT.md` — Created comprehensive development guide (new file)
- `Docs/QUALITY-GATES.md` — Updated current status (technical debt resolved)

### Commits
- [`aa23405`](https://github.com/MikhailMalorod/telegram-bot-universal/commit/aa23405) — style(main): Remove f-string without placeholders
- [`638522d`](https://github.com/MikhailMalorod/telegram-bot-universal/commit/638522d) — fix(handlers): Add null checks for update.message and effective_user
- [`b7a4223`](https://github.com/MikhailMalorod/telegram-bot-universal/commit/b7a4223) — fix(config): Add TypedDict for ProviderConfig
- [`e5671a9`](https://github.com/MikhailMalorod/telegram-bot-universal/commit/e5671a9) — fix(session): Change get_session return type to Optional
- [`f12ab89`](https://github.com/MikhailMalorod/telegram-bot-universal/commit/f12ab89) — fix(handlers): Add None check for LangChain response
- [`f9be59d`](https://github.com/MikhailMalorod/telegram-bot-universal/commit/f9be59d) — fix(handlers): Add missing await for async rebuild_index call
- [`cf35279`](https://github.com/MikhailMalorod/telegram-bot-universal/commit/cf35279) — docs: Update mypy status (87 → 67 errors, top 20 fixed)
- [`084ac1e`](https://github.com/MikhailMalorod/telegram-bot-universal/commit/084ac1e) — build: Add local quality checks (pre-commit scripts + Makefile)
- [`d412430`](https://github.com/MikhailMalorod/telegram-bot-universal/commit/d412430) — docs: Update development setup with dev dependencies and quality checks
- [`ff345f2`](https://github.com/MikhailMalorod/telegram-bot-universal/commit/ff345f2) — style: Auto-format code with black (21 files)

## [0.8.5] - 2025-12-22

### Added
- **FeedbackCollector** — класс для сбора обратной связи от пользователей
  - Redis storage с TTL 90 дней (7776000 секунд)
  - Memory fallback при недоступности Redis
  - Методы: `save_feedback()`, `get_feedback()`
- **Команда `/help`** — инструкция для пользователей (Markdown формат)
  - Описание основных команд: `/start`, `/help`, `/feedback`
  - Примеры вопросов для бота
- **Команда `/feedback`** — запрос оценки качества ответа
  - Inline-кнопки рейтинга (1-5 звёзд)
  - Проверка наличия last_query/last_answer в session
- **Callback query handler** — обработка inline-кнопок
  - `feedback:{rating}` — сохранение оценки ответа
  - `action:feedback` — показ inline-кнопок рейтинга
  - `action:help` — показ help текста
  - `mode:{mode_name}` — переключение режима
- **Расширенный `/start`** — onboarding с 3 inline-кнопками:
  - "📚 IT Support FAQ" (переключение режима)
  - "💬 Оставить отзыв" (запрос feedback)
  - "❓ Помощь" (показать help)
- **Session storage** — сохранение `last_query` и `last_answer` для feedback

### Changed
- `telegram_rag_bot/handlers.py`:
  - Добавлен `handle_callback_query()` для обработки callback queries
  - Обновлен `cmd_start()` с inline-кнопками и расширенным welcome text
  - Обновлен `handle_message()` для сохранения last_query/last_answer
  - Добавлены методы `cmd_help()` и `cmd_feedback()`
- `telegram_rag_bot/main.py`:
  - Инициализация `FeedbackCollector` (после SessionManager)
  - Регистрация новых handlers (`/help`, `/feedback`, `CallbackQueryHandler`)
  - Передача `feedback_collector` в `TelegramHandlers`

### Tests
- `tests/test_feedback_collector.py` — новый файл (6 тестов):
  - `test_save_feedback_success`
  - `test_save_feedback_invalid_rating`
  - `test_save_feedback_memory_fallback`
  - `test_get_feedback`
  - `test_get_feedback_empty`
  - `test_get_feedback_memory_fallback`
  - `test_get_feedback_limit`
- `tests/test_handlers.py` — расширен (+6 тестов):
  - `test_cmd_help`
  - `test_cmd_feedback_no_history`
  - `test_cmd_feedback_with_history`
  - `test_handle_callback_query_feedback`
  - `test_handle_callback_query_action_help`
  - `test_handle_message_saves_session`
- `tests/conftest.py` — добавлены fixtures: `mock_callback_query`, `mock_feedback_collector`
- Coverage: 78%+ maintained

### Status
- ✅ Ready for 1-3 user pilot testing

## [0.13.3] - 2026-02-26

### Fixed
- **Critical (Issue #14)**: Bot crashed after every LLM response when
  `platform.callback_url` is configured
- **Root cause**: `await _send_usage_to_platform()` inside `track_usage` callback
  violated Python 3.11+ requirement — asyncio timeout context managers must run
  inside an `asyncio.Task`, not in a plain coroutine
- **Fix**: replaced `await` with `asyncio.create_task()` — true fire-and-forget
- **Side effect eliminated**: GigaChat 429 flood from 6 auto-restart cycles

### Changed
- Usage tracking is now fully fire-and-forget: Platform API unavailability
  never blocks or crashes the main bot response flow

### Notes
- v0.13.2 on PyPI contains Issue #14 (published 2026-02-25 before the fix)
- All users on v0.13.2 with `platform.callback_url` set should upgrade to v0.13.3

## [0.13.2] - 2026-02-26

### Fixed
- **Critical**: `RuntimeError: Timeout context manager should be used inside a task`
  при отправке usage report на Platform API (issue #14)
- **Root cause**: `await _send_usage_to_platform()` в `track_usage` callback
  нарушало требование Python 3.11+ для asyncio timeout context managers
- **Fix**: заменён `await` на `asyncio.create_task()` — fire-and-forget pattern
- **Impact**: бот больше не падает после каждого сообщения при наличии `platform.callback_url`
- **GigaChat 429**: устранена причина flood авто-рестартов
- **Transport hardening (Issue #13)**: `_send_usage_to_platform` уже мигрирован с `aiohttp.ClientSession` на `httpx.AsyncClient(timeout=2.0)` с сохранением retry (3 попытки, backoff 0.5s → 1.0s), 429 handling (NO retry, ERROR log) и fail-silent поведения

### Changed
- Usage tracking теперь полностью fire-and-forget (не блокирует основной поток)

---

## [Unreleased]

### Planned for 0.9.2
- Additional FAQ modes (HR, Finance, Sales)
- Multi-department rollout
- Analytics dashboard

---

## Version Update Checklist

When releasing a new version:

1. Update `telegram_rag_bot/__init__.py` (`__version__`)
2. Update `pyproject.toml` (`version` field)
3. Update `CHANGELOG.md` (add new version section)
4. Create git tag: `git tag -a v0.X.Y -m "Release v0.X.Y"`
5. Push tag: `git push origin v0.X.Y`
6. Create GitHub Release (GitHub Actions will auto-publish to PyPI)
