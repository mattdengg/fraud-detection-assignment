import logging
from typing import Protocol

from app.models import FlaggedTransactionEvent

logger = logging.getLogger(__name__)

class EventPublisher(Protocol):
    def publish_flagged(self, event: FlaggedTransactionEvent) -> None: ...

class LoggingPublisher:
    def __init__(self) -> None:
        self.published: list[FlaggedTransactionEvent] = []

    def publish_flagged(self, event: FlaggedTransactionEvent) -> None:
        self.published.append(event)
        logger.warning("Flagged %s", event.model_dump_json())