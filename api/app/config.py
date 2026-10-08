import os
from datetime import timedelta
from decimal import Decimal
from app.rules import RuleConfig

def _env(name: str, default: object) -> str:
    return os.getenv(name, str(default))

def load_rule_config() -> RuleConfig:
    d = RuleConfig()
    return RuleConfig(
        large_withdrawal_threshold=Decimal(_env("LARGE_WITHDRAWAL_THRESHOLD", d.large_withdrawal_threshold)),
        max_travel_speed_kmh=float(_env("MAX_TRAVEL_SPEED_KMH", d.max_travel_speed_kmh)),
        min_travel_distance_km=float(_env("MIN_TRAVEL_DISTANCE_KM", d.min_travel_distance_km)),
        failed_login_limit=int(_env("FAILED_LOGIN_LIMIT", d.failed_login_limit)),
        failed_login_window=timedelta(
            minutes=int(_env("FAILED_LOGIN_WINDOW_MINUTES", int(d.failed_login_window.total_seconds() // 60)))
        ),
    )