# Release Promotion Agent (RPA)

> Обзор на одну страницу. Архитектура целиком — в [01_ARCHITECTURE.md](01_ARCHITECTURE.md),
> состояние модулей и что стоит проверить — в [05_STATUS.md](05_STATUS.md).

## Цель

Агент для автоматизации подготовки релизных изменений конфигурационных YAML-файлов
с последующим созданием pull request в системе контроля версий (SourceControl).

## Основной стек

- Python 3.11+
- LangChain
- langchain-gigachat
- GigaChat API (mTLS или token auth)
- Pydantic v2
- Docker

## Архитектура

```
чат-бот / CLI
    ↓
Release Promotion Agent
    ↓
Оркестратор (FSM)
    ↓
Analyzers (diff, intent, reconciliation)
    ↓
GigaChat Client (mTLS / token)
    ↓
Tools (SourceControl, Confluence)
```

## Модули

- `agents` — release_agent (релизный сценарий) и chat_agent (диалог)
- `analyzers` — анализ diff веток, определение намерений, сверка факта и плана
- `cli` — командный интерфейс (typer)
- `core` — FSM, контекст сессии, аудит-цепочка, логирование, редакция секретов
- `llm` — клиент GigaChat, поддержка mTLS и token auth
- `models` — общие модели ответа и статистики
- `prompts` — сборка системного промпта по частям
- `tools` — SourceControl (`git_tool`) и Confluence (`confluence_tool`)
- `validation` — валидация кандидатов на основе правил

## Запуск

```bash
# Проверить конфигурацию
release-promotion-agent check-config

# Прогон сценария на подставных данных, без сети
release-promotion-agent demo

# Диалоговый режим
release-promotion-agent chat
```
