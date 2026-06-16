# Руководство по настройке и запуску work-agent

Подробная инструкция: установка, конфигурация, провайдеры LLM, запуск всех
фронтендов (CLI, веб-дашборд, Telegram), планировщик задач и эксплуатация в
Docker. Краткий обзор — в [README.md](README.md), архитектура — в
[DESIGN.md](DESIGN.md).

---

## 1. Предварительные требования

- **Python ≥ 3.11** (для локального запуска) или **Docker** + **Docker Compose**.
- **API-ключ** хотя бы одного провайдера:
  - Anthropic (Claude) → `ANTHROPIC_API_KEY`
  - DeepSeek → `DEEPSEEK_API_KEY`
  - любой OpenAI-совместимый эндпоинт (vLLM, Ollama, OpenRouter) → `OPENAI_API_KEY`
    (локальным моделям ключ часто не нужен)
- (Опционально) **Telegram bot token** → `TELEGRAM_BOT_TOKEN` (получить у
  [@BotFather](https://t.me/BotFather)).

---

## 2. Установка

### Вариант A. Docker (рекомендуется)

```bash
git clone https://github.com/kozlov-dmit/work-agent.git
cd work-agent

cp .env.example .env            # вписать ключи (+ TELEGRAM_BOT_TOKEN при необходимости)
cp config.example.yaml config.yaml
mkdir -p workspace              # рабочие файлы агента (volume)

docker compose up               # поднимает web (дашборд) + telegram + scheduler
# → дашборд: http://localhost:8000/dashboard
```

`docker compose up` поднимает **сразу три** долгоживущих сервиса: `web`
(чат + дашборд на порту 8000), `telegram` (нужен `TELEGRAM_BOT_TOKEN`) и
единственный `scheduler`. Образ ставит агента вместе с extras `web` и `telegram`,
поднимает непривилегированного пользователя `agent`, монтирует `/workspace`. При
старте контейнера автоматически выполняется `work-agent bootstrap` (переустановка
самостоятельно доустановленных инструментов).

Разовые команды по-прежнему доступны: `docker compose run --rm web chat`,
`docker compose run --rm web run "задача"`.

### Вариант B. Локально (Python)

```bash
git clone https://github.com/kozlov-dmit/work-agent.git
cd work-agent

python -m venv .venv && source .venv/bin/activate
pip install -e .                # ядро
pip install -e ".[web]"         # + веб-сервер и дашборд (fastapi, uvicorn, psutil)
pip install -e ".[telegram]"    # + Telegram-бот
# или всё сразу для разработки:
pip install -e ".[dev,web,telegram]"
```

> При локальном запуске рабочая директория по умолчанию `/workspace` (см.
> `sandbox.workdir`). Локально задайте свой путь в `config.yaml`, иначе
> файловые инструменты и состояние будут указывать на `/workspace`.

---

## 3. Переменные окружения

| Переменная | Назначение |
|---|---|
| `ANTHROPIC_API_KEY` | Ключ Anthropic (провайдер `anthropic`) |
| `DEEPSEEK_API_KEY` | Ключ DeepSeek (провайдер `deepseek`) |
| `OPENAI_API_KEY` | Ключ для OpenAI-совместимых эндпоинтов |
| `TELEGRAM_BOT_TOKEN` | Токен бота (для `telegram` и Telegram-доставки задач) |
| `WORK_AGENT_CONFIG` | Путь к config-файлу (имеет приоритет при поиске) |
| `WORK_AGENT_PROVIDER` | Переопределить `provider` |
| `WORK_AGENT_MODEL` | Переопределить `model` |
| `WORK_AGENT_BASE_URL` | Переопределить `base_url` |
| `WORK_AGENT_API_KEY_ENV` | Переопределить имя env-переменной с ключом |

Ключ под каждый провайдер выбирается автоматически (`ANTHROPIC_API_KEY` /
`DEEPSEEK_API_KEY` / `OPENAI_API_KEY`), если `api_key_env` оставлен по умолчанию.

---

## 4. Конфигурация (`config.yaml`)

Приоритет источников (по возрастанию): значения по умолчанию → `config.yaml` →
переменные окружения → флаги CLI.

**Поиск файла**, если `--config` не задан: `WORK_AGENT_CONFIG` →
`/workspace/.work-agent/config.yaml` → `./config.yaml`.

Полный пример со всеми разделами:

```yaml
# --- основной провайдер/модель ---
provider: anthropic            # anthropic | deepseek | openai_compatible
model: claude-opus-4-8         # для non-anthropic — имя модели эндпоинта
api_key_env: ANTHROPIC_API_KEY # имя env-переменной с ключом
base_url: null                 # для openai_compatible (vLLM/Ollama/OpenRouter)

# --- параметры цикла ---
agent:
  max_iterations: 50           # потолок шагов tool-use за один ход
  effort: high                 # anthropic: low | medium | high | xhigh | max

# --- компакция длинных диалогов ---
compaction:
  enabled: true
  threshold_tokens: 40000      # свернуть старое сверх порога (для Claude можно выше)
  keep_recent: 12              # сколько последних сообщений хранить дословно

# --- добавка к системному промпту (правится и из дашборда) ---
system_prompt_extra: ""

# --- маршрутизация моделей по целям ---
default_profile: chat
profiles:
  chat:        { provider: anthropic, model: claude-opus-4-8 }
  search:      { provider: deepseek,  model: deepseek-chat }
  development: { provider: anthropic, model: claude-opus-4-8, effort: xhigh }
  analysis:    { provider: openai_compatible, model: llama3.1,
                 base_url: http://host.docker.internal:11434/v1 }

# --- инструменты и разрешения ---
tools:
  enabled: [bash, read, write, edit, glob, grep, http_request,
            install_tool, configure, skill, skill_write, delegate, schedule]
  permissions:
    default: ask               # allow | ask | deny
    overrides:
      read: allow
      glob: allow
      grep: allow
      skill: allow
      delegate: allow

# --- рабочая директория (sandbox) ---
sandbox:
  workdir: /workspace
```

### Провайдеры — примеры

**Anthropic (по умолчанию):**
```yaml
provider: anthropic
model: claude-opus-4-8
```

**DeepSeek:**
```yaml
provider: deepseek
model: deepseek-chat           # поддерживает tool use; reasoner — ограниченно
```

**Локальная модель через Ollama (OpenAI-совместимо):**
```yaml
provider: openai_compatible
model: llama3.1
api_key_env: OPENAI_API_KEY    # Ollama ключ не проверяет
base_url: http://host.docker.internal:11434/v1
```

### Маршрутизация моделей по целям

`profiles` задаёт отдельную LLM под каждую цель. Основной диалог идёт на
`default_profile`, а инструмент `delegate` направляет профильные подзадачи на
`search` / `development` / `analysis`. Поле, не указанное в профиле, наследуется
из верхнего уровня; при смене провайдера без явной модели берётся дефолт
провайдера.

### Разрешения инструментов

- `allow` — выполнять без спроса; `ask` — спрашивать; `deny` — запрещать.
- В интерактивном CLI `ask` показывает запрос подтверждения; флаг `--yolo`
  авто-подтверждает.
- В веб- и Telegram-фронтендах, а также в запланированных задачах `ask`
  авто-подтверждается (граница изоляции — контейнер), но `deny` всегда
  соблюдается.

---

## 5. Запуск

### CLI

```bash
work-agent chat                       # интерактивный REPL
work-agent run "опиши файлы в каталоге"   # одноразовая задача
work-agent tools list                 # список доступных инструментов
work-agent --config ./config.yaml chat
work-agent --yolo run "..."           # без подтверждений
```

### Веб-сервер с дашбордом

```bash
# локально
work-agent serve --host 0.0.0.0 --port 8000
# docker (входит в `docker compose up`); отдельно:
docker compose up web
```

- Чат: `http://localhost:8000/`
- Дашборд: `http://localhost:8000/dashboard`
  - **Metrics** — расход токенов, надёжность LLM и счётчики инструментов
    (агрегат со всех процессов); системные метрики (CPU/RAM/сеть) — в разрезе
    по сервисам (web/telegram/scheduler). Автообновление.
  - **Scheduled tasks** — просмотр/добавление/вкл-выкл/удаление cron-задач.
  - **Config** — выбор моделей по ролям, default-профиль, добавка к системному
    промпту, effort, политика разрешений, max_iterations (сохраняется в
    config-файл).
- Health-check: `GET /healthz`.

### Telegram-бот

```bash
export TELEGRAM_BOT_TOKEN=123456:ABC...
work-agent telegram
# docker (входит в `docker compose up`); отдельно:
docker compose up telegram
```

- Каждый чат — своя сессия; история **персистентна** (переживает рестарт),
  `/reset` очищает, `/start` — приветствие.
- Внутри бота работает **резервный планировщик** (см. ниже про выбор лидера),
  поэтому задачи выполняются даже если отдельный сервис `scheduler` не поднялся.

### Планировщик задач (cron)

Агент создаёт задачи из диалога: напишите ему, например,
«присылай новостной дайджест каждое утро в 9:00» — он зарегистрирует cron-задачу
инструментом `schedule`. **Сама по себе задача планировщик не запускает** — её
выполнит уже работающий сервис `scheduler` (он входит в `docker compose up`).

Запуск/управление:
```bash
work-agent scheduler                  # отдельный процесс-исполнитель
work-agent schedule list              # посмотреть задачи
work-agent schedule remove <id>       # удалить задачу
# docker — поднимается вместе со всеми по `docker compose up`; отдельно:
docker compose up scheduler
```

- **Отказоустойчивость через выбор лидера.** Цикл планировщика работает во всех
  долгоживущих сервисах (web, telegram, scheduler), но задачи выполняет только
  держатель **аренды-лидерства** (атомарный лок в SQLite) — двойного запуска нет.
  Если лидер умер, аренду по истечении TTL перехватывает другой живой сервис,
  поэтому задачи идут, пока поднят хоть один сервис. Инструмент `schedule`
  предупреждает, если в момент добавления ни один планировщик не живой.
- Доставка результата: в Telegram-чат (если задача создана с такой целью и задан
  `TELEGRAM_BOT_TOKEN`) либо в файл
  `/workspace/.work-agent/schedule-output/<id>/`.
- Время трактуется в таймзоне задачи (IANA), иначе — локальное время контейнера.

Формат cron: `минута час день месяц день_недели`. Примеры:
`0 9 * * *` — каждый день в 09:00; `0 9 * * 1-5` — по будням в 09:00;
`*/30 * * * *` — каждые 30 минут.

---

## 6. Возможности агента (кратко)

- **Самоустановка инструментов** (`install_tool`): `apt`/`pip`/`npm`; пишется в
  манифест и переустанавливается при старте контейнера (`work-agent bootstrap`).
- **Самоконфигурация** (`configure`): включение/выключение инструментов на лету,
  смена модели/эффорта/прав — сохраняется в config-файл.
- **Скилы** (`skill`, `skill_write`): переиспользуемые инструкции; агент сам
  создаёт и дописывает их по вашим замечаниям. Хранятся в
  `/workspace/.work-agent/skills/`.
- **Делегирование** (`delegate`): подзадача уходит на профильную модель.
- **Расписание** (`schedule`): cron-задачи (см. выше).

---

## 7. Состояние и тома

Всё постоянное состояние — в `/<workdir>/.work-agent/` (по умолчанию
`/workspace/.work-agent/`), который монтируется как Docker volume:

| Путь | Назначение |
|---|---|
| `provisioning.json` | манифест самоустановленных пакетов |
| `skills/<name>/SKILL.md` | скилы |
| `sessions/telegram-<chat_id>.json` | история Telegram-чатов |
| `schedules.json` | запланированные cron-задачи |
| `schedule-output/<id>/` | результаты задач при доставке в лог |
| `metrics.db` | общие метрики (SQLite), агрегируются со всех процессов |
| `config.yaml` | конфиг, если агент сохранил его сюда |

В `docker-compose.yml` каталог `./workspace` хоста смонтирован в `/workspace`, а
`./config.yaml` — в `/app/config.yaml` (на запись, чтобы дашборд/`configure`
могли сохранять изменения; путь задан через `WORK_AGENT_CONFIG`).

---

## 8. Docker Compose — детали

`docker compose up` поднимает три сервиса (общий образ через YAML-anchor,
`restart: unless-stopped`):

| Сервис | Команда | Назначение |
|---|---|---|
| `web` | `serve` | чат + дашборд на порту `8000` |
| `telegram` | `telegram` | Telegram-бот (нужен `TELEGRAM_BOT_TOKEN`) |
| `scheduler` | `scheduler` | единственный исполнитель cron-задач |

```bash
docker compose up                 # все три сервиса
docker compose up web             # только дашборд/чат
docker compose run --rm web chat  # разовый интерактивный чат
docker compose run --rm web run "ваша задача"
```

- Порт `8000` проброшен сервисом `web`.
- Планировщик ровно один (сервис `scheduler`); Telegram-бот свой не запускает —
  двойного срабатывания задач нет.
- Если `TELEGRAM_BOT_TOKEN` не задан, сервис `telegram` будет падать и
  перезапускаться — закомментируйте его в `docker-compose.yml`, если бот не нужен.

> **Модель доверия.** Контейнер — граница изоляции и считается single-tenant,
> untrusted-by-default. Пользователю `agent` выдан беспарольный `sudo` (нужен для
> `apt` при самоустановке). Не запускайте недоверенные задачи в одном контейнере
> с чувствительными данными; ограничивайте сетевые доступы на уровне Docker.

---

## 9. Проверка и тесты

```bash
pip install -e ".[dev,web,telegram]"
pytest -q
```

Быстрая проверка без ключей:
```bash
work-agent tools list
work-agent --config ./config.yaml schedule list
```

---

## 10. Типичные проблемы

| Симптом | Причина / решение |
|---|---|
| `Missing API key: set $...` | Не задан ключ выбранного провайдера в окружении/`.env`. |
| `Web extras not installed` | `pip install -e ".[web]"` (или используйте Docker-образ). |
| `Telegram extras not installed` | `pip install -e ".[telegram]"`. |
| `Missing bot token` | Не задан `TELEGRAM_BOT_TOKEN`. |
| Системные метрики «n/a» на дашборде | Не установлен `psutil` (входит в extra `web`). |
| Файловые инструменты не находят файлы локально | `sandbox.workdir` указывает на `/workspace` — задайте свой путь в `config.yaml`. |
| Задачи не срабатывают | Запущен ли исполнитель (`work-agent scheduler` или Telegram-бот)? Проверьте cron и таймзону через `schedule list`. |
| `./config.yaml` смонтировался как каталог в Docker | Перед `up` создайте файл: `cp config.example.yaml config.yaml`. |
