# Onboarding Navigator — примечания к выпуску 0.1.0

## Сводка

**31/35 AC ok, 4 pending_environment, 0 risk, 0 fail.** Статус G2 — `pass_with_pending_environment`, согласно принятому решению пользователя и [g2_status.json](g2_status.json). Эта документация не закрывает G2 и не подтверждает развёртывание в production.

## Сценарии, проверенные офлайн

Следующие цепочки приложения проверены с тестовыми заменами внешних систем и локальными артефактами, без реальных Telegram/LLM/Redis/Docker/Kubernetes:

- YAML-режимы: `it_support`, `benefits`, `learning`, `culture`, `onboarding_plan`. Добавление новых наборов не требует правок кода; они обнаруживаются при перезапуске (AC-S8).
- Переключение GigaChat→YandexGPT через сохранённое ядро оркестрации (AC-N03).
- RAG на FAISS с порогом сходства 0.65: ниже порога генерация заменяется резервным сценарием с доступными предложениями из первых трёх кандидатов и эскалацией (AC-S6).
- Персональный онбординг по роли/отделу: TTL профиля 24 часа от явного ввода; порядок выбора плана `<role>__<department>.md`→`<role>.md`→`default.md` (AC-S4/F01).
- Цитаты: разрешённый источник и точный возвращённый `page_content`, без повторного поиска. При недоступном контексте или неизвестном источнике выводится локализованное сообщение об отсутствии основания (AC-U01).
- Диагностика VPN/почты: проверяемые YAML-ветви, без решений LLM, эскалация на каждом шаге (AC-U02).
- Явное создание тикетов и автоматическое после двух последовательных RAG-fallback, неизменный UUID между повторными попытками и устранение дублей в пределах процесса (AC-S7/F05).
- `/reindex` и `/status` только для администраторов; `/reload_faq` — псевдоним `/reindex` (AC-F03/F04).
- Метрики: `llm_requests_total`, гистограмма `rag_score_bucket`, `fallback_total{type="rag"|"llm"}`, `tickets_created_total`, `tickets_failed_total` (AC-N04..N07/N11).
- Готовность к локализации: `i18n.py`, **124 конечных ключа перевода** в `ru.yaml` (не 240+); AST активных обработчиков и загрузчика режимов проходит проверку, три устаревших резервных литерала загрузчика помечены. EN вне объёма работ (AC-C07).
- Тесты исходного пакета: 316 passed, 3 существующих пропуска; покрытие **2238/2869 = 78.006%** (AC-N10). Инфраструктура: 20 passed, 1 skip из-за отсутствия kubeconform. Неизменность хешей: 44/44 замороженных файлов и 8/8 принятых файлов i18n.

## Что остаётся pending_environment

