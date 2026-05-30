import pytest
from src.scraper.fetchers.adaptive_wait import (
    AdaptiveWaitSignals, AdaptiveWaitState, evaluate_detail_readiness
)

def make_signals(**kwargs):
    defaults = {
        "ready_state": "complete",
        "current_url": "https://suchen.mobile.de/fahrzeuge/details.html?id=123",
        "title": "Car for sale",
        "body_text": "This is a normal page body with plenty of text to pass the length threshold.",
        "body_length": 1000,
        "has_target_field": False,
        "has_error_signal": False,
        "is_about_blank": False,
        "is_mobile_domain": True
    }
    defaults.update(kwargs)
    return AdaptiveWaitSignals(**defaults)

def test_about_blank_returns_wait():
    s = make_signals(is_about_blank=True, current_url="about:blank")
    d = evaluate_detail_readiness(s)
    assert d.state == AdaptiveWaitState.WAIT
    
def test_access_denied_returns_error():
    s = make_signals(title="Access Denied")
    d = evaluate_detail_readiness(s)
    assert d.state == AdaptiveWaitState.ERROR

def test_perimeterx_returns_error():
    s = make_signals(body_text="Please solve this PerimeterX challenge")
    d = evaluate_detail_readiness(s)
    assert d.state == AdaptiveWaitState.ERROR

def test_ready_detail_with_target_field_returns_ready():
    s = make_signals(has_target_field=True, body_text="Lots of text... Baureihe: X")
    d = evaluate_detail_readiness(s)
    assert d.state == AdaptiveWaitState.READY

def test_ready_detail_with_financing_returns_ready():
    s = make_signals(body_text="Lots of text... Finanzierung available")
    d = evaluate_detail_readiness(s)
    assert d.state == AdaptiveWaitState.READY

def test_small_body_returns_wait():
    s = make_signals(body_length=100)
    d = evaluate_detail_readiness(s)
    assert d.state == AdaptiveWaitState.WAIT

def test_non_mobile_url_returns_wait_or_error():
    # Design choice: WAIT if it's a redirect that hasn't landed on mobile.de yet
    s = make_signals(is_mobile_domain=False, current_url="https://google.com")
    d = evaluate_detail_readiness(s)
    assert d.state == AdaptiveWaitState.WAIT

def test_unicode_co2_signal_detected():
    s = make_signals(body_text="Lots of text... CO₂-Emissionen: 100g")
    d = evaluate_detail_readiness(s)
    assert d.state == AdaptiveWaitState.READY

def test_co2_ascii_signal_detected():
    s = make_signals(body_text="Lots of text... CO2-Emissionen: 100g")
    d = evaluate_detail_readiness(s)
    assert d.state == AdaptiveWaitState.READY

def test_missing_target_fields_returns_wait():
    s = make_signals(body_text="A completely blank page with enough length to pass but no targets" * 20)
    d = evaluate_detail_readiness(s)
    assert d.state == AdaptiveWaitState.WAIT
