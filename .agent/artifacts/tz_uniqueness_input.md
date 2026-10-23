# G1a — утверждённые новые AC

Источник: решение пользователя по change_proposal.md. Только формализация,
без G1b, чтения rag_chains.py или анализа его контракта, без кода.

U02 утверждена без условий. U01 утверждена условно: Architect в G1b должен
подтвердить provenance (путь + chunk_id) через существующий контракт
langchain_adapter/rag_chains.py без изменения ядра AC-C03. Если недоступно —
U01 backlog, MVP только U02; Architect явно фиксирует это в architecture_plan.md.
U03/U04/U05 — backlog; отклонённых стратегий нет.

Входы: acceptance_criteria.yaml, change_proposal.md, repo_map.json,
baseline_report.md из .agent/artifacts/.
Контроль неизменности: .agent/artifacts/acceptance_before_u01_u02.json.

## AC-U01
- type: functional
- requirement: К ответу добавляется название разрешённого источника и дословная цитата из использованного RAG-контекста.
- acceptance: Для 12 контрольных пар AC-S1/S2/S3/S5 источник и дословная цитата соответствуют ключевому факту пары (12/12). Positive fixtures имеют достоверный provenance; negative fixtures (источник недоступен / нет совпадения) дают RU «основание недоступно» без выдуманных ссылок. AC-S6 сохраняется: при fallback цитата не выдумывается. Ядро RAG не менять (AC-C03); UI-строки по AC-C07.
- linked_modules: handlers.py, langchain_adapter/rag_chains.py (только чтение контракта в G1b, не правка), config/i18n/ru.yaml.
- priority: mandatory (условно, condition ниже).
- test_hint: integration
- condition: Активен только если Architect в G1b подтвердит доступность provenance (путь + chunk_id) через существующий контракт rag_chains.py без изменения ядра AC-C03. Иначе backlog, MVP без U01; решение обязательно фиксируется в architecture_plan.md. В текущей задаче проверку G1b НЕ выполнять.

## AC-U02
- type: functional
- requirement: Для VPN и неполученного письма — YAML-описанный детерминированный диалог с ветвлением, ведущий к утверждённому факту FAQ или к эскалации.
- acceptance: Минимум 2 конечные ветви на каждый сценарий, максимум 3 уточнения на путь. Каждая конечная ветвь ссылается на утверждённый факт FAQ. Пароли/токены не запрашивать, команды не запускать. Явная эскалация доступна на каждом шаге (AC-S7). Изменение развилки через YAML без изменения кода (AC-C04). Счётчик AC-S7 меняют только прежние RAG-события, диагностические вопросы не изменяют счётчик. Integration-тест всех путей. Сохранить AC-C02/C03/C06/C07.
- linked_modules: handlers.py, mode_loader.py, config_loader.py, config/modes/it_support/.
- priority: mandatory
- test_hint: integration

## Правила
1. Добавить только AC-U01/AC-U02, итог 35. Исходные 33 AC не менять,
   желательно сохранить исходные байты как префикс YAML и просто дописать AC.
2. condition разрешён как дополнительное поле AC-U01, priority остаётся mandatory.
   Явные связи с существующими AC отразить в acceptance, без редактирования этих AC.
3. Новых TBD не вводить. Если требуется default для проверяемости — явно отметить.
4. linked_modules включают пользовательские целевые config paths; они не обязаны
   уже существовать. В tz_status.json отметить planned target для ru.yaml;
   не создавать config files, не выдавать существование за факт.
5. Доступ к .env/.env.* и .idea запрещён. Все записи только .agent/artifacts/.
6. Не изменять change_proposal.md, repo_map.json, baseline_report.md или AGENTS.md.
7. AGENTS.md уже содержит install-команду 0.14.6 (проверено Orchestrator),
   дополнительных правок не нужно.
8. Обновить tz_status.json: accepted U02, conditionally accepted U01,
   provenance verification deferred explicitly to G1b, questions=[];
   это не повод для need_info и не разрешение начать G1b.
