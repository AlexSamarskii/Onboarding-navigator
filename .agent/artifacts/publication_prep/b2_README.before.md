# Onboarding Navigator — дополнение к README

## О проекте

HR-расширение [telegram-rag-bot 0.14.6](https://pypi.org/project/telegram-rag-bot/0.14.6/) для онбординга и поддержки сотрудников. См. [примечания к выпуску](release_notes.md) и [атрибуцию](ATTRIBUTION.md). Статус: 31/35 AC ok, 4 pending_environment, 0 fail; источник статуса — [g2_status.json](g2_status.json). Команды ниже — инструкции оператору, не подтверждение выполненного развёртывания.

## Быстрый старт — локально

Запускайте из корня репозитория, чтобы были доступны config и корневые пакеты integrations/analytics. Установите адаптированные исходники, а не неизменённый выпуск PyPI:

```sh
python -m venv .venv
.venv/bin/python -m pip install -e workspace/telegram-rag-bot-src/
```

Безопасно предоставьте текущей оболочке переменные: `TELEGRAM_TOKEN`, `GIGACHAT_KEY`, `YANDEX_API_KEY`, `YANDEX_FOLDER_ID`, `ADMIN_IDS` (JSON-список целых чисел), `TICKETING_WEBHOOK_URL`, `HR_CHAT_ID`. Экспортируйте уже заданные значения и запустите:

```sh
export TELEGRAM_TOKEN GIGACHAT_KEY YANDEX_API_KEY YANDEX_FOLDER_ID
export ADMIN_IDS TICKETING_WEBHOOK_URL HR_CHAT_ID
PYTHONPATH=. .venv/bin/python -m telegram_rag_bot run
```

Локальная команда `run` **не** загружает `.env` автоматически. Оператор может подготовить такой приватный файл для Docker; не коммитьте его. Вызов модуля без аргументов печатает справку, поэтому `run` обязателен. Из текущего каталога берётся `config/config.yaml`. Неизменённый локальный конфиг использует HTTP 8000 по умолчанию; в собранном образе задаётся HTTP 8080.

В Telegram: `/start`, `/mode` для списка режимов, `/mode onboarding_plan`, затем сообщение для начала сбора профиля. На запросы роли и отдела отвечайте строчными безопасными для пути значениями (например, `developer`, затем `engineering`). Сам `/start` не собирает профиль. Другие режимы: `/mode it_support`, `/mode benefits`, `/mode learning`, `/mode culture`.

## Быстрый старт — Docker

AC-N08 остаётся pending. Нужны daemon и приватный env-файл времени выполнения. Команды не запускались:

```sh
docker build -t onboarding-navigator .
docker run --rm --env-file .env -p 8080:8080 onboarding-navigator
```

Из другого терминала:

```sh
curl -f http://127.0.0.1:8080/health
docker run --rm onboarding-navigator python -c "import yaml; c=yaml.safe_load(open('/app/config/config.yaml')); assert c['http_server']['port']==8080"
```

Ожидается, но не подтверждено: HTTP 200, здоровый контейнер. CMD — `python -m telegram_rag_bot run`, uid 1000. `deploy/build_config_overlay.py` меняет только копию конфига в образе на HTTP 8080; конфиг репозитория неизменен.

## Быстрый старт — Kubernetes

AC-N09 остаётся pending. Нужны реальный кластер, собранный образ, доступный его узлам (либо ссылка на образ, скорректированная оператором), и семь переменных, уже безопасно переданных оболочке оператора. Следующая команда создаёт нужный Secret; если раскрытие значений в аргументах процесса недопустимо, используйте утверждённый механизм управления секретами:

```sh
kubectl create secret generic telegram-secrets \
  --from-literal=TELEGRAM_TOKEN="$TELEGRAM_TOKEN" \
  --from-literal=GIGACHAT_KEY="$GIGACHAT_KEY" \
  --from-literal=YANDEX_API_KEY="$YANDEX_API_KEY" \
  --from-literal=YANDEX_FOLDER_ID="$YANDEX_FOLDER_ID" \
  --from-literal=ADMIN_IDS="$ADMIN_IDS" \
  --from-literal=TICKETING_WEBHOOK_URL="$TICKETING_WEBHOOK_URL" \
  --from-literal=HR_CHAT_ID="$HR_CHAT_ID"
kubectl apply -f deploy/k8s/deployment.yaml
kubectl rollout status deployment/onboarding-navigator --timeout=120s
kubectl get pods -l app=onboarding-navigator
```

Ожидается, но не подтверждено: 1/1 Running. Манифест создаёт ConfigMap+Deployment+Service. Доступный только для чтения subPath заменяет лишь `/app/config/config.yaml`; режимы и локаль остаются в образе. HTTP 8080, доступный для записи `/data` emptyDir, корневая ФС только для чтения, uid 1000; requests 1 CPU/2Gi, limits 2 CPU/4Gi, одна реплика. Значения секретов отсутствуют в манифесте. Изменения встроенных режимов и локали требуют пересборки и повторного развёртывания.

## Добавление YAML-режима (AC-S8)

```sh
mkdir -p config/modes/my_mode
```

Создайте `config/modes/my_mode/mode.yaml`:

```yaml
name: my_mode
display_name: My mode
description: Answers for the new mode
enabled: true
files:
  system_prompt: system_prompt.md
  faq: faq.md
timeout_seconds: 30
source_titles:
  faq.md: My mode FAQ
```

Добавьте `system_prompt.md` в UTF-8 и проверенные факты в `faq.md`. Названия режима/источника могут быть строками для резервного отображения или существующими ключами локали. Все пути должны оставаться внутри набора режима. Необязательный `diagnostics_file` указывает на валидируемый граф; необязательный `plans_directory` — безопасное имя одного каталога.

**Для обнаружения нового набора перезапустите приложение.** Администраторская `/reindex` обновляет Markdown для режимов, уже присутствующих в конфигурации времени выполнения; новые определения она не обнаруживает. Можно переиндексировать существующие FAQ, планы и политики. Для режимов, встроенных в контейнер, нужны пересборка и повторное развёртывание. Правки кода не требуются.

## Проверка pending AC

См. [g2_status.json → pending_environment_detail](g2_status.json) и [точные команды воспроизведения](implementation_note.md#pending_environment_reproduction).

- AC-N08: команды Docker выше; цель — HTTP 200/healthy.
- AC-N09: команды Kubernetes выше; цель — 1/1 Running.
- AC-N01: нужен реальный внешний мост завершения Telegram-запросов, затем:

```sh
python tests/load/run_baseline.py --target-url <REAL_URL> --rps 10 --duration 300 --samples 1000 --seed 0 --telegram-e2e --out artifacts/ac_n01
```

Контракт моста: POST `{request_id, mode, query}` → совпадающий request_id и `telegram_e2e_completed: true` только после получения ответа Telegram. Подтверждения приёма webhook/Bot API недостаточно. Замороженное приложение не предоставляет этот мост. Цель в `artifacts/ac_n01/summary.json`: `p95_telegram_e2e_ms <= 3000`.

- AC-N02 заблокирован: нет `/debug/rag_latency`; для RAG p95 ≤ 200 мс нужен отдельный PR с эндпоинтом или внешнее профилирование py-spy/pyinstrument. `--rag-only` завершается с кодом 2 и не выдумывает результат.

Просмотр без сети: `python tests/load/run_baseline.py --dry-run --seed 0 --out artifacts/dry_run`. Он создаёт детерминированный манифест выборки 1000 из 3000, но не подтверждает задержку.

## Отличия от upstream

Сохранено ядро маршрутизации/RAG; добавлены HR-режимы, порог сходства, цитаты из контекста, детерминированная диагностика, планы по профилю, тикеты, аналитика, локализация и инфраструктура. Полный перечень keep/adapt/add: [release_notes.md](release_notes.md).

## Известные ограничения

- Устранение дублей тикетов локально процессу; идемпотентность между pod не гарантируется.
- Эвристическое редактирование чувствительных данных; удаление всех таких данных не гарантируется.
- Резервная память локальна процессу и не является общим состоянием.
- Kubernetes emptyDir временный; для долговременного хранения нужен постоянный том.
- Календарь, голос, EN, аналитический UI вне объёма работ.
- Отсутствие `/debug/rag_latency` блокирует AC-N02.
- Совместимость реальных Docker/Kubernetes и задержка Telegram ещё не проверены.

## Тестирование

Принятое покрытие — 78.006% (2238/2869); порог ≥ 78%. Команда воспроизведения проверок исходного пакета с тестовыми заменами из корня репозитория, с существующим окружением разработки и pytest-cov:

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=workspace/telegram-rag-bot-src:workspace/telegram-rag-bot:. COVERAGE_FILE=/tmp/onboarding-navigator.coverage .venv/bin/python -B -m pytest workspace/telegram-rag-bot-src/tests --ignore=workspace/telegram-rag-bot-src/tests/load_test.py --cov=telegram_rag_bot --cov-config=workspace/telegram-rag-bot-src/pyproject.toml --cov-report=term-missing --cov-fail-under=78 -q -p no:cacheprovider
```

Исторический `tests/load_test.py` исключён, поскольку обращается к файлам учётных данных при импорте; не запускайте его как модульный тест. Во время этой правки документации тесты и команды реального окружения не запускались.
