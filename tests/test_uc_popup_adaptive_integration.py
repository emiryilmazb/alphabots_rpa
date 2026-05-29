import pytest
from unittest.mock import MagicMock
from src.scraper.fetchers.uc_popup_fetcher import _collect_adaptive_wait_signals
def test_collect_adaptive_wait_signals_success():
    driver = MagicMock()
    driver.execute_script.return_value = "complete"
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
