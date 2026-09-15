# Настройка бота для работы с Source Control через PAT-токен

## Краткая инструкция для "максимально тупого" 😊

### Шаг 1: Получи PAT-токен в Source Control
1. Зайди в Source Control (https://sc-ci.sber.ru или твой контур)
2. Найди свой репозиторий `sa-sdvp00001234`
3. В настройках репозитория найди раздел **"Keys"** или **"Deployment Keys"** или **"Personal Access Tokens"**
4. Создай новый ключ/токен с правами на **чтение и запись** (read/write)
5. Скопируй токен - он покажется только один раз!

### Шаг 2: Создай файл .env
В корне проекта создай файл `.env` (скопируй из `.env.example`):

```bash
cp .env.example .env
```

### Шаг 3: Заполни .env своими данными
Открой `.env` и заполни следующие переменные:

```ini
# === GigaChat (обязательно!) ===
# Возьми credentials в СберБоксе/AI Hub
GIGACHAT_CREDENTIALS=твои_credentials_от_gigachat
GIGACHAT_AUTH_URL=https://ngw.devices.sberbank.ru:9443/api/v2/oauth
GIGACHAT_SCOPE=GIGACHAT_CORP_PRO

# === Source Control (обязательно!) ===
# URL API твоего Source Control
SOURCECONTROL_BASE_URL=https://api.sc-ci.sber.ru/sc/api/v3

# Тот самый PAT-токен из Шага 1
SOURCECONTROL_TOKEN=abc123xyz...  # <-- вставь сюда свой токен

# Project Key - это ID твоего ТУЗа/репозитория
SOURCECONTROL_PROJECT_KEY=SA-SDVP00001234

# Имя репозитория (можно оставить как PROJECT_KEY если не знаешь)
SOURCECONTROL_REPO_SLUG=sa-sdvp00001234

# === Confluence (если нужно читать страницы) ===
CONFLUENCE_BASE_URL=https://confluence.sberbank.ru
CONFLUENCE_TOKEN=токен_или_пароль_от_confluence

# === Агент ===
# Твой user_id в системе (можно узнать у админа)
AGENT_ALLOWED_USERS=твой_user_id
```

### Шаг 4: Проверка конфигурации
Запусти проверку:
```bash
python -m release_promotion_agent.cli.app check-config
```

Если всё ок - увидишь зелёные галочки. Если есть ошибки - читай сообщение, какая переменная не задана.

### Шаг 5: Запуск бота
```bash
python -m release_promotion_agent.cli.app console
```

### Как это работает:
1. Ты кидаешь боту текст или ссылку на Confluence
2. Бот анализирует через GigaChat и пишет план действий
3. Ты подтверждаешь ("да")
4. Бот спрашивает имя ветки
5. Бот создаёт ветку, делает коммит с изменениями

## Какие параметры нужны в .env (минимум):

| Переменная | Где взять | Пример |
|------------|-----------|--------|
| `GIGACHAT_CREDENTIALS` | СберБокс/AI Hub | `eyJhbGc...` |
| `GIGACHAT_AUTH_URL` | Документация GigaChat | `https://ngw.devices.sberbank.ru:9443/api/v2/oauth` |
| `SOURCECONTROL_BASE_URL` | Адрес твоего Source Control | `https://api.sc-ci.sber.ru/sc/api/v3` |
| `SOURCECONTROL_TOKEN` | Ключ развёртывания в Source Control | `abc123xyz...` |
| `SOURCECONTROL_PROJECT_KEY` | ID твоего ТУЗа | `SA-SDVP00001234` |
| `SOURCECONTROL_REPO_SLUG` | Имя репозитория | `my-repo` |
| `CONFLUENCE_TOKEN` | Токен Confluence | `token...` |
| `AGENT_ALLOWED_USERS` | Твой user_id | `user123` |

## Чего НЕ нужно:
- ❌ Не нужны сертификаты (`SOURCECONTROL_CERT_FILE`, `SOURCECONTROL_KEY_FILE`)
- ❌ Не нужен ТУЗ (`SOURCECONTROL_TUZ`) 
- ❌ Не нужен MCP-сервер
- ❌ Не нужен SecMan для сертификатов

Всё работает через обычный PAT-токен! 🎉
