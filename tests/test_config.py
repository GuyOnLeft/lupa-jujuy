# satellite-scanner/tests/test_config.py
from scanner.config import (
    METRO_BBOX, BSI_THRESHOLD, NDVI_THRESHOLD,
    MIN_AREA_M2, TILE_SIZE, TILE_ZOOM,
    CONFIDENCE_THRESHOLD, MODEL
)

def test_metro_bbox_covers_san_salvador():
    # bbox is [west, south, east, north]
    west, south, east, north = METRO_BBOX
    # San Salvador de Jujuy city center: -24.185, -65.300
    assert west < -65.300 < east
    assert south < -24.185 < north

def test_thresholds_in_range():
    assert 0 < BSI_THRESHOLD < 1
    assert 0 < NDVI_THRESHOLD < 1
    assert CONFIDENCE_THRESHOLD >= 0.5

def test_tile_config():
    assert TILE_SIZE == 400
    assert TILE_ZOOM == 18

def test_model_is_claude():
    assert 'claude' in MODEL
