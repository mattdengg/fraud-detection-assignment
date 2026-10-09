import logging
from typing import Protocol
import boto3

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

class SqsPublisher(EventPublisher):
    def __init__(self, queue_url: str) -> None:
        self._sqs = boto3.client("sqs")
        self._queue_url = queue_url

    def publish_flagged(self, event: FlaggedTransactionEvent) -> None:
        self._sqs.send_message(QueueUrl=self._queue_url, MessageBody=event.model_dump_json())
        logger.info("Published flagged transaction %s", event.transaction_id)