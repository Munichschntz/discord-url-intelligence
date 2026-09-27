"""Provider contracts; concrete network adapters arrive in later milestones."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Link:
    link_id: int
    canonical_url: str
    resource_type: str | None


@dataclass(frozen=True)
class Metadata:
    provider: str
    title: str | None = None
    description: str | None = None
    data: dict[str, object] = field(default_factory=dict)
    readable_text: str = ""


class PermanentFailure(Exception):
    """The request cannot succeed on retry."""


class TransientFailure(Exception):
    """The request may succeed later."""


class Adapter(Protocol):
    def supports(self, link: Link) -> bool: ...

    async def enrich(self, link: Link) -> Metadata: ...


class Registry:
    """First matching adapter wins; register specific adapters before fallbacks."""

    def __init__(self, *adapters: Adapter) -> None:
        self.adapters = adapters

    def select(self, link: Link) -> Adapter | None:
        return next((adapter for adapter in self.adapters if adapter.supports(link)), None)
