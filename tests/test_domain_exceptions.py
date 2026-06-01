from src.domain.exceptions import MobileDeScraperError, DetailPageBlockedError


def test_exception_inheritance():
    err = DetailPageBlockedError("blocked")
    assert isinstance(err, MobileDeScraperError)
    assert str(err) == "blocked"
