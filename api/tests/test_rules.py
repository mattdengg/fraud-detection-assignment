from datetime import datetime, timedelta, timezone
from decimal import Decimal
from app.models import FlagReason, Location, TransactionIn, TransactionType
from app.rules import AccountHistory, RuleConfig, evaluate

CONFIG = RuleConfig()
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)

TORONTO = Location(city="Toronto", country="CA", latitude=43.6532, longitude=-79.3832)
MONTREAL = Location(city="Montreal", country="CA", latitude=45.5019, longitude=-73.5674)
LONDON = Location(city="London", country="GB", latitude=51.5072, longitude=-0.1276)

def make_txn(
    amount: str = "100",
    txn_type: TransactionType = TransactionType.WITHDRAWAL,
    location: Location = TORONTO,
    timestamp: datetime = NOW,
) -> TransactionIn:
    return TransactionIn(
        account_id="acc-1",
        amount=Decimal(amount),
        transaction_type=txn_type,
        location=location,
        timestamp=timestamp,
    )

# --- Large withdrawal ---

def test_normal_withdrawal_is_approved():
    assert evaluate(make_txn("100"), AccountHistory(), CONFIG) == []


def test_withdrawal_at_threshold_is_approved():
    assert evaluate(make_txn("5000"), AccountHistory(), CONFIG) == []


def test_withdrawal_over_threshold_is_flagged():
    assert evaluate(make_txn("5000.01"), AccountHistory(), CONFIG) == [FlagReason.LARGE_WITHDRAWAL]


def test_large_deposit_is_not_flagged():
    txn = make_txn("50000", txn_type=TransactionType.DEPOSIT)
    assert evaluate(txn, AccountHistory(), CONFIG) == []

# --- Impossible travel ---

def test_no_history_is_approved():
    assert evaluate(make_txn(location=LONDON), AccountHistory(), CONFIG) == []


def test_same_city_is_approved():
    history = AccountHistory(last_location=TORONTO, last_timestamp=NOW - timedelta(minutes=1))
    assert evaluate(make_txn(location=TORONTO), history, CONFIG) == []


def test_plausible_travel_is_approved():
    # Toronto -> Montreal is ~500 km; 2 hours is ~250 km/h
    history = AccountHistory(last_location=TORONTO, last_timestamp=NOW - timedelta(hours=2))
    assert evaluate(make_txn(location=MONTREAL), history, CONFIG) == []


def test_impossible_travel_is_flagged():
    history = AccountHistory(last_location=TORONTO, last_timestamp=NOW - timedelta(minutes=10))
    assert evaluate(make_txn(location=LONDON), history, CONFIG) == [FlagReason.IMPOSSIBLE_TRAVEL]

# --- Failed logins ---

def test_two_recent_failed_logins_is_approved():
    history = AccountHistory(failed_logins=(NOW - timedelta(minutes=2), NOW - timedelta(minutes=1)))
    assert evaluate(make_txn(), history, CONFIG) == []


def test_three_recent_failed_logins_is_flagged():
    history = AccountHistory(failed_logins=tuple(NOW - timedelta(minutes=m) for m in (1, 2, 3)))
    assert evaluate(make_txn(), history, CONFIG) == [FlagReason.EXCESSIVE_FAILED_LOGINS]


def test_old_failed_logins_are_ignored():
    history = AccountHistory(failed_logins=tuple(NOW - timedelta(minutes=m) for m in (20, 25, 30)))
    assert evaluate(make_txn(), history, CONFIG) == []

# --- Combined ---

def test_multiple_rules_report_all_reasons():
    history = AccountHistory(
        last_location=TORONTO,
        last_timestamp=NOW - timedelta(minutes=10),
        failed_logins=tuple(NOW - timedelta(minutes=m) for m in (1, 2, 3)),
    )
    reasons = evaluate(make_txn("9000", location=LONDON), history, CONFIG)
    assert set(reasons) == {
        FlagReason.LARGE_WITHDRAWAL,
        FlagReason.IMPOSSIBLE_TRAVEL,
        FlagReason.EXCESSIVE_FAILED_LOGINS,
    }