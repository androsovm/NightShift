# NightShift MVP

Автономный ночной раннер задач: собирает задачи из внешних источников в локальную очередь, выполняет их через Claude Code, прогоняет quality gates и создаёт draft PR. Человек проверяет PR и закрывает задачу в источнике сам.

## CLI

| Команда | Описание |
|---------|----------|
| `nightshift init` | Интерактивный визард: сканирует `~/Projects` + кастомные пути, выбор проектов, источников задач, глобальных лимитов, токенов, расписания. Создаёт `~/.nightshift/config.yaml` и `.nightshift.yaml` в каждом проекте |
| `nightshift add` | Добавление проекта в существующую конфигурацию. Подхватывает лимиты из уже настроенных проектов, проверяет дубликаты, спрашивает токены только для новых источников |
| `nightshift sync` | Импорт задач из настроенных источников в локальную очередь (`~/.nightshift/tasks.yaml`). Дедупликация по `source_ref` — при конфликте спрашивает пользователя (skip/update/duplicate). Флаг: `--project / -p` |
| `nightshift tasks` | Управление локальной очередью задач (подробнее ниже) |
| `nightshift run` | Выполнение задач из локальной очереди. Не ходит в источники напрямую. Флаги: `--dry-run` (показать план), `--project / -p` (один проект) |
| `nightshift status` | Статус последнего запуска: таблица задач, PR, количество изменений |
| `nightshift log` | История запусков. `nightshift log N` — детали задачи N с последними 50 строками лога |
| `nightshift install` | Установка в системный планировщик: launchd (macOS) / systemd (Linux). Показывает предупреждение о sleep prevention. PATH включает `/opt/homebrew/bin` |
| `nightshift uninstall` | Удаление из планировщика |
| `nightshift doctor` | Проверка окружения: claude CLI, gh, git, push access, GPG, API-токены, конфиги, sleep prevention |

Глобальный флаг: `--verbose / -v` — DEBUG-уровень логирования.

## Управление задачами — `nightshift tasks`

| Подкоманда | Описание |
|------------|----------|
| `nightshift tasks list` | Список задач с фильтрами: `--status`, `--project`, `--priority` |
| `nightshift tasks add` | Добавить задачу вручную (интерактивный ввод: title, project, priority, intent, scope, constraints). `source_type=manual` |
| `nightshift tasks remove <id>` | Удалить задачу из очереди |
| `nightshift tasks edit <id>` | Редактировать поля задачи (интерактивно или через флаги `--title`, `--intent`, `--priority`) |
| `nightshift tasks prioritize <id> <priority>` | Изменить приоритет (high / medium / low) |
| `nightshift tasks skip <id>` | Пометить задачу как skipped |
| `nightshift tasks requeue <id>` | Вернуть задачу в статус pending |
| `nightshift tasks history <id>` | История попыток выполнения: дата, статус, ветка, PR, ошибка, длительность |

## Локальная очередь задач

Задачи хранятся в `~/.nightshift/tasks.yaml` — единый файл для всех проектов. Атомарная запись (temp file + `os.replace`).

Workflow:
1. `nightshift sync` — импорт задач из источников (GitHub, YouTrack, Trello, YAML) в очередь
2. Пользователь управляет задачами: расставляет приоритеты, удаляет ненужные, добавляет свои
3. `nightshift run` — выполняет pending-задачи из очереди, записывает результат (attempt) в историю задачи
4. Пользователь проверяет PR и закрывает задачу в источнике вручную

Каждая задача хранит полную историю попыток выполнения (`TaskAttempt`): timestamp, статус, run_id, ветка, PR URL, ошибка, длительность.

## Источники задач

Источники используются только для импорта через `nightshift sync`. После импорта задачи живут в локальной очереди. Внешние источники не модифицируются автоматически.

| Источник | Откуда берёт задачи | Тег/метка по умолчанию |
|----------|---------------------|------------------------|
| **YAML** | Секция `tasks:` в `.nightshift.yaml`, статус `pending` | — |
| **GitHub Issues** | Issues с настраиваемой меткой. Авто-определение repo из git remote | `nightshift` |
| **YouTrack** | Issues с настраиваемым тегом. Требует `base_url` и `project_id` | `nightshift` |
| **Trello** | Карточки из настраиваемого списка. Требует `board_id` | список "NightShift Queue" |

Расширяемость: entry point `nightshift.sources` для сторонних адаптеров + `nightshift.sources.register()` для программной регистрации.

## Пайплайн выполнения задачи

