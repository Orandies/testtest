# Образ агента. Состояние сессии живёт в памяти процесса, поэтому
# постоянное хранилище контейнеру не нужно.
#
# Сборка:
#   docker build -t release-promotion-agent .
#
# Если пакеты ставятся из внутреннего зеркала, индекс передаётся аргументом:
#   docker build --build-arg PIP_INDEX_URL=<адрес зеркала> -t release-promotion-agent .

FROM python:3.11-slim

ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY pyproject.toml ./
COPY release_promotion_agent ./release_promotion_agent
RUN pip install --no-cache-dir .

# Процесс работает не от root.
RUN useradd --create-home agent
USER agent

# Секреты передаются переменными окружения при запуске, в образ не попадают.
ENTRYPOINT ["release-promotion-agent"]
CMD ["demo"]
