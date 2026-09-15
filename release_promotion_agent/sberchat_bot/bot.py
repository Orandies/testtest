"""Ядро SberChat-бота на официальной SDK.

Интегрируется с ChatAgent (диалог с GigaChat) для обработки входящих
сообщений и генерации ответов.

Поддерживаемые команды:
    /start    — приветствие
    /chat     — режим диалога
    /status   — статус бота
    /help     — справка
"""

from __future__ import annotations

import logging

from release_promotion_agent.config import Config

__all__ = ["SberChatBot", "BotError"]

_log = logging.getLogger(__name__)


class BotError(Exception):
    """Ошибка бота."""


class SberChatBot:
    """SberChat-бот на основе официальной SDK (dialog_bot_sdk).

    Инкапсулирует работу с DialogBot SDK и предоставляет высокоуровневый
    API для обработки сообщений и ответов.
    """

    COMMANDS: dict[str, str] = {
        "start": "Запустить бота и получить справку",
        "chat": "Начать диалог с GigaChat (режим чтения)",
        "release": "Запустить релизный сценарий",
        "status": "Показать статус текущей сессии",
        "help": "Показать справку по командам",
    }

    def __init__(self, config: Config) -> None:
        """Инициализация бота.

        Args:
            config: Конфигурация агента.
        """
        self._config = config

    def create_dialog_bot(self):
        """Создать и настроить DialogBot SDK.

        Returns:
            Настроенный DialogBot инстанс.

        Raises:
            BotError: если не настроены токен или endpoint.
        """
        try:
            from dialog_bot_sdk.bot import DialogBot

            if not self._config.sberchat_bot_token:
                raise BotError("Не задан SBERCHAT_BOT_TOKEN: бот не может работать без токена")

            bot_config: dict[str, object] = {
                "endpoint": "epbotsift.sberchat.sberbank.ru",
                "token": self._config.sberchat_bot_token.get_secret_value(),
            }

            # CA-сертификат — SDK ожидает путь к файлу
            if self._config.sberchat_root_certs:
                bot_config["root_certificates"] = str(self._config.sberchat_root_certs)
                _log.info("CA-сертификат: %s", self._config.sberchat_root_certs)

            # Sandbox окружение
            if self._config.sberchat_sandbox:
                bot_config["endpoint"] = "epbotsandbox.sberchat.sberbank.ru"
                bot_config["is_secure"] = False

            _log.info(
                "Создаю DialogBot SDK: endpoint=%s token=%s",
                bot_config["endpoint"],
                "******",
            )

            bot = DialogBot.create_bot(bot_config)
            _log.info("DialogBot SDK создан успешно")
            return bot

        except Exception as exc:
            raise BotError(f"Не удалось создать DialogBot: {exc}") from exc

    async def run(self) -> None:
        """Запустить бота."""
        from release_promotion_agent.agents.chat_agent import ChatAgent

        try:
            bot = self.create_dialog_bot()
        except BotError as exc:
            _log.error("Ошибка создания бота: %s", exc)
            raise

        # ChatAgent для генерации ответов
        chat_agent = ChatAgent(self._config)

        # ── Обработчики ──────────────────────────────────────────────

        def _handle_start(message):
            """Команда /start."""
            peer = message.peer
            bot.messaging.send_message_sync(
                peer,
                "Привет! Я агент подготовки релизных изменений.\n\n"
                "Доступные команды:\n"
                "  /chat — диалог с GigaChat\n"
                "  /release — запустить релизный сценарий\n"
                "  /status — статус текущей сессии\n"
                "  /help — справка",
            )

        def _handle_chat(message):
            """Команда /chat — режим диалога."""
            peer = message.peer
            bot.messaging.send_message_sync(
                peer,
                "Режим диалога с GigaChat активирован.\n"
                "Введите ваш вопрос, и я отвечу на основе доступных данных.\n"
                "Можно добавить ссылку на Confluence-страницу — я её прочитаю.",
            )

        def _handle_release(message):
            """Команда /release — релизный сценарий."""
            peer = message.peer
            if not self._config.has_sourcecontrol or not self._config.has_confluence:
                bot.messaging.send_message_sync(
                    peer,
                    "Релизный сценарий недоступен: не настроены SourceControl и/или Confluence.\n"
                    "Запустите демо: release-promotion-agent demo",
                )
                return

            bot.messaging.send_message_sync(
                peer,
                "Запускаю релизный сценарий...\n"
                "Это может занять несколько минут.",
            )
            # TODO: запустить Orchestrator
            _log.warning("Orchestrator не интегрирован")

        def _handle_status(message):
            """Команда /status."""
            peer = message.peer
            lines = ["Статус бота: запущен"]
            if self._config.use_mtls:
                gg = "mTLS"
            elif self._config.use_token:
                gg = "token"
            else:
                gg = "не настроен"
            lines.append(f"GigaChat: {gg}")
            lines.append(
                f"SourceControl: {'настроен' if self._config.has_sourcecontrol else 'не настроен'}"
            )
            lines.append(
                f"Confluence: {'настроен' if self._config.has_confluence else 'не настроен'}"
            )
            bot.messaging.send_message_sync(peer, "\n".join(lines))

        def _handle_help(message):
            """Команда /help."""
            peer = message.peer
            lines = ["Доступные команды:"]
            for cmd, desc in self.COMMANDS.items():
                lines.append(f"  /{cmd} — {desc}")
            bot.messaging.send_message_sync(peer, "\n".join(lines))

        def _handle_text(message):
            """Обработка текстового сообщения — передать ChatAgent."""
            peer = message.peer
            try:
                text = message.message.text_message.text
                response = chat_agent.process(text)
                bot.messaging.send_message_sync(peer, response.text)
            except Exception as exc:
                _log.warning("Ошибка ChatAgent: %s", exc)
                bot.messaging.send_message_sync(
                    peer, "Не удалось обработать сообщение. Попробуйте позже.",
                )

        # ── Регистрация обработчиков ─────────────────────────────────
        from dialog_bot_sdk.entities.messaging import (
            CommandHandler,
            MessageContentType,
            MessageHandler,
        )

        bot.messaging.command_handler([
            CommandHandler(_handle_start, "start", description="Приветствие"),
            CommandHandler(_handle_chat, "chat", description="Режим диалога"),
            CommandHandler(_handle_release, "release", description="Релизный сценарий"),
            CommandHandler(_handle_status, "status", description="Статус бота"),
            CommandHandler(_handle_help, "help", description="Справка"),
        ])

        bot.messaging.message_handler([
            MessageHandler(_handle_text, MessageContentType.TEXT_MESSAGE),
        ])

        # ── Запуск ───────────────────────────────────────────────────
        _log.info("Запускаю цикл получения обновлений...")
        bot.updates.on_updates(do_read_message=True, do_register_commands=True)
        _log.info("SberChat-бот запущен")


def create_bot(config: Config) -> SberChatBot:
    """Фабрика для создания SberChatBot.

    Args:
        config: Конфигурация агента.

    Returns:
        Инициализированный SberChatBot.
    """
    return SberChatBot(config)
