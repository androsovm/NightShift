# NightShift MVP

Автономный ночной раннер задач: собирает задачи из внешних источников, выполняет их через Claude Code, прогоняет quality gates и создаёт draft PR.

## CLI

| Команда | Описание |
|---------|----------|
| `nightshift init` | Интерактивный визард: сканирует `~/Projects` + кастомные пути, выбор проектов, источников задач, глобальных лимитов, токенов, расписания. Создаёт `~/.nightshift/config.yaml` и `.nightshift.yaml` в каждом проекте |
| `nightshift add` | Добавление проекта в существующую конфигурацию. Подхватывает лимиты из уже настроенных проектов, проверяет дубликаты, спрашивает токены только для новых источников |
| `nightshift run` | Запуск полного цикла. Флаги: `--dry-run` (показать план), `--project / -p` (один проект) |
| `nightshift status` | Статус последнего запуска: таблица задач, PR, количество изменений |
| `nightshift log` | История запусков. `nightshift log N` — детали задачи N с последними 50 строками лога |
| `nightshift install` | Установка в системный планировщик: launchd (macOS) / systemd (Linux). Показывает предупреждение о sleep prevention |
| `nightshift uninstall` | Удаление из планировщика |
| `nightshift doctor` | Проверка окружения: claude CLI, gh, git, push access, GPG, API-токены, конфиги, sleep prevention |

Глобальный флаг: `--verbose / -v` — DEBUG-уровень логирования.

## Источники задач

| Источник | Откуда берёт задачи | Как закрывает |
|----------|---------------------|---------------|
| **YAML** | Секция `tasks:` в `.nightshift.yaml`, статус `pending` | Ставит `status: done` и `pr_url` в YAML |
| **GitHub Issues** | Issues с меткой `nightshift` (настраивается). Авто-определение repo из git remote | Комментарий со ссылкой на PR + закрытие issue |
| **YouTrack** | Issues с тегом `nightshift` (настраивается). Требует `base_url` и `project_id` | Удаляет тег + комментарий |
| **Trello** | Карточки из списка "NightShift Queue" (настраивается). Требует `board_id` | Перемещает в список "Done" + комментарий |

Расширяемость: entry point `nightshift.sources` для сторонних адаптеров + `nightshift.sources.register()` для программной регистрации.

## Пайплайн выполнения задачи

1. `prepare_repo` — fetch, checkout main, pull (fetch и pull не фатальны при ошибке сети)
2. Сбор задач из всех источников проекта
3. Сортировка по приоритету (high > medium > low), обрезка до `max_tasks_per_run`
4. Для каждой задачи:
   - Создание ветки `nightshift/{slug}-{YYYYMMDD}`
   - Прогон baseline-тестов (`pytest`)
   - Вызов `claude -p <prompt> --dangerously-skip-permissions` с таймаутом
   - Retry до 3 раз при транзиентных ошибках (529, overloaded, rate limit, connection)
   - Quality gates: blast radius, linter (ruff/flake8/eslint), сравнение тестов с baseline
   - Push ветки + создание draft PR через `gh pr create`
   - Отметка задачи как выполненной в источнике
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

## Конфигурация

- **Глобальная**: `~/.nightshift/config.yaml` — расписание, список проектов, лимит PR
- **Проектная**: `.nightshift.yaml` — источники, лимиты, кастомный system prompt для Claude, YAML-задачи
- **Секреты**: `~/.nightshift/.env` (chmod 600) — GITHUB_TOKEN, YOUTRACK_TOKEN, TRELLO_API_KEY, TRELLO_TOKEN

## Хранение и логи

- Результаты запусков: `~/.nightshift/runs/{run_id}.json` (Pydantic → JSON)
- Логи задач: `~/.nightshift/logs/{run_id}/{task-slug}.log`
- Corrupted JSON в runs/ не крашит — пропускается с warning
- Структурное логирование через structlog: JSON-формат для unattended, цветной консольный для `--verbose`

## Prompt для Claude

Автоматически собирается из полей задачи:
- Контекст автономной работы (нет человека, нужно завершить самостоятельно)
- Опциональный `claude_system_prompt` из конфига проекта
- Заголовок, intent, scope (файлы), constraints
- Инструкции: прочитать файлы, реализовать, написать тесты, запустить lint, сделать коммит
- Запрет на создание PR и push (это делает runner)

## Стек

- Python >= 3.13, MIT
- CLI: typer + rich + questionary
- HTTP: httpx (async)
- Валидация: pydantic v2
- Конфиги: pyyaml + python-dotenv
- Логирование: structlog
- Тесты: pytest + pytest-asyncio
