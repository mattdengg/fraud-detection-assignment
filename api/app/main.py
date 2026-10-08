import logging
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status

from app.config import load_rule_config
from app.events import EventPublisher, LoggingPublisher
from app.models import (
    FlaggedTransactionEvent,
    LoginAttempt,
    Status,
    TransactionIn,
    TransactionResult,
)
from app.rules import RuleConfig, evaluate
from app.store import InMemoryStore, Store

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Fraud Detection API")

@lru_cache
def get_store() -> Store:
    return InMemoryStore()

@lru_cache
def get_publisher() -> EventPublisher:
    return LoggingPublisher()


@lru_cache
def get_config() -> RuleConfig:
    return load_rule_config()

StoreDep = Annotated[Store, Depends(get_store)]
PublisherDep = Annotated[EventPublisher, Depends(get_publisher)]
ConfigDep = Annotated[RuleConfig, Depends(get_config)]

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@app.post("/transactions", response_model=TransactionResult, status_code=status.HTTP_201_CREATED)
def create_transaction(
    txn: TransactionIn, store: StoreDep, publisher: PublisherDep, config: ConfigDep
) -> TransactionResult:
    history = store.get_history(txn.account_id)
    reasons = evaluate(txn, history, config)
    result = TransactionResult(
        transaction_id=str(uuid.uuid4()),
        status=Status.FLAGGED if reasons else Status.APPROVED,
        reasons=reasons,
    )
    store.record_transaction(txn, result)
    if reasons:
        publisher.publish_flagged(
            FlaggedTransactionEvent(
                transaction_id=result.transaction_id,
                reasons=reasons,
                evaluated_at=datetime.now(timezone.utc),
                transaction=txn,
            )
        )
    return result

@app.get("/transactions/{transaction_id}", response_model=TransactionResult)
def get_transaction(transaction_id: str, store: StoreDep) -> TransactionResult:
    result = store.get_result(transaction_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return result

@app.post("/login-attempts", status_code=status.HTTP_204_NO_CONTENT)
def record_login_attempt(attempt: LoginAttempt, store: StoreDep) -> None:
    if not attempt.success:
        store.record_failed_login(attempt.account_id, attempt.timestamp)