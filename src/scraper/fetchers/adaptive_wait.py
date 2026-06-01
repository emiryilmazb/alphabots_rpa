from dataclasses import dataclass
from enum import Enum, auto


class AdaptiveWaitState(Enum):
    WAIT = auto()
    READY = auto()
    ERROR = auto()
    TIMEOUT = auto()


@dataclass
class AdaptiveWaitSignals:
    ready_state: str
    current_url: str
    title: str
    body_text: str
    body_length: int
    has_target_field: bool
    has_error_signal: bool
    is_about_blank: bool
    is_mobile_domain: bool


@dataclass
class AdaptiveWaitDecision:
    state: AdaptiveWaitState
    reason: str
    elapsed_ms: int
    signals: AdaptiveWaitSignals


@dataclass
class AdaptiveWaitMetricsSnapshot:
    used_count: int = 0
    success_count: int = 0
    timeout_count: int = 0
    error_count: int = 0
    avg_ms: float = 0.0
    max_ms: int = 0


def evaluate_detail_readiness(
    signals: AdaptiveWaitSignals, elapsed_ms: int = 0
) -> AdaptiveWaitDecision:
    lower_title = signals.title.lower()
    lower_body = signals.body_text.lower()

    if (
        signals.has_error_signal
        or "access denied" in lower_title
        or "access denied" in lower_body
        or "edgesuite" in lower_title
        or "edgesuite" in lower_body
        or "perimeterx" in lower_title
        or "perimeterx" in lower_body
    ):
        return AdaptiveWaitDecision(
            AdaptiveWaitState.ERROR, "Blocked by bot protection", elapsed_ms, signals
        )

    if signals.is_about_blank or "about:blank" in signals.current_url:
        return AdaptiveWaitDecision(
            AdaptiveWaitState.WAIT, "URL is about:blank", elapsed_ms, signals
        )

    if not signals.is_mobile_domain:
        return AdaptiveWaitDecision(
            AdaptiveWaitState.WAIT, "Not on mobile.de domain yet", elapsed_ms, signals
        )

    if signals.ready_state not in ("interactive", "complete"):
        return AdaptiveWaitDecision(
            AdaptiveWaitState.WAIT,
            f"Ready state is {signals.ready_state}",
            elapsed_ms,
            signals,
        )

    if signals.body_length < 500:
        return AdaptiveWaitDecision(
            AdaptiveWaitState.WAIT, "Body length too small", elapsed_ms, signals
        )

    target_keywords = [
        "baureihe",
        "ausstattungslinie",
        "co₂",
        "co2",
        "fahrzeughalter",
        "finanzierung",
        "preis",
        "kilometerstand",
        "erstzulassung",
    ]
    has_kw = signals.has_target_field or any(kw in lower_body for kw in target_keywords)

    if has_kw:
        return AdaptiveWaitDecision(
            AdaptiveWaitState.READY, "Target field found", elapsed_ms, signals
        )

    return AdaptiveWaitDecision(
        AdaptiveWaitState.WAIT, "No target fields found yet", elapsed_ms, signals
    )
