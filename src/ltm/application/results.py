"""Transport-neutral results returned by application use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class UseCaseResult(Generic[T]):
    ok: bool
    code: str
    message: str
    value: T | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def success(cls, value: T, *, code: str, message: str) -> "UseCaseResult[T]":
        return cls(ok=True, code=code, message=message, value=value)

    @classmethod
    def failure(cls, *, code: str, message: str) -> "UseCaseResult[T]":
        return cls(ok=False, code=code, message=message)

    def with_warning(self, warning: str) -> "UseCaseResult[T]":
        return UseCaseResult(
            ok=self.ok,
            code=self.code,
            message=self.message,
            value=self.value,
            warnings=(*self.warnings, warning),
        )
