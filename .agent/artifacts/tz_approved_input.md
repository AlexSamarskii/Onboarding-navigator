# Утверждённое ТЗ — уточнение для TZ Agent

Источник: сообщение пользователя. Только acceptance criteria, код не писать.

S1 IT-доступы (it_support); S2 льготы (benefits); S3 обучение (learning);
S4 персональный план онбординга по роли/отделу (onboarding_plan);
S5 культура/политики (culture); S6 вне базы → fallback без выдумывания;
S7 явный запрос эскалации или 2 fallback подряд → создание заявки;
S8 новый YAML-режим без изменений кода.

Источники: config/modes/<mode>/faq.md, system_prompt.md;
config/modes/onboarding_plan/plans/<role>.md;
config/modes/culture/policies/*.md. FAISS индексация при старте или /reindex.
Секреты/токены только в .env; ADMIN_IDS whitelist.

Score <0.65 (конфигурируемый) → не выдумывать без RAG-контекста,
предложить top-3 ближайших вопроса и эскалацию; analytics/unanswered.jsonl;
2 fallback подряд → автоэскалация.

Действия: трекер Jira/YouTrack/email-вебхук (integrations.ticketing),
уведомление HR-чата, чеклист онбординга; /reindex и /status только ADMIN_IDS.
Метрики: llm_requests_total, rag_score_bucket, fallback_total,
tickets_created_total.

Нефункциональные: p95 ответа <=3 сек; p95 RAG <=200 мс;
GigaChat → YandexGPT; Docker + K8s; coverage >=78%; всё через YAML,
новый режим = новая папка config/modes/<mode>/.
Сохраняются предыдущие ограничения Python >=3.11, не менять ядро
multi-LLM fallback и RAG, сохранить YAML-режимы.

Out of scope: мультиязычность (кроме архитектурной готовности), голос,
календарь, аналитический UI, авторизация в HR-системах,
покупки/изменение HR-данных/произвольные действия.

Все S1–S8, coverage>=78%, fallback LLM и YAML-конфигурируемость mandatory.
Top-3 подсказки и analytics/unanswered.jsonl — optional.

Выход: acceptance_criteria.yaml целиком, каждый AC содержит id, type,
requirement, acceptance (измеримый), linked_modules, priority, test_hint.
Ровно один основной AC на каждый S1–S8 плюс дополнительные атомарные
nonfunctional/constraint/optional AC. Не угадывать недостающие параметры;
вернуть status=need_info и конкретные вопросы. G1 не объявлять утверждённым.
