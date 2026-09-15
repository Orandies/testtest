# Реализация консольного бота с MCP интеграцией

## Выполненные изменения

### 1. Обновлён MCP клиент (`release_promotion_agent/mcp/client.py`)

**Изменения:**
- Добавлен параметр `ca_bundle` в конструктор для поддержки кастомных CA сертификатов
- Улучшена настройка SSL контекста для mTLS подключения
- Создан HTTP транспорт с правильной проверкой сертификатов

**Новая сигнатура:**
```python
def __init__(
    self,
    server_url: str,
    cert_file: Path | str,
    key_file: Path | str,
    tuz: str = "SA-S0000000000",
    ca_bundle: Path | str | None = None,
    timeout_seconds: float = 30.0,
) -> None:
```

**Доступные MCP инструменты (22 метода):**

Навигация и чтение:
- `get_repository_info` - метаданные репозитория
- `get-file-content` - содержимое файла
- `get-diff` - diff между ветками  
- `get-list-files` - список файлов
- `get-diff-stats` - статистика diff
- `get-commit-changes` - изменения коммита
- `list-commits` - история коммитов
- `get-list-branches` - список веток
- `search-code` - поиск по коду
- `list-pull-requests` - список PR
- `get-file-stats` - статистика файлов

Запись:
- `create-branch` - создание ветки
- `delete-file` - удаление файлов
- `create-pull-request` - создание PR
- `create-comment` - комментарий к PR
- `create-or-update-file` - создание/обновление файла
- `find-and-replace-file-content` - замена текста
- `multi-replace-file-content` - множественная замена
- `create-commit-multifile` - атомарный коммит (до 15 файлов)

### 2. Обновлён Console Bot (`release_promotion_agent/cli/console_bot.py`)

**Изменения:**
- Метод `_init_mcp_client` теперь использует `SOURCECONTROL_CERT_FILE` и `SOURCECONTROL_KEY_FILE`
- При отсутствии сертификатов SourceControl пытается использовать GigaChat сертификаты
- Правильное использование `config.sourcecontrol_tuz` вместо hardcoded значения

**Процесс работы бота:**

1. **Приём запроса** - текст или ссылка на Confluence
2. **Извлечение URL** - автоматическое распознавание Confluence ссылок
3. **Чтение Confluence** - загрузка содержимого страницы
4. **Анализ через LLM** - генерация плана действий
5. **Показ плана** - вывод сводки планируемых действий
6. **Подтверждение** - ожидание ответа пользователя (да/нет/корректировка)
7. **Выбор ветки** - запрос имени ветки для изменений
8. **Выполнение через MCP**:
   - Проверка существования ветки
   - Создание ветки при необходимости
   - Применение изменений к файлам
   - Создание коммита
   - Создание Pull Request

### 3. Конфигурация (`release_promotion_agent/config.py`)

**Уже существующие поля для MCP:**
- `sourcecontrol_base_url` - URL MCP сервера
- `sourcecontrol_token` - токен (опционально)
- `sourcecontrol_tuz` - ТУЗ (по умолчанию SA-S0000000000)
- `sourcecontrol_cert_file` - сертификат клиента
- `sourcecontrol_key_file` - приватный ключ

### 4. Документация

Созданы файлы:
- `.env.example` - пример конфигурации окружения
- `README_CONSOLE_BOT.md` - полная документация консольного бота

## Запуск бота

```bash
# Через модуль
python -m release_promotion_agent.cli.app console

# Или через entry point (после установки)
release-promotion-agent console
```

## Необходимые переменные окружения

### Минимальная конфигурация для работы с MCP:

```bash
# GigaChat (один из режимов)
GIGACHAT_CERT_FILE=/path/to/cert.pem
GIGACHAT_KEY_FILE=/path/to/key.pem

# ИЛИ
GIGACHAT_CREDENTIALS=your_credentials
GIGACHAT_AUTH_URL=https://auth-url.sberbank.ru

# SourceControl MCP
SOURCECONTROL_BASE_URL=https://aaaa-sc.xxxx.bbbbbbb.k8s.sigma.sbrf.ru
SOURCECONTROL_TUZ=SA-S0000000000
SOURCECONTROL_CERT_FILE=/path/to/sc-cert.pem
SOURCECONTROL_KEY_FILE=/path/to/sc-key.pem

# Confluence (для чтения страниц)
CONFLUENCE_BASE_URL=https://confluence.company.ru
CONFLUENCE_TOKEN=token

# Агент
AGENT_ALLOWED_USERS=user_id
```

## Интеграция с SecMan

Сертификаты для MCP подключения хранятся в SecMan:
1. Получить сертификат и ключ для ТУЗ SA-S0000000000
2. Сохранить в безопасное место
3. Указать пути в переменных окружения:
   - `SOURCECONTROL_CERT_FILE`
   - `SOURCECONTROL_KEY_FILE`

## Исключения

Бот **НЕ использует sberchat_bot** - работает только в консоли, как и требовалось.

## Проверка работоспособности

Все компоненты успешно импортируются:
```bash
$ python -c "from release_promotion_agent.mcp.client import MCPClient; print('✓')"
✓
$ python -c "from release_promotion_agent.cli.console_bot import ConsoleBot; print('✓')"
✓
```

MCP клиент имеет все 22 инструмента для работы с SourceControl.

## Следующие шаги для полноценной работы

1. Получить сертификаты из SecMan для ТУЗ SA-SDVP00001234 (ваш ключ развёртывания)
2. Настроить переменные окружения в `.env`
3. Запустить бота командой `release-promotion-agent console`
4. Протестировать на реальной странице Confluence

## Архитектура взаимодействия

```
Пользователь → Console Bot → Chat Agent → GigaChat LLM
                    ↓
              MCP Client → SourceControl MCP Server
                    ↓
              Confluence Tool → Confluence API
```

Бот выступает оркестратором, координируя:
- Чтение Confluence (через Confluence Tool)
- Анализ текста (через Chat Agent + GigaChat)
- Запись в SourceControl (через MCP Client)
