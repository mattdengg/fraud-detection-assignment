import threading
from datetime import datetime
from typing import Protocol

from app.models import Location, TransactionIn, TransactionResult
from app.rules import AccountHistory

MAX_FAILED_LOGINS_KEPT = 50

class Store(Protocol):
    def get_history(self, account_id: str) -> AccountHistory: ...
    def record_transaction(self, txn: TransactionIn, result: TransactionResult) -> None: ...
    def record_failed_login(self, account_id: str, at: datetime) -> None: ...
    def get_result(self, transaction_id: str) -> TransactionResult | None: ...

class InMemoryStore:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_seen: dict[str, tuple[Location, datetime]] = {}
        self._failed_logins: dict[str, list[datetime]] = {}
        self._results: dict[str, TransactionResult] = {}

    def get_history(self, account_id: str) -> AccountHistory:
        with self._lock:
            last = self._last_seen.get(account_id)
            return AccountHistory(
                last_location=last[0] if last else None,
                last_timestamp=last[1] if last else None,
                failed_logins=tuple(self._failed_logins.get(account_id, [])),
            )

    def record_transaction(self, txn: TransactionIn, result: TransactionResult) -> None:
        with self._lock:
            prev = self._last_seen.get(txn.account_id)
            if prev is None or txn.timestamp >= prev[1]:
                self._last_seen[txn.account_id] = (txn.location, txn.timestamp)
            self._results[result.transaction_id] = result

    def record_failed_login(self, account_id: str, at: datetime) -> None:
        with self._lock:
            attempts = self._failed_logins.get(account_id, []) + [at]
            self._failed_logins[account_id] = attempts[-MAX_FAILED_LOGINS_KEPT:]

    def get_result(self, transaction_id: str) -> TransactionResult | None:
        with self._lock:
            return self._results.get(transaction_id)
