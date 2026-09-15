# Release Promotion Agent — DevLog

## 2026-09-04: Приведение ветки в рабочее состояние

### Изменения

1. **Тесты** — набор снова зелёный, 91 passed. Тест аудит-цепочки обращался
   к модулю по старому имени `chain` после переезда `audit/chain.py`
   в `core/audit_chain.py`.

2. **Конфигурация** — проверка доступов SourceControl и Confluence вынесена
   из загрузки конфигурации в `Config.require_release_mode()`: чат-режиму
   эти доступы не нужны, релизному сценарию — обязательны. `check-config`
   показывает, чего не хватает для релиза, не считая это ошибкой запуска.

3. **Удалены дубликаты** — `tools/confluence_tools.py` и
   `tools/confluence_models.py` повторяли классы из `confluence_tool.py`
   и ни на что не были подключены. Демо-обёртка `app/` полностью
   повторялась пакетом `release_promotion_agent/`; запуск — через CLI.

## 2026-08-13: Merge develop-cdm + develop-sps

### Цель

Объединить две ветки в единый проект с поддержкой всех параметров.

### Изменения

1. **Конфигурация** — объединены параметры обоих веток:
   - mTLS: GIGACHAT_CERT_FILE, GIGACHAT_KEY_FILE, GIGACHAT_KEY_FILE_PASSWORD
   - Token: GIGACHAT_CREDENTIALS, GIGACHAT_SCOPE, GIGACHAT_MODEL
   - URL: GIGACHAT_AUTH_URL, GIGACHAT_BASE_URL, VERIFY_SSL
   - Системные: SOURCECONTROL_*, CONFLUENCE_*

2. **GigaChatClient** — создана поддержка обоих режимов аутентификации

3. **pyproject.toml** — добавлены зависимости langchain, langchain-gigachat, python-dotenv

4. **app/** — создана демо-обёртка из develop-sps для быстрого тестирования

5. **docs/** — добавлена документация из develop-sps (ADR, Architecture, DEVLOG)

### Архитектура после слияния

```
release_promotion_agent/  ← основной пакет (develop-cdm)
├── config.py             ← объединённая конфигурация
├── llm/
│   └── gigachat_client.py  ← mTLS + token auth
├── core/
├── analyzers/
├── sourcecontrol/
├── validation/
└── audit/

app/                      ← демо-обёртка (из develop-sps)
├── main.py
├── config.py
├── agent/
└── prompts/

docs/                     ← документация (из develop-sps)
├── ADR.md
├── Architecture.md
└── DEVLOG.md
```
