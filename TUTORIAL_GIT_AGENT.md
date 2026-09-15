# Полный туториал: Запуск ИИ-агента для работы с Git

Этот туториал поможет вам запустить ИИ-агента, который выполняет git-команды по текстовым командам на русском языке.

## Шаг 1: Проверка требований

### 1.1 Убедитесь, что у вас установлен Python 3.11+
```bash
python --version
```
Если Python не установлен, скачайте его с https://www.python.org/downloads/

### 1.2 Убедитесь, что установлен git
```bash
git --version
```
Если git не установлен:
- Windows: https://git-scm.com/download/win
- macOS: `brew install git`
- Linux: `sudo apt-get install git` (Ubuntu/Debian) или `sudo yum install git` (CentOS/RHEL)

## Шаг 2: Установка зависимостей

Перейдите в директорию проекта и установите зависимости:

```bash
cd /workspace
pip install -r requirements.txt
```

**В корпоративной среде Сбербанк:**
Если у вас нет доступа к PyPI или есть ограничения, попробуйте:
```bash
pip install --user -r requirements.txt
```

Или установите пакеты по одному:
```bash
pip install typer rich httpx langchain-core
```

## Шаг 3: Настройка .env файла

Файл `.env` находится в корне проекта (`/workspace/.env`). Откройте его и заполните:

### 3.1 Получите API ключ GigaChat
1. Перейдите на https://developers.sber.ru/
2. Зарегистрируйтесь/войдите
3. Создайте новый проект и получите API ключ (GIGACHAT_CREDENTIALS)

### 3.2 Заполните .env файл

Откройте файл `.env` и замените значения:

```ini
# Обязательно: API ключ GigaChat
GIGACHAT_CREDENTIALS=ваш_ключ_от_sber_developers

# Опционально: Путь к локальному репозиторию (по умолчанию текущая директория)
LOCAL_GIT_REPO_PATH=/путь/к/вашему/репозиторию

# Опционально: Модель GigaChat (по умолчанию GigaChat-Pro)
GIGACHAT_MODEL=GigaChat-Pro
```

**Важно для корпоративной среды:**
- Если у вас есть ограничения на доступ к внешним API, убедитесь, что developers.sber.ru доступен
- Возможно потребуется настройка прокси

## Шаг 4: Подготовка репозитория

### Вариант A: Работа с существующим локальным репозиторием

Если у вас уже есть локальный репозиторий:
```bash
cd /путь/к/репозиторию
```

### Вариант B: Клонирование репозитория с GitHub

Склонируйте ваш репозиторий вручную (до запуска агента):
```bash
git clone https://github.com/ВАШ_USERNAME/ВАШ РЕПОЗИТОРИЙ.git
cd ВАШ РЕПОЗИТОРИЙ
```

**Настройка аутентификации GitHub:**
- HTTPS: используйте Personal Access Token вместо пароля
- SSH: настройте SSH ключи заранее

## Шаг 5: Запуск агента

### Вариант 1: Интерактивный режим

Запустите агента в интерактивном режиме:

```bash
cd /workspace
python -m release_promotion_agent.cli.app git --repo /путь/к/репозиторию
```

Или если вы уже в директории репозитория:
```bash
python -m release_promotion_agent.cli.app git
```

После запуска вы увидите приглашение `Команда >`. Вводите команды на русском языке:

**Примеры команд:**
```
создай файл test.yaml с содержимым hello world в ветке test-branch
переключись на ветку main
покажи статус репозитория
склонируй репозиторий https://github.com/user/repo.git в папку my-repo
покажи diff между ветками main и feature
сделай merge ветки feature в текущую
создай файл 123.yaml внутри которого написано слово Мяу 10 раз в ветку 123p
```

Для выхода введите `exit`.

### Вариант 2: Одноразовое выполнение

Выполнить одну команду без входа в интерактивный режим:

```bash
python -m release_promotion_agent.cli.app git run "создай файл test.txt с hello" --repo /путь/к/репозиторию
```

