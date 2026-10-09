import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Protocol

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app.models import FlagReason, Location, Status, TransactionIn, TransactionResult
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

PROFILE_SK = "PROFILE"
LOGIN_PREFIX = "LOGIN#"


def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _from_ms(ms: object) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)


class DynamoStore(Store):
    """DynamoDB-backed store, shared across all API tasks."""

    def __init__(
        self,
        activity_table: str,
        transactions_table: str,
        login_ttl: timedelta = timedelta(days=1),
    ) -> None:
        dynamodb = boto3.resource("dynamodb")
        self._activity = dynamodb.Table(activity_table)
        self._transactions = dynamodb.Table(transactions_table)
        self._login_ttl = login_ttl

    def get_history(self, account_id: str) -> AccountHistory:
        items: list[dict] = []
        kwargs: dict = {"KeyConditionExpression": Key("account_id").eq(account_id)}
        while True:
            resp = self._activity.query(**kwargs)
            items.extend(resp["Items"])
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

        last_location: Location | None = None
        last_timestamp: datetime | None = None
        failed: list[datetime] = []
        for item in items:
            if item["sk"] == PROFILE_SK:
                last_location = Location.model_validate_json(item["last_location"])
                last_timestamp = _from_ms(item["last_ts_ms"])
            elif item["sk"].startswith(LOGIN_PREFIX):
                failed.append(_from_ms(item["at_ms"]))

        return AccountHistory(
            last_location=last_location,
            last_timestamp=last_timestamp,
            failed_logins=tuple(sorted(failed)),
        )

    def record_transaction(self, txn: TransactionIn, result: TransactionResult) -> None:
        self._transactions.put_item(
            Item={
                "transaction_id": result.transaction_id,
                "account_id": txn.account_id,
                "status": result.status.value,
                "reasons": [r.value for r in result.reasons],
                "created_at_ms": _to_ms(datetime.now(timezone.utc)),
            }
        )

        ts_ms = _to_ms(txn.timestamp)
        try:
            # Only move "last seen" forward in time; ignore out-of-order transactions
            self._activity.put_item(
                Item={
                    "account_id": txn.account_id,
                    "sk": PROFILE_SK,
                    "last_location": txn.location.model_dump_json(),
                    "last_ts_ms": ts_ms,
                },
                ConditionExpression="attribute_not_exists(last_ts_ms) OR last_ts_ms <= :ts",
                ExpressionAttributeValues={":ts": ts_ms},
            )
        except ClientError as err:
            if err.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

    def record_failed_login(self, account_id: str, at: datetime) -> None:
        at_ms = _to_ms(at)
        self._activity.put_item(
            Item={
                "account_id": account_id,
                "sk": f"{LOGIN_PREFIX}{at_ms:013d}#{uuid.uuid4()}",
                "at_ms": at_ms,
                "expires_at": int(at.timestamp() + self._login_ttl.total_seconds()),
            }
        )

    def get_result(self, transaction_id: str) -> TransactionResult | None:
        item = self._transactions.get_item(Key={"transaction_id": transaction_id}).get("Item")
        if item is None:
            return None
        return TransactionResult(
            transaction_id=item["transaction_id"],
            status=Status(item["status"]),
            reasons=[FlagReason(r) for r in item["reasons"]],
        )