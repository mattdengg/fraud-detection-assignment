import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from app.models import FlagReason, Location, TransactionIn, TransactionType

EARTH_RADIUS_KM = 6371.0

@dataclass(frozen=True)
class RuleConfig:
    large_withdrawal_threshold: Decimal = Decimal("5000")
    max_travel_speed_kmh: float = 900.0
    min_travel_distance_km: float = 50.0
    failed_login_limit: int = 3
    failed_login_window: timedelta = timedelta(minutes=15)

@dataclass(frozen=True)
class AccountHistory:
    last_location: Location | None = None
    last_timestamp: datetime | None = None
    failed_logins: tuple[datetime, ...] = ()

def haversine_km(a: Location, b: Location) -> float:
    lat1, lon1, lat2, lon2 = map(
        math.radians, (a.latitude, a.longitude, b.latitude, b.longitude)
    )
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))

def check_large_withdrawal(txn: TransactionIn, config: RuleConfig) -> FlagReason | None:
    if (
        txn.transaction_type is TransactionType.WITHDRAWAL
        and txn.amount > config.large_withdrawal_threshold
    ):
        return FlagReason.LARGE_WITHDRAWAL
    return None

def check_impossible_travel(txn: TransactionIn, history: AccountHistory, config: RuleConfig) -> FlagReason | None:
    if history.last_location is None or history.last_timestamp is None:
        return None
    distance_km = haversine_km(history.last_location, txn.location)
    if distance_km < config.min_travel_distance_km:
        return None
    hours = abs((txn.timestamp - history.last_timestamp).total_seconds()) / 3600
    if hours == 0 or distance_km / hours > config.max_travel_speed_kmh:
        return FlagReason.IMPOSSIBLE_TRAVEL
    return None

def check_failed_logins(txn: TransactionIn, history: AccountHistory, config: RuleConfig) -> FlagReason | None:
    window_start = txn.timestamp - config.failed_login_window
    recent = sum(1 for t in history.failed_logins if window_start <= t <= txn.timestamp)
    if recent >= config.failed_login_limit:
        return FlagReason.EXCESSIVE_FAILED_LOGINS
    return None

def evaluate(txn: TransactionIn, history: AccountHistory, config: RuleConfig) -> list[FlagReason]:
    results = (
        check_large_withdrawal(txn, config),
        check_impossible_travel(txn, history, config),
        check_failed_logins(txn, history, config),
    )
    return [reason for reason in results if reason is not None]