Ни один из перечисленных результатов в реальном окружении не получен. См. [g2_status.json → pending_environment_detail](g2_status.json) и [воспроизведение](#reproduction).

| AC | Цель и необходимые условия |
| --- | --- |
| AC-N01 | Telegram E2E p95 ≤ 3000 мс; нужны реальный мост завершения Telegram-запросов и нагрузочное окружение. |
| AC-N02 | RAG p95 ≤ 200 мс; **blocked**: в замороженном приложении нет `/debug/rag_latency`. Нужен отдельный PR с эндпоинтом или профилирование py-spy/pyinstrument. |
| AC-N08 | Для сборки/запуска Docker-образа нужны Docker daemon и учётные данные времени выполнения. |
| AC-N09 | Для развёртывания Kubernetes нужны реальный кластер, доступный образ и `telegram-secrets`; цель — 1/1 Running. |

<a id="reproduction"></a>

## Воспроизведение

Точные команды и ожидаемые результаты: [implementation_note.md#pending_environment_reproduction](implementation_note.md#pending_environment_reproduction), на который ссылается [g2_status.json](g2_status.json). Ниже приведены инструкции оператору; команды не выполнялись.

```sh
docker build -t onboarding-navigator .
docker run --rm --env-file .env -p 8080:8080 onboarding-navigator
curl -f http://127.0.0.1:8080/health
kubectl apply -f deploy/k8s/deployment.yaml
kubectl rollout status deployment/onboarding-navigator --timeout=120s
kubectl get pods -l app=onboarding-navigator
python tests/load/run_baseline.py --target-url <REAL_URL> --rps 10 --duration 300 --samples 1000 --seed 0 --telegram-e2e --out artifacts/ac_n01
```

`<REAL_URL>` должен быть внешним POST-мостом, принимающим `{request_id, mode, query}` и возвращающим совпадающий request_id и `telegram_e2e_completed: true` только после получения ответа Telegram. Замороженные эндпоинты health/metrics не отвечают на запросы к боту. Подтверждение приёма webhook или Bot API sendMessage недостаточно для E2E-замера. Цель в итоговом отчёте: `p95_telegram_e2e_ms <= 3000`. `--rag-only` завершается с кодом 2 и объяснением отсутствующего эндпоинта, без выдуманных измерений.

## Изменения архитектуры относительно telegram-rag-bot 0.14.6

- **Keep, неизменность подтверждена хешами:** upstream `orchestrator/router.py`, `orchestrator/retrieval/async_faiss.py`; `telegram_rag_bot/langchain_adapter/rag_chains.py`, `vectorstore/local_faiss.py`, `__main__.py`, реализация embeddings. Замороженный набор из 44 файлов включает ранее принятые изменения; «замороженный» не означает, что каждый файл взят без изменений из upstream.
- **Adapt:** `handlers.py` (миграция 47 литералов и подключение HR), `main.py` (`bootstrap_components`, `ProviderObserver`, `RequestScopedRouter`, разрешённое узкое исправление legacy reload), `mode_loader.py` (необязательные поля, три помеченных legacy fallback), `config_loader.py` (продуктовый конфиг), менеджер сессий (профиль/диагностика/счётчик/UUID тикета), метрики (пять новых серий).
- **Add:** `hr_adapter.py` с `HRFAISSProvider(LocalFAISSProvider)`, `citations.py`, `diagnostics.py`, `i18n.py`, извлечённый совместимый путь `handlers_legacy.py`, `integrations/ticketing.py`, `analytics/writer.py`. Legacy-обработчик недостижим в HR runtime и исключён из покрытия; реальные LCEL-пути `rag_chains.py` покрыты с тестовыми заменами.
- **Конфигурация:** продуктовые настройки с подстановками env, русская локаль из 124 конечных ключей, пять режимов, планы онбординга и корпоративные политики.
- **Инфраструктура:** образ из wheel, исключения контекста сборки, обычные ConfigMap/Deployment/Service, детерминированный нагрузочный инструмент, наложение конфигурации только на копию в образе. HTTP 8080 задаётся в образе; конфиг репозитория неизменен. Kubernetes дополнительно размещает analytics/FAISS в `/data`.

## Заменённые тесты и происхождение

`.agent/artifacts/backend_rest_wiring_checks/test_i18n_keys_used.py` архивирован как `.py.superseded`; исходное тело сохранено под заголовком о происхождении. Исходный SHA256: `81b87f6526a3c86d3dd0fa4946b454c835fc11949165c90730586cbcf6f68e63`.

Замена: `.agent/artifacts/backend_rest_i18n_checks/test_legacy_and_ui_cyrillic.py`. A/A′ сохраняют мультимножество кириллицы и нормализованную AST-логику извлечённого legacy-метода; B отклоняет неразрешённую кириллицу активного UI; C проверяет разрешение литеральных ключей перевода. Старое условие требовало оставить литералы в handlers и упало бы после утверждённой миграции; это намеренная замена проверки, не регрессия.

## Безопасность и соблюдение требований

Учётные данные поступают через env/Secret во время выполнения; конфиги и манифесты содержат подстановки/ссылки. Принятое офлайн-ревью не обнаружило открытых секретов в конфигурации, манифестах, логах или тестах. При подготовке документации выпуска файлы секретов не читались.

**Ограничения:** редактирование чувствительных данных эвристическое и не гарантирует удаления всех таких данных; идемпотентность тикетов действует в пределах процесса, не между pod; резервная память локальна процессу и не является общим состоянием. Kubernetes emptyDir временный. Календарь, голос, EN, аналитический UI, HR-auth, закупки и изменения HR-данных вне объёма работ.

Атрибуция и полный фактический текст MIT для telegram-rag-bot 0.14.6 сохранены в [ATTRIBUTION.md](ATTRIBUTION.md).
