# satellite-scanner/tests/test_date_sites.py
import pytest
from unittest.mock import patch, MagicMock
from scanner.date_sites import (
    get_landsat_collection_id,
    determine_confidence_trend,
    date_site,
)


def test_get_landsat_collection_id_recent():
    cid, bands = get_landsat_collection_id(2020)
    assert 'LC08' in cid or 'LC09' in cid
    assert 'swir' in bands
    assert 'red' in bands
    assert 'nir' in bands
    assert 'blue' in bands


def test_get_landsat_collection_id_mid():
    cid, bands = get_landsat_collection_id(2005)
    assert 'LE07' in cid


def test_get_landsat_collection_id_old():
    cid, bands = get_landsat_collection_id(1990)
    assert 'LT05' in cid


def test_get_landsat_collection_id_boundary_2013():
    cid, _ = get_landsat_collection_id(2013)
    assert 'LC08' in cid or 'LC09' in cid


def test_determine_confidence_trend_growing():
    # More recent years than old
    years = [2022, 2023, 2024, 2025]
    assert determine_confidence_trend(years) == 'growing'


def test_determine_confidence_trend_stable():
    years = list(range(2010, 2026))
    assert determine_confidence_trend(years) == 'stable'


def test_determine_confidence_trend_shrinking():
    years = [1995, 1996, 1997, 1998, 2024]
    assert determine_confidence_trend(years) == 'shrinking'


def test_determine_confidence_trend_empty():
    assert determine_confidence_trend([]) == 'unknown'


def test_date_site_returns_structure():
    """date_site returns required keys even when mocked."""
    with patch('scanner.date_sites._site_detected_in_year', return_value=False):
        with patch('scanner.date_sites.initialize_ee'):
            result = date_site(lat=-24.185, lng=-65.300)
    assert 'first_detected_year' in result
    assert 'yearly_presence' in result
    assert 'confidence_trend' in result


def test_date_site_finds_first_year():
    """When site is detected only in 2018 and 2019, first_detected_year=2018."""
    def mock_detected(lat, lng, year):
        return year in (2018, 2019)

    with patch('scanner.date_sites._site_detected_in_year', side_effect=mock_detected):
        with patch('scanner.date_sites.initialize_ee'):
            result = date_site(lat=-24.185, lng=-65.300)
    assert result['first_detected_year'] == 2018
    assert 2018 in result['yearly_presence']
    assert 2019 in result['yearly_presence']
