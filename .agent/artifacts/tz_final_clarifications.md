# Утверждённые уточнения пользователя

Все прежние вопросы закрыты. Новые TBD не вводить; для неоднозначностей выбрать безопасное значение и явно отметить default в acceptance. Только acceptance artifacts, код не писать. Пользователь переопределил гейт: G1 для этой задачи пройден, когда acceptance_criteria.yaml не содержит TBD. Это не разрешение на реализацию без утверждённого file_change_plan.

## Материалы и контрольные пары
Обезличенные примеры faq.md; integration-проверка ключевого факта подстрокой/регуляркой. Политики можно заменить без изменения AC.
- it_support: «Как подключиться к VPN?» → клиент VPN + контакт IT; «Не приходит письмо на корпоративную почту» → квота/спам + контакт IT; «Как получить доступ к Git?» → заявка + согласование руководителя.
- benefits: «Какие льготы по ДМС?» → полис + HR-контакт; «Сколько дней отпуска?» → число дней из faq.md; «Как оформить больничный?» → шаги + HR-контакт.
- learning: «Какие курсы доступны?» → ссылка на каталог; «Как согласовать обучение?» → шаги согласования; «Есть ли бюджет на обучение?» → лимит/правило.
- culture: «Какой график работы?» → гибкий график/часы; «Есть ли дресс-код?» → правило; «Как оформить командировку?» → шаги + HR-контакт.

## Персонализация
Роль/отдел сообщает пользователь через /start или при первом onboarding_plan. session_manager TTL 24 ч. Приоритет plans/<role>__<department>.md, затем plans/<role>.md. Нет плана → «план не настроен», plans/default.md при наличии, эскалация; analytics/unanswered.jsonl reason="missing_plan".

## Similarity
Нормализованная [0,1], выше релевантнее. rag.score_threshold=0.65 default. FAISS distance конвертируется существующим адаптером, ядро RAG не менять (AC-C03). Ниже порога → RAG-fallback, >= → успешный RAG-ответ.

## Ticketing
MVP backend HTTP webhook: POST JSON integrations.ticketing.url. Поля ticket_id UUID, user_id_hash SHA-256 Telegram ID, mode, query, timestamp ISO 8601, reason explicit|fallback_x2, top_score. 3 попытки с backoff 1s/2s/4s. Провал → сообщение пользователю + ERROR-лог + tickets_failed_total. HR notification через тот же webhook с notify_chat_id из integrations.ticketing.hr_chat_id; если не задан, тикет без уведомления. Счётчик RAG-fallback в сессии: инкремент каждый RAG-fallback; сброс успешный RAG-ответ, создание тикета, TTL 24ч.

## Status
ADMIN_IDS only. mode, version из METADATA, llm.gigachat/llm.yandexgpt = ok|fail по последнему health-check, faiss.documents, uptime_seconds, last_reindex ISO8601|never.

## Performance
10 RPS, 5 мин, 1000 запросов; база 1000 чанков; 1 pod 2 CPU/4 GB в тестовом K8s; warmup 100 запросов не в статистике. p95 ответа <=3с от получения сообщения Telegram до отправки ответа, включая внешние LLM и Telegram. p95 RAG <=200мс только retrieval+FAISS, без LLM/Telegram.

## Метрики и покрытие
fallback_total{type="rag"} для similarity ниже порога; fallback_total{type="llm"} для GigaChat → YandexGPT.
Line coverage telegram_rag_bot/ >=78%. Исключения __main__.py, tests/, migrations/, автогенерируемые файлы, внешние адаптеры с живыми API (обосновать в отчёте). Команда pytest --cov=telegram_rag_bot --cov-report=term.

## i18n readiness
Все пользовательские строки config/i18n/ru.yaml (ключи→значения); handlers.py и mode_loader.py без кириллических строковых литералов, кроме логов с # noqa: i18n. config.yaml i18n.default_locale=ru. Проверка grep -nP '[А-Яа-я]' по двум файлам не находит совпадений в строковых литералах. EN out of scope, en.yaml добавляется без изменения кода.

## Требуемый выход
Обновить acceptance_criteria.yaml целиком: все прежние AC и приоритеты, конкретика вместо вопросов. В AC-S1..S5 явные пары; для S4 использовать сценарии выбора плана (в Q1 нет HR-пар для S4). Сохранить schema id/type/requirement/acceptance/linked_modules/priority/test_hint. Не выдумывать политики, даты отпусков, лимиты. Состояние и defaults сохранить отдельно в tz_status.json, новых вопросов не задавать.
