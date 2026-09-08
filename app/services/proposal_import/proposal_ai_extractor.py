from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class ProposalAIExtractor(ABC):
    @abstractmethod
    def extract(self, sanitized_text: str) -> dict[str, Any]:
        raise NotImplementedError


@dataclass
class FakeProposalAIExtractor(ProposalAIExtractor):
    response: dict[str, Any] = field(default_factory=dict)

    def extract(self, sanitized_text: str) -> dict[str, Any]:
        return dict(self.response)
