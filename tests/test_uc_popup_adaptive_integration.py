import pytest
from unittest.mock import MagicMock
from src.scraper.fetchers.uc_popup_fetcher import _collect_adaptive_wait_signals


def test_collect_adaptive_wait_signals_success():
    driver = MagicMock()

    def fake_execute(script):
        if "readyState" in script:
            return "complete"
        if "innerText" in script:
            return "Body text Baureihe"
        return ""

    driver.execute_script.side_effect = fake_execute

    driver.current_url = "https://suchen.mobile.de/details"
    driver.title = "Car"
    body_mock = MagicMock()
    body_mock.text = "Body text Baureihe"
    driver.find_element.return_value = body_mock
    signals = _collect_adaptive_wait_signals(driver)
    assert signals.ready_state == "complete"
    assert signals.is_mobile_domain is True
    assert signals.body_length > 10


def test_collect_adaptive_wait_signals_exception_handled():
    driver = MagicMock()
    driver.execute_script.side_effect = Exception("Crash")
    signals = _collect_adaptive_wait_signals(driver)
    assert signals.ready_state == "complete"


class DummyConfig:
    def __init__(self, profile="adaptive"):
        self.uc_wait_profile = profile
        self.adaptive_wait_used_count = 0
        self.adaptive_wait_success_count = 0
        self.adaptive_wait_timeout_count = 0
        self.adaptive_wait_error_count = 0
        self.adaptive_wait_total_ms = 0
        self.adaptive_wait_max_ms = 0


from src.scraper.fetchers.uc_popup_fetcher import UcPopupFetcher  # noqa: E402
from src.domain.exceptions import DetailPageBlockedError  # noqa: E402
from unittest.mock import patch  # noqa: E402
from src.main import _compute_run_summary  # noqa: E402
from datetime import datetime  # noqa: E402
import pandas as pd  # noqa: E402


@patch("src.scraper.fetchers.uc_popup_fetcher._collect_adaptive_wait_signals")
@patch("src.scraper.fetchers.uc_popup_fetcher.evaluate_detail_readiness")
def test_adaptive_wait_ready_increments(mock_evaluate, mock_collect):
    config = DummyConfig("adaptive")
    fetcher = UcPopupFetcher(config)
    driver = MagicMock()
    wait_mock = MagicMock()

    from src.scraper.fetchers.adaptive_wait import (
        AdaptiveWaitDecision,
        AdaptiveWaitState,
    )

    mock_evaluate.return_value = AdaptiveWaitDecision(
        AdaptiveWaitState.READY, "Ready", 0, None
    )

    fetcher._wait_for_detail_dom(driver, wait_mock)

    assert config.adaptive_wait_used_count == 1
    assert config.adaptive_wait_success_count == 1
    assert config.adaptive_wait_total_ms == 0


@patch("src.scraper.fetchers.uc_popup_fetcher._collect_adaptive_wait_signals")
@patch("src.scraper.fetchers.uc_popup_fetcher.evaluate_detail_readiness")
def test_adaptive_wait_timeout_increments(mock_evaluate, mock_collect):
    config = DummyConfig("adaptive")
    fetcher = UcPopupFetcher(config)
    driver = MagicMock()
    wait_mock = MagicMock()

    from src.scraper.fetchers.adaptive_wait import (
        AdaptiveWaitDecision,
        AdaptiveWaitState,
    )

    mock_evaluate.return_value = AdaptiveWaitDecision(
        AdaptiveWaitState.WAIT, "Wait", 0, None
    )

    fetcher._wait_for_detail_dom(driver, wait_mock)

    assert config.adaptive_wait_used_count == 1
    assert config.adaptive_wait_timeout_count == 1
    assert config.adaptive_wait_total_ms >= 4000
    assert config.adaptive_wait_max_ms >= 4000


@patch("src.scraper.fetchers.uc_popup_fetcher._collect_adaptive_wait_signals")
@patch("src.scraper.fetchers.uc_popup_fetcher.evaluate_detail_readiness")
def test_adaptive_wait_error_increments(mock_evaluate, mock_collect):
    config = DummyConfig("adaptive")
    fetcher = UcPopupFetcher(config)
    driver = MagicMock()
    wait_mock = MagicMock()

    from src.scraper.fetchers.adaptive_wait import (
        AdaptiveWaitDecision,
        AdaptiveWaitState,
    )

    mock_evaluate.return_value = AdaptiveWaitDecision(
        AdaptiveWaitState.ERROR, "Error", 0, None
    )

    with pytest.raises(DetailPageBlockedError):
        fetcher._wait_for_detail_dom(driver, wait_mock)

    assert config.adaptive_wait_used_count == 1
    assert config.adaptive_wait_error_count == 1
    assert config.adaptive_wait_total_ms == 0


def test_safe_profile_does_not_increment_adaptive_metrics():
    config = DummyConfig("safe")
    fetcher = UcPopupFetcher(config)
    driver = MagicMock()
    wait_mock = MagicMock()

    fetcher._wait_for_detail_dom(driver, wait_mock)

    assert config.adaptive_wait_used_count == 0
    assert config.adaptive_wait_success_count == 0
    assert config.adaptive_wait_timeout_count == 0


def test_run_summary_includes_adaptive_metrics():
    config = MagicMock()
    config.adaptive_wait_used_count = 2
    config.adaptive_wait_success_count = 1
    config.adaptive_wait_timeout_count = 1
    config.adaptive_wait_error_count = 0
    config.adaptive_wait_total_ms = 4000
    config.adaptive_wait_max_ms = 4000
    config.state = "nordrhein-westfalen"
    config.pipeline_mode = "sqlite"
    config.browser_mode = "xvfb"
    config.fetch_strategy = "auto"
    config.detail_policy = "missing-required"
    config.vendor_concurrency = 1
    config.vehicle_detail_concurrency = 1

    df_vendors = pd.DataFrame([{"Händler ID": "C1", "Händlername": "Demo"}])
    df_cars = pd.DataFrame([{"Händler ID": "C1", "Vehicle_URL": "url"}])

    summary = _compute_run_summary(
        "test-id",
        datetime.now(),
        datetime.now(),
        config,
        df_vendors,
        df_cars,
        df_cars,
        [],
    )

    assert summary["adaptive_wait_used_count"] == 2
    assert summary["adaptive_wait_success_count"] == 1
    assert summary["adaptive_wait_timeout_count"] == 1
    assert summary["adaptive_wait_error_count"] == 0
    assert summary["adaptive_wait_total_ms"] == 4000
    assert summary["adaptive_wait_avg_ms"] == 2000.0
    assert summary["adaptive_wait_max_ms"] == 4000
