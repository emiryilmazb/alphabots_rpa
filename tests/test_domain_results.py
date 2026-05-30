from src.domain.results import DetailFetchStatus, DetailFetchResult, CoverageFieldResult
import dataclasses

def test_default_values():
    status = DetailFetchStatus()
    assert status.success is False

def test_serialization():
    res = DetailFetchResult(status=DetailFetchStatus(success=True))
    assert dataclasses.asdict(res)["status"]["success"] is True

def test_coverage_result():
    cov = CoverageFieldResult(field_name="CO2", coverage_percentage=100.0)
    assert cov.field_name == "CO2"
