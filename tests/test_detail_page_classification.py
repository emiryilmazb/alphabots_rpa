from src.scraper.detail_page import classify_detail_page


def test_classifies_real_mobile_detail_page():
    html = """
    <html><head><title>Volkswagen Golf für 12.000 €</title></head>
    <body><h1>Volkswagen Golf</h1><div data-testid="price-label">12.000 €</div>
    <h3>Technische Daten</h3><dl><dt>Kilometerstand</dt><dd>50.000 km</dd></dl></body></html>
    """

    result = classify_detail_page(
        html,
        "https://suchen.mobile.de/fahrzeuge/details.html?id=455165432",
        "Volkswagen Golf für 12.000 €",
    )

    assert result.classification == "real_detail_page"


def test_classifies_access_denied_as_error_page():
    result = classify_detail_page(
        "<html><body>Access denied - errors.edgesuite.net</body></html>",
        "https://suchen.mobile.de/fahrzeuge/details.html?id=455165432",
        "Access denied",
    )

    assert result.classification == "error_page"


def test_classifies_mobile_home_redirect():
    result = classify_detail_page(
        "<html><head><title>mobile.de - Gebrauchtwagen und Neuwagen</title></head><body></body></html>",
        "https://home.mobile.de/",
        "mobile.de - Gebrauchtwagen und Neuwagen",
    )

    assert result.classification == "home_redirect"