### Вариант 3: Сухой прогон (dry-run)

Проверить какие команды будут выполнены без фактического выполнения:

```bash
python -m release_promotion_agent.cli.app git --repo /путь/к/репозиторию --dry-run
```

## Шаг 6: Примеры использования

### Пример 1: Создание файла в новой ветке

**Команда:**
```
создай файл config.yaml с содержимым database: postgres в ветке feature-db
```

**Что сделает агент:**
1. Создаст ветку `feature-db`
2. Создаст файл `config.yaml` с содержимым `database: postgres`
3. Добавит файл в git
4. Сделаем коммит с сообщением "создан config.yaml"

### Пример 2: Клонирование репозитория

**Команда:**
```
склонируй репозиторий https://github.com/octocat/Hello-World.git в папку hello-world
```

**Что сделает агент:**
1. Выполнит `git clone https://github.com/octocat/Hello-World.git hello-world`

### Пример 3: Merge веток

**Команда:**
```
сделай merge ветки feature в текущую ветку
```

**Что сделает агент:**
1. Выполнит `git merge feature`

### Пример 4: Просмотр diff

**Команда:**
```
покажи diff между HEAD и HEAD~1
```

**Что сделает агент:**
1. Выполнит `git diff HEAD HEAD~1`
2. Покажет результат

### Пример 5: Ваш пример из запроса

**Команда:**
```
создай файл 123.yaml внутри которого написано слово Мяу 10 раз в ветку 123p
```

**Что сделает агент:**
1. Создаст ветку `123p`
2. Создаст файл `123.yaml` с текстом "Мяу" 10 раз (каждое с новой строки)
3. Добавит файл в git
4. Сделаем коммит

## Шаг 7: Push изменений в GitHub

Агент работает с локальным репозиторием. Чтобы отправить изменения в GitHub:

**В интерактивном режиме:**
```
сделай push ветки 123p в origin
```

Или вручную:
```bash
git push -u origin 123p
```

## Решение проблем

### Ошибка: ModuleNotFoundError: No module named 'typer'

Установите недостающий пакет:
```bash
pip install typer
```

### Ошибка: Команда 'git' не найдена

Установите git:
- Windows: https://git-scm.com/download/win
- macOS: `brew install git`
- Linux: `sudo apt-get install git`

### Ошибка: Не настроен GigaChat

1. Проверьте, что файл `.env` существует и содержит `GIGACHAT_CREDENTIALS`
2. Убедитесь, что API ключ действителен
3. Проверьте доступность developers.sber.ru

### Ошибка: Authentication failed при clone/push

Настройте аутентификацию GitHub:
- Используйте Personal Access Token: https://github.com/settings/tokens
- Или настройте SSH ключи: https://docs.github.com/en/authentication/connecting-to-github-with-ssh

### Ошибка: SSL certificate verify failed

В корпоративной среде может потребоваться настройка прокси или отключение проверки SSL (не рекомендуется):

```ini
# В .env файле (только для тестирования!)
GIGACHAT_VERIFY_SSL=false
```

## Безопасность в корпоративной среде

**Важно!**
- Не коммитьте чувствительные данные (пароли, токены) через агента
- Проверяйте команды перед выполнением (используйте `--dry-run`)
- Убедитесь, что использование внешних API разрешено политикой безопасности
- API ключ GigaChat храните в секрете, не коммитьте `.env` файл

Добавьте `.env` в `.gitignore`:
```bash
echo ".env" >> .gitignore
```

## Дополнительные команды

Получить справку:
```bash
python -m release_promotion_agent.cli.app git --help
```

Проверить конфигурацию:
```bash
python -m release_promotion_agent.cli.app check-config
```

## Поддержка

Если возникли проблемы:
1. Проверьте логи ошибок
2. Убедитесь, что все зависимости установлены
3. Проверьте доступность внешних сервисов
4. Обратитесь к документации проекта
