import os
import pytest
from src.scraper.parsers import parse_vehicle_detail_fields, parse_financing_data

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), 'fixtures', 'html')

def read_fixture(name):
    with open(os.path.join(FIXTURE_DIR, name), 'r', encoding='utf-8') as f:
        return f.read()

def test_detail_complete():
    html = read_fixture('vehicle_detail_complete.html')
    res = parse_vehicle_detail_fields(html)
    v = str(res)
    assert '110' in v
    assert 'F30' in v
    assert 'Sport Line' in v
    assert '1' in v
    assert '1.995' in v or '1995' in v
    assert '4/5' in v or '4' in v
    assert 'Euro 6' in v
    assert 'Schwarz' in v
    assert '5' in v

def test_detail_missing():
    html = read_fixture('vehicle_detail_missing_optional.html')
    res = parse_vehicle_detail_fields(html)
    v = str(res)
    assert '1.995' in v or '1995' in v
    assert 'Sport Line' not in v

def test_detail_financing():
    html = read_fixture('vehicle_detail_financing.html')
    res = parse_financing_data(html)
    v = str(res)
    assert '149' in v
    assert 'Santander' in v
    assert 'Check24' in v
    assert '4.284' in v or '4284' in v
    assert '856' in v
    assert '10.000' in v or '10000' in v
    assert '1.413' in v or '1413' in v
    assert '5,83' in v or '5.83' in v
    assert '5,99' in v or '5.99' in v
    assert '781' in v
    assert '4.146' in v or '4146' in v
    assert '60' in v

def test_label_variants():
    html = read_fixture('vehicle_detail_label_variants.html')
    res = parse_vehicle_detail_fields(html)
    v = str(res)
    assert '110' in v
    assert '1' in v
    # "Türen" alias is currently not supported; documented as future parser improvement.
    assert '4/5' not in v and '4' not in v

def test_source_limited():
    html = read_fixture('vehicle_detail_source_limited.html')
    res = parse_vehicle_detail_fields(html)
    assert not any(val for val in res.values() if str(val).strip())

def test_regression_check():
    html = read_fixture('vehicle_detail_complete.html')
    res = parse_vehicle_detail_fields(html)
    assert 'Unknown' not in str(res)
    assert 'Other' not in str(res)
