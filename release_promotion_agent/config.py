"""Конфигурация агента. Секреты читаются только из переменных окружения.

Локально они приходят из файла .env, загруженного в окружение процесса;
на сервере — из системы управления секретами. Код при этом не меняется.

Config.load() вызывается первым шагом, до любого сетевого вызова, и при
неполной конфигурации сообщает сразу обо всех проблемах.

Поддерживаются два режима аутентификации GigaChat:
  1. Взаимная TLS (mTLS) — GIGACHAT_CERT_FILE + GIGACHAT_KEY_FILE.
  2. Токен (credentials) — GIGACHAT_CREDENTIALS.
Необходимо задать параметры хотя бы одного режима.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, SecretStr

from release_promotion_agent.core.errors import ConfigError

# Загружаем переменные из .env файла, если он есть.
# На сервере переменные приходят из системы управления секретами —
# в этом случае .env не нужен.
load_dotenv()

# Системные переменные для orchestrator-режима (создание PR, Git, Confluence).
# Для chat-режима (только GigaChat) эти переменные не обязательны.
# Оркестратор требует: SOURCECONTROL + CONFLUENCE + AGENT_ALLOWED_USERS.
# Chat-агент требует: только GIGACHAT_CREDENTIALS или mTLS.


class Config(BaseModel):
    """Проверенная конфигурация агента.

    Собирается один раз методом load и дальше не меняется. Секреты лежат
    в SecretStr: в текстовое представление объекта они не попадают, и
    случайная печать конфигурации в лог их не раскрывает. Значения
    секретов отдаются наружу только методом secret_values — им
    пользуется фильтр логов, чтобы знать, что вырезать.

    Обязателен ровно один пункт: режим аутентификации модели. Доступы к
    системе контроля версий и Confluence нужны только релизному
    сценарию, поэтому проверяются не при старте, а перед первым
    обращением к ним — см. require_release_mode.
    """

    model_config = ConfigDict(frozen=True)

    # ── SourceControl ──────────────────────────────────────────────────
    # Опционально: нужно только для orchestrator-режима.
    sourcecontrol_base_url: str | None = None
    sourcecontrol_token: SecretStr | None = None

    # ── Confluence ─────────────────────────────────────────────────────
    # Опционально: нужно только для orchestrator-режима.
    confluence_base_url: str | None = None
    confluence_token: SecretStr | None = None
    # Проверка сертификата сервера включена по умолчанию: без неё нельзя
    # отличить настоящий Confluence от того, кто им притворился, а из
    # Confluence приходит план установки — один из двух источников правды.
    confluence_verify_ssl: bool = True
    # Корневой сертификат внутреннего удостоверяющего центра. Задан — проверка
    # идёт по нему, и выключать её из-за самоподписанного сертификата не нужно.
    confluence_ca_bundle: Path | None = None

    # ── GigaChat: взаимная TLS (mTLS) ─────────────────────────────────
    # Один из режимов (mTLS или token) должен быть задан.
    gigachat_cert_file: Path | None = None
    gigachat_key_file: Path | None = None
    gigachat_key_file_password: SecretStr | None = None

    # ── GigaChat: токен (credentials) ─────────────────────────────────
    gigachat_credentials: SecretStr | None = None
    gigachat_scope: str | None = None
    gigachat_model: str = "GigaChat-2"
    # Адрес сервиса аутентификации приходит из окружения: адреса контуров
    # в коде не хранятся, у разных стендов они разные.
    gigachat_auth_url: str | None = None
    gigachat_base_url: str = "https://gigachat.devices.sberbank.ru/api/v1/"
    gigachat_verify_ssl: bool = False
    # Параметры генерации для более естественных ответов
    gigachat_temperature: float = 0.7
    gigachat_top_p: float = 0.9

    # ── Уведомления в чат (необязательно) ─────────────────────────────
    sberchat_webhook_token: SecretStr | None = None

    # ── SberChat бот ─────────────────────────────────────────────────
    # Токен бота SberChat (получить через @SberChatBot).
    sberchat_bot_token: SecretStr | None = None
    # Путь к PEM-файлу корневого CA-сертификата.
    sberchat_root_certs: Path | None = None
    # Sandbox окружение.
    sberchat_sandbox: bool = False

    # ── Агент ─────────────────────────────────────────────────────────
    # Команды принимаются только от перечисленных пользователей.
    allowed_users: tuple[str, ...]
    log_level: str = "INFO"

    # ── методы ─────────────────────────────────────────────────────────

    def is_authorized(self, user_id: str) -> bool:
        return user_id in self.allowed_users

    @property
    def use_mtls(self) -> bool:
        """mTLS используется, если заданы и сертификат, и ключ."""
        return (
            self.gigachat_cert_file is not None
            and self.gigachat_key_file is not None
            and self.gigachat_cert_file.is_file()
            and self.gigachat_key_file.is_file()
        )

    @property
    def use_token(self) -> bool:
        """Токен используется, если заданы credentials."""
        return self.gigachat_credentials is not None

    @property
    def has_sourcecontrol(self) -> bool:
        """Есть ли настроен SourceControl (orchestrator-режим)."""
        return self.sourcecontrol_base_url is not None and self.sourcecontrol_token is not None

    @property
    def confluence_tls_verify(self) -> bool | str:
        """Значение параметра проверки сертификата для httpx и requests.

        Путь к корневому сертификату, если он задан: проверка идёт по
        внутреннему удостоверяющему центру. Иначе True или False.
        """
        if self.confluence_ca_bundle is not None:
            return str(self.confluence_ca_bundle)
        return self.confluence_verify_ssl

    @property
    def has_confluence(self) -> bool:
        """Есть ли настроен Confluence."""
        return self.confluence_base_url is not None and self.confluence_token is not None

    @property
    def has_llm(self) -> bool:
        """Есть ли настроенная языковая модель."""
        return self.use_mtls or self.use_token

    @property
    def has_sberchat_bot(self) -> bool:
        """Есть ли настроен SberChat бот."""
        return self.sberchat_bot_token is not None

    def missing_for_release(self) -> tuple[str, ...]:
        """Переменные, без которых релизный сценарий не поедет.

        Проверяются не при старте: чат-режим работает вообще без
        SourceControl и Confluence, и требовать их у всех подряд означало бы
        не пускать инженера в чат из-за доступов, которые ему там не нужны.
        Fail-fast никуда не делся — он сместился к первому обращению
        к внешним системам, см. require_release_mode().
        """
        missing: list[str] = []
        if self.sourcecontrol_base_url is None:
            missing.append("SOURCECONTROL_BASE_URL")
        if self.sourcecontrol_token is None:
            missing.append("SOURCECONTROL_TOKEN")
        if self.confluence_base_url is None:
            missing.append("CONFLUENCE_BASE_URL")
        if self.confluence_token is None:
            missing.append("CONFLUENCE_TOKEN")
        if not self.allowed_users:
            missing.append("AGENT_ALLOWED_USERS")
        return tuple(missing)

    def require_release_mode(self) -> None:
        """Проверка перед релизным сценарием: либо всё есть, либо не стартуем."""
        missing = self.missing_for_release()
        if missing:
            raise ConfigError(
                "Для релизного сценария не хватает переменных окружения:\n  - "
                + "\n  - ".join(missing)
            )

    def secret_values(self) -> tuple[str, ...]:
        """Значения секретов для фильтра, вырезающего их из логов.

        Токены SourceControl и Confluence необязательны — в чат-режиме их
        нет вовсе. Поэтому каждый берётся только если задан: иначе настройка
        логирования падала бы ровно там, где вырезать нечего.
        """
        secrets: list[str] = []
        if self.sourcecontrol_token is not None:
            secrets.append(self.sourcecontrol_token.get_secret_value())
        if self.confluence_token is not None:
            secrets.append(self.confluence_token.get_secret_value())
        if self.gigachat_key_file_password is not None:
            secrets.append(self.gigachat_key_file_password.get_secret_value())
        if self.gigachat_credentials is not None:
            secrets.append(self.gigachat_credentials.get_secret_value())
        if self.sberchat_webhook_token is not None:
            secrets.append(self.sberchat_webhook_token.get_secret_value())
        if self.sberchat_bot_token is not None:
            secrets.append(self.sberchat_bot_token.get_secret_value())
        return tuple(s for s in secrets if s)

    @classmethod
    def load(cls, env: Mapping[str, str] | None = None) -> Config:
        """Читает окружение и собирает все проблемы в одну ошибку."""
        source = os.environ if env is None else env
        problems: list[str] = []

        # Опциональные параметры SourceControl (только для orchestrator-режима).
        sc_base = source.get("SOURCECONTROL_BASE_URL", "").rstrip("/") or None
        sc_token = source.get("SOURCECONTROL_TOKEN") or None

        # Список пользователей задаётся через запятую. Историческое имя
        # переменной с префиксом AKK_ продолжает работать: у части инженеров
        # оно уже прописано в .env, и переименование не должно ломать запуск.
        allowed_users: tuple[str, ...] = ()
        raw_users = source.get("AGENT_ALLOWED_USERS") or source.get("AKK_ALLOWED_USERS", "")
        if raw_users.strip():
            allowed_users = tuple(u.strip() for u in raw_users.split(",") if u.strip())
            if not allowed_users:
                problems.append("AGENT_ALLOWED_USERS задана, но список пуст")

        # ── GigaChat: mTLS ─────────────────────────────────────────────
        cert_file = Path(source.get("GIGACHAT_CERT_FILE", "") or "")
        key_file = Path(source.get("GIGACHAT_KEY_FILE", "") or "")
        has_cert = bool(source.get("GIGACHAT_CERT_FILE", "").strip())
        has_key = bool(source.get("GIGACHAT_KEY_FILE", "").strip())

        if has_cert and has_key:
            if not cert_file.is_file():
                problems.append(f"GIGACHAT_CERT_FILE: файл не найден: {cert_file}")
            if not key_file.is_file():
                problems.append(f"GIGACHAT_KEY_FILE: файл не найден: {key_file}")
        elif has_cert or has_key:
            problems.append("для mTLS нужны оба параметра: GIGACHAT_CERT_FILE и GIGACHAT_KEY_FILE")

        # ── GigaChat: токен ────────────────────────────────────────────
        has_creds = bool(source.get("GIGACHAT_CREDENTIALS", "").strip())
        if has_creds:
            raw_creds = source.get("GIGACHAT_CREDENTIALS", "")
            raw_scope = source.get("GIGACHAT_SCOPE", "")
            model = source.get("GIGACHAT_MODEL", "GigaChat-2").strip() or "GigaChat-2"
            auth_url = source.get("GIGACHAT_AUTH_URL", "").strip() or None
            if auth_url is None:
                problems.append(
                    "для режима токена нужен GIGACHAT_AUTH_URL — "
                    "адрес сервиса аутентификации вашего контура"
                )
            base_url = (
                source.get("GIGACHAT_BASE_URL", "").strip()
                or "https://gigachat.devices.sberbank.ru/api/v1/"
            )
            verify_ssl = (
                source.get("VERIFY_SSL", "false").lower() == "true"
                or source.get("GIGACHAT_VERIFY_SSL", "false").lower() == "true"
            )
            # Параметры генерации для более естественных ответов
            temperature_raw = source.get("GIGACHAT_TEMPERATURE", "0.7")
            try:
                temperature = float(temperature_raw)
            except ValueError:
                temperature = 0.7
                problems.append(f"GIGACHAT_TEMPERATURE должно быть числом, используется {temperature}")
            
            top_p_raw = source.get("GIGACHAT_TOP_P", "0.9")
            try:
                top_p = float(top_p_raw)
            except ValueError:
                top_p = 0.9
                problems.append(f"GIGACHAT_TOP_P должно быть числом, используется {top_p}")
        else:
            raw_scope = None
            model = None
            auth_url = None
            base_url = None
            verify_ssl = False
            temperature = 0.7
            top_p = 0.9

        # ── Выбор режима ───────────────────────────────────────────────
        if not has_cert and not has_key and not has_creds:
            problems.append(
                "не задан режим аутентификации GigaChat: "
                "GIGACHAT_CERT_FILE + GIGACHAT_KEY_FILE (mTLS) "
                "или GIGACHAT_CREDENTIALS (токен)"
            )

        # ── Конфлюенс (опционально для chat-режима) ───────────────────
        conf_base = source.get("CONFLUENCE_BASE_URL", "").rstrip("/") or None
        conf_token = source.get("CONFLUENCE_TOKEN") or None

        # Проверка сертификата включена, пока её явно не выключили. Если у
        # сервера самоподписанный сертификат, правильный путь — положить
        # корневой сертификат внутреннего удостоверяющего центра и указать
        # его в CONFLUENCE_CA_BUNDLE; выключение проверки остаётся крайней
        # мерой и видно в выводе check-config.
        conf_verify = source.get("CONFLUENCE_VERIFY_SSL", "true").strip().lower() != "false"
        conf_ca_raw = source.get("CONFLUENCE_CA_BUNDLE", "").strip()
        conf_ca = Path(conf_ca_raw) if conf_ca_raw else None
        if conf_ca is not None and not conf_ca.is_file():
            problems.append(f"CONFLUENCE_CA_BUNDLE: файл не найден: {conf_ca}")

        # ── Опциональные параметры ──────────────────────────────────────
        key_password = source.get("GIGACHAT_KEY_FILE_PASSWORD")
        webhook_token = source.get("SBERCHAT_WEBHOOK_TOKEN")

        # ── SberChat бот ───────────────────────────────────────────────
        bot_token = source.get("SBERCHAT_BOT_TOKEN")
        root_certs_raw = source.get("SBERCHAT_ROOT_CERTS", "").strip()
        root_certs = Path(root_certs_raw) if root_certs_raw else None
        if root_certs is not None and not root_certs.is_file():
            problems.append(f"SBERCHAT_ROOT_CERTS: файл не найден: {root_certs}")
        sandbox = source.get("SBERCHAT_SANDBOX", "false").strip().lower() == "true"

        log_level = (source.get("AGENT_LOG_LEVEL") or source.get("AKK_LOG_LEVEL", "INFO")).upper()

        if problems:
            raise ConfigError(
                "Конфигурация неполна, агент не стартует:\n  - " + "\n  - ".join(problems)
            )

        return cls(
            # SourceControl (опционально)
            sourcecontrol_base_url=sc_base,
            sourcecontrol_token=SecretStr(sc_token) if sc_token else None,
            # Confluence (опционально)
            confluence_base_url=conf_base,
            confluence_token=SecretStr(conf_token) if conf_token else None,
            confluence_verify_ssl=conf_verify,
            confluence_ca_bundle=conf_ca,
            # GigaChat mTLS
            gigachat_cert_file=cert_file if has_cert else None,
            gigachat_key_file=key_file if has_key else None,
            gigachat_key_file_password=(SecretStr(key_password) if key_password else None),
            # GigaChat token
            gigachat_credentials=(SecretStr(raw_creds) if has_creds else None),
            gigachat_scope=raw_scope
            if raw_scope
            else Config.model_fields["gigachat_scope"].default,
            gigachat_model=model if model else Config.model_fields["gigachat_model"].default,
            gigachat_auth_url=auth_url,
            gigachat_base_url=base_url
            if base_url
            else Config.model_fields["gigachat_base_url"].default,
            gigachat_verify_ssl=verify_ssl,
            # Параметры генерации
            gigachat_temperature=temperature,
            gigachat_top_p=top_p,
            # Уведомления в чат (необязательно)
            sberchat_webhook_token=(SecretStr(webhook_token) if webhook_token else None),
            # SberChat бот
            sberchat_bot_token=(SecretStr(bot_token) if bot_token else None),
            sberchat_root_certs=root_certs,
            sberchat_sandbox=sandbox,
            # Agent
            allowed_users=allowed_users,
            log_level=log_level,
        )
