# satellite-scanner/tests/test_gee_scan.py
import pytest
from unittest.mock import patch, MagicMock
from scanner.gee_scan import compute_bsi_expression, parse_candidates, initialize_ee

def test_compute_bsi_expression():
    """BSI formula string is correct for Sentinel-2 bands."""
    expr = compute_bsi_expression()
    assert 'B11' in expr  # SWIR1
    assert 'B4' in expr   # Red
    assert 'B8' in expr   # NIR
    assert 'B2' in expr   # Blue

def test_parse_candidates_extracts_centroids():
    """parse_candidates pulls lat/lng from GEE FeatureCollection info."""
    mock_gee_info = {
        'type': 'FeatureCollection',
        'features': [
            {
                'type': 'Feature',
                'geometry': {'type': 'Polygon', 'coordinates': [[[-65.3, -24.2], [-65.31, -24.2], [-65.31, -24.21], [-65.3, -24.2]]]},
                'properties': {
                    'centroid_lat': -24.205,
                    'centroid_lng': -65.305,
                    'area': 1200.0
                }
            }
        ]
    }
    result = parse_candidates(mock_gee_info)
    assert len(result) == 1
    assert result[0]['lat'] == pytest.approx(-24.205)
    assert result[0]['lng'] == pytest.approx(-65.305)
    assert result[0]['area_m2'] == pytest.approx(1200.0)

def test_parse_candidates_empty():
    mock_gee_info = {'type': 'FeatureCollection', 'features': []}
    assert parse_candidates(mock_gee_info) == []

def test_parse_candidates_skips_missing_centroid():
    mock_gee_info = {
        'type': 'FeatureCollection',
        'features': [{'type': 'Feature', 'geometry': {}, 'properties': {}}]
    }
    result = parse_candidates(mock_gee_info)
    assert result == []
