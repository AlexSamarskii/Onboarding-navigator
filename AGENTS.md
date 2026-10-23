## Контекст проекта

Проект: **HR-бот «Onboarding Navigator»** — корпоративный Telegram-ассистент
для онбординга и HR-поддержки сотрудников.

База (актуальные источники):
- **PyPI-пакет `telegram-rag-bot` (v0.14.6)** — production-ready FAQ-бот для Telegram
  с multi-LLM fallback (GigaChat + YandexGPT), RAG на FAISS, YAML-режимами,
  Docker/K8s и Prometheus-метриками. Установка: `pip install telegram-rag-bot==0.14.6`.
- **GitHub `MikhailMalorod/Multi-LLM-Orchestrator`** — ядро оркестрации LLM
  (fallback, routing) и асинхронный FAISS-retriever.
  Клонирование: `git clone https://github.com/MikhailMalorod/Multi-LLM-Orchestrator.git`

Уникализация достигается за счёт:
- новых YAML-режимов (IT-доступы, Финансы, Обучение, Корпоративная культура);
- персонализации по роли/отделу;
- интеграции с календарём и трекером тикетов;
- аналитики частых вопросов;
- мультиязычности (RU/EN) через конфиг.

## Все агенты обязаны

1. Опираться на факты из репозитория и артефактов. Не выдумывать имена
   файлов, классов, API, эндпоинтов.
2. Предлагать минимально достаточные изменения. Сначала — переиспользование
   (`keep`), потом адаптация (`adapt`), только затем переписывание (`rewrite`).
3. Сохранять обратную совместимость с существующей архитектурой, если ТЗ не
   требует иного.
4. Любой вывод оформлять в машиночитаемом виде (JSON/YAML/Markdown) с явной
   структурой — как в `.agent/prompts/` или в шапке роли.
5. Если данных не хватает — перечислить, каких именно, и предложить безопасное
   допущение. Не угадывать.
6. Не редактировать файлы вне своей зоны ответственности (см. `file_change_plan.yaml`).
7. Не менять лицензионные заголовки и атрибуцию исходного проекта.
8. Не «подгонять» тесты под реализацию. Тесты проверяют AC, не наоборот.
9. Работать только с открытыми проектами (лицензионный гейт снят, но атрибуция
   сохраняется).

## Гейты (проверяет Orchestrator)

- **G0 Baseline** — репозиторий собирается/запускается, есть `repo_map.json`
  и `baseline_report.md`.
- **G1 Change Plan Approved** — утверждены `change_proposal.md` и
  `architecture_plan.md`, `file_change_plan.yaml` не пуст.
- **G2 Tests + Acceptance Passed** — `test_report.xml` зелёный,
  `acceptance_matrix.csv` без `fail`.

Пропускать гейты запрещено. Реализация без утверждённого `file_change_plan.yaml`
запрещена.

## Артефакты (единое хранилище)

Все агенты пишут и читают артефакты только через `.agent/artifacts/`:

| Артефакт | Автор | Потребители |
|---|---|---|
| `repo_map.json` | Repo Auditor | все |
| `baseline_report.md` | Repo Auditor | Orchestrator, Architect |
| `acceptance_criteria.yaml` | TZ Agent | все |
| `change_proposal.md` | Uniqueness Agent | Architect |
| `architecture_plan.md` | Architect | все |
| `file_change_plan.yaml` | Architect | Implementer, Reuse |
| `reuse_map.yaml` | Reuse/Adapter | Implementer |
| `patch.diff` + `implementation_note.md` | Implementer | Reviewer, Test, QA |
| `review.json` | Reviewer | Implementer |
| `test_report.xml` + `test_summary.md` | Test Agent | QA, Release |
| `acceptance_matrix.csv` | QA Agent | Orchestrator, Release |
| `release_notes.md` | Release Agent | человек |

## Формат коммуникации с Orchestrator

Каждый агент возвращает статус:

```json
{
  "agent": "имя",
  "status": "ok|need_info|blocked|failed",
  "artifact_ref": "путь/ID",
  "notes": "кратко",
  "questions": ["..."]
}
```

## Запреты

Не коммитить секреты, токены, ключи.
Не удалять существующую документацию без замены.
Не менять архитектуру ядра без эскалации к Architect.
Не считать задачу выполненной без привязки к acceptance_criteria.yaml.