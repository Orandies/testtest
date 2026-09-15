# Консольный бот для Release Promotion Agent

## Описание

Консольный бот позволяет взаимодействовать с AI-агентом через терминал для анализа Confluence страниц и выполнения изменений в SourceControl через MCP (Model Context Protocol).

## Процесс работы

1. **Пользователь отправляет текст или ссылку на Confluence**
   - Бот автоматически распознаёт URL Confluence
   - Читает содержимое страницы

2. **Анализ запроса**
   - GigaChat анализирует текст/содержимое Confluence
   - Генерирует краткую сводку планируемых действий

3. **Подтверждение плана**
   - Бот показывает план действий
   - Ждёт подтверждения от пользователя (да/нет)
   - При необходимости можно внести корректировки

4. **Выбор ветки**
   - После подтверждения бот спрашивает имя ветки для изменений

5. **Выполнение изменений**
   - Бот подключается к SourceControl через MCP
   - Создаёт ветку (если не существует)
   - Применяет изменения к файлам
   - Создаёт коммит
   - Создаёт Pull Request

## Запуск

```bash
python -m release_promotion_agent.cli.app console
```

Или через команду:
```bash
release-promotion-agent console
```

## Необходимые переменные окружения

### Обязательно

#### GigaChat (один из режимов)

**Режим mTLS:**
```bash
GIGACHAT_CERT_FILE=/path/to/cert.pem
GIGACHAT_KEY_FILE=/path/to/key.pem
```

**ИЛИ режим токена:**
```bash
GIGACHAT_CREDENTIALS=your_credentials_here
GIGACHAT_AUTH_URL=https://auth-url.sberbank.ru
GIGACHAT_SCOPE=GIGACHAT_API_PERS
```

#### Для работы с SourceControl (MCP)
```bash
SOURCECONTROL_BASE_URL=https://aaaa-sc.xxxx.bbbbbbb.k8s.sigma.sbrf.ru
SOURCECONTROL_TUZ=SA-S0000000000
SOURCECONTROL_CERT_FILE=/path/to/sc-cert.pem
SOURCECONTROL_KEY_FILE=/path/to/sc-key.pem
```

#### Для чтения Confluence
```bash
CONFLUENCE_BASE_URL=https://confluence.your-company.ru
CONFLUENCE_TOKEN=your_token_here
```

#### Агент
```bash
AGENT_ALLOWED_USERS=your_user_id
```

## MCP инструменты

Бот использует следующие MCP инструменты для работы с SourceControl:

### Навигация и чтение
- `get_repository_info` - метаданные репозитория
- `get-file-content` - содержимое файла
- `get-diff` - diff между ветками
- `get-list-files` - список файлов
- `get-list-branches` - список веток
- `list-commits` - история коммитов

### Запись
- `create-branch` - создание ветки
- `create-or-update-file` - создание/обновление файла
- `find-and-replace-file-content` - замена текста в файле
- `multi-replace-file-content` - множественная замена
- `create-commit-multifile` - атомарный коммит нескольких файлов
- `create-pull-request` - создание PR
- `create-comment` - комментарий к PR

## Интеграция с SecMan

Сертификаты для MCP подключения хранятся в SecMan и загружаются через переменные окружения:
- `SOURCECONTROL_CERT_FILE` - сертификат клиента
- `SOURCECONTROL_KEY_FILE` - приватный ключ

## Пример сессии

```
$ python -m release_promotion_agent.cli.app console

╭─────────────────────────────────────────────╮
│ Release Promotion Agent - Console Bot       │
│                                             │
│ Отправьте текст или ссылку на Confluence    │
│ для анализа.                                │
│ Бот проанализирует и напишет план действий. │
│ Для выхода введите 'exit' или 'quit'        │
╰─────────────────────────────────────────────╯

✓ MCP подключён к SourceControl

Введите запрос > https://confluence.company.ru/pages/123456

📄 Найдена ссылка на Confluence: https://confluence.company.ru/pages/123456
✓ Страница прочитана: План релиза v2.0

🤖 Анализ запроса...

╭─────────────────────────────────────────────╮
│ 📋 Сводка планируемых действий              │
│                                             │
│ План действий:                              │
│ 1. Обновить config.yaml в репозитории X     │
│ 2. Изменить параметр VERSION на 2.0         │
│ 3. Добавить новый endpoint в api.conf       │
│                                             │
│ Подтвердите выполнение (да/нет)             │
╰─────────────────────────────────────────────╯

Выполнить план? (да/нет) > да
✓ План подтверждён

В какой ветке сделать изменения? > feature/release-v2.0

Ключ репозитория? > my-repo

🔧 Выполнение изменений в ветке feature/release-v2.0...
[dim]Создание ветки feature/release-v2.0...[/dim]
[dim]Применение изменений...[/dim]
[dim]Создание pull request...[/dim]
✓ Изменения выполнены: Committed: abc123, PR: https://sc.company.ru/pr/456
```

## Исключения

Бот **НЕ** использует sberchat_bot - работает только в консоли.

## Безопасность

- Все секреты читаются только из переменных окружения
- mTLS используется для подключения к MCP серверу
- ТУЗ (ТУЗ: SA-S0000000000) указывается для идентификации сервиса
- Проверка сертификата сервера включена по умолчанию
