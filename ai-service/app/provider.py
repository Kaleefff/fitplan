"""RecognitionProvider: the interface every recognition backend implements (D25, D-05).

D-05 may swap the model or the provider; the endpoints only see this interface. A
provider returns a complete Prediction or raises, never a partial result.
"""

from collections.abc import Sequence
from typing import Protocol

from app.schemas import Prediction


class ProviderError(Exception):
    """The model failed or its answer was unusable (502 ai_unavailable)."""


class ProviderTimeoutError(ProviderError):
    """The model did not answer within the time budget (504 ai_unavailable)."""


class RecognitionProvider(Protocol):
    async def recognise(self, jpeg: bytes, labels: Sequence[str]) -> Prediction:
        """Ingredients in the JPEG photo; every label and alternative is one of `labels`."""
        ...
