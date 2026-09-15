"""Модели проверки: кандидат на запись и результат его валидации.

Результат всегда возвращается значением: любая проблема, включая ошибку
разбора YAML, попадает в errors, а не поднимает исключение.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Env(StrEnum):
    """Стенды, для которых готовятся изменения конфигов."""

    PSI = "PSI"
    PROM = "PROM"


class CandidateFile(BaseModel):
    """Кандидат на запись: содержимое конфига, предложенное моделью.

    До подтверждения человеком это просто текст: записывает его код агента
    и только после чекпоинта.
    """

    model_config = ConfigDict(frozen=True)

    repo_key: str
    env: Env
    file_path: str
    content: str


class ValidationResult(BaseModel):
    """Итог проверки: признак успеха, ошибки и предупреждения."""

    model_config = ConfigDict(frozen=True)

    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @classmethod
    def ok(cls, warnings: tuple[str, ...] = ()) -> ValidationResult:
        return cls(valid=True, warnings=warnings)

    @classmethod
    def fail(cls, *errors: str, warnings: tuple[str, ...] = ()) -> ValidationResult:
        return cls(valid=False, errors=tuple(errors), warnings=warnings)

    def merged_with(self, other: ValidationResult) -> ValidationResult:
        return ValidationResult(
            valid=self.valid and other.valid,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
        )