1. `prepare_repo` — fetch, checkout main, pull (fetch и pull не фатальны при ошибке сети)
2. Загрузка pending-задач из локальной очереди, группировка по проектам
3. Сортировка по приоритету (high > medium > low), обрезка до `max_tasks_per_run`
4. Для каждой задачи:
   - Создание ветки `nightshift/{slug}-{YYYYMMDD}`
   - Прогон baseline-тестов (`pytest`)
   - Вызов `claude -p <prompt> --dangerously-skip-permissions` с таймаутом
   - Retry до 3 раз при транзиентных ошибках (529, overloaded, rate limit, connection, ECONNRESET, ETIMEDOUT)
   - Quality gates: blast radius, linter (ruff/flake8/eslint), сравнение тестов с baseline
   - Push ветки + создание draft PR через `gh pr create`
   - Запись результата (attempt) в историю задачи в очереди
   - Проверка лимита `max_prs_per_night` — при достижении оставшиеся задачи помечаются `skipped`
   - Возврат на main

## Quality gates

| Gate | Что проверяет |
|------|---------------|
| Blast radius | Количество изменённых файлов и строк не превышает лимиты (`max_files_changed`, `max_lines_changed`) |
| Linter | Авто-определяет ruff / flake8 / eslint, запускает на проекте |
| Test regression | Сравнивает количество passed/failed тестов до и после изменений. Падает, если passing уменьшились или failing увеличились |

## Лимиты и ограничения

| Параметр | Default | Уровень |
|----------|---------|---------|
| `max_tasks_per_run` | 5 | Проект (настраивается глобально в визарде) |
| `task_timeout_minutes` | 45 | Проект (настраивается глобально в визарде) |
| `max_files_changed` | 20 | Проект (настраивается глобально в визарде) |
| `max_lines_changed` | 500 | Проект (настраивается глобально в визарде) |
| `max_duration_hours` | 4 | Глобальный |
| `max_prs_per_night` | 10 | Глобальный |
| `schedule.time` | 04:00 | Глобальный |
| `schedule.timezone` | UTC | Глобальный |

## Устойчивость к ошибкам

- **Сетевые сбои git**: `fetch` и `pull` в `prepare_repo` не фатальны — при ошибке логируется warning и продолжается работа с локальным состоянием. Только `checkout main` фатален
- **Claude API**: retry до 3 раз с задержкой 30 секунд при транзиентных ошибках. Таймауты не ретраятся
- **Corrupted storage**: повреждённые JSON-файлы в `runs/` пропускаются с warning, не крашат CLI
- **Event loop**: fallback через `asyncio.new_event_loop()` для окружений с уже запущенным event loop
- **Sleep prevention**: `install` показывает предупреждение, `doctor` проверяет настройки сна (macOS: `pmset`, Linux: `systemctl`)

## Конфигурация

- **Глобальная**: `~/.nightshift/config.yaml` — расписание, список проектов, лимит PR
- **Проектная**: `.nightshift.yaml` — источники, лимиты, кастомный system prompt для Claude, YAML-задачи
- **Очередь задач**: `~/.nightshift/tasks.yaml` — все задачи из всех проектов с историей попыток
- **Секреты**: `~/.nightshift/.env` (chmod 600) — GITHUB_TOKEN, YOUTRACK_TOKEN, TRELLO_API_KEY, TRELLO_TOKEN

## Хранение и логи

- Очередь задач: `~/.nightshift/tasks.yaml` (YAML, атомарная запись)
- Результаты запусков: `~/.nightshift/runs/{run_id}.json` (Pydantic → JSON)
- Логи задач: `~/.nightshift/logs/{run_id}/{task-slug}.log`
- Corrupted JSON в runs/ не крашит — пропускается с warning (перехват `JSONDecodeError` и `ValidationError`)
- Структурное логирование через structlog: JSON-формат для unattended, цветной консольный для `--verbose`
- Логи запусков: `~/.nightshift/logs/{run_id}/run.log` (JSONL)

## Prompt для Claude

Автоматически собирается из полей задачи:
- Контекст автономной работы (нет человека, нужно завершить самостоятельно)
- Опциональный `claude_system_prompt` из конфига проекта
- Заголовок, intent, scope (файлы), constraints
- Инструкции: прочитать файлы, реализовать, написать тесты, запустить lint, сделать коммит
- Запрет на создание PR и push (это делает runner)

## Стек

- Python >= 3.13, MIT, `py.typed`
- CLI: typer + rich + questionary
- HTTP: httpx (async)
- Валидация: pydantic v2
- Конфиги: pyyaml + python-dotenv
- Логирование: structlog (JSON для unattended, цветной консольный для `--verbose`, JSONL в файл)
- Тесты: pytest + pytest-asyncio (170 тестов)
