# satellite-scanner/tests/test_pipeline.py
import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from scanner.pipeline import build_seed_record, save_output


def test_build_seed_record_structure():
    candidate = {
        'lat': -24.185,
        'lng': -65.300,
        'area_m2': 1200,
        'tile_path': 'data/candidates/-24.185000_-65.300000.png',
    }
    classification = {
        'waste_type': 'doméstico',
        'severity': 'high',
        'confidence': 0.91,
        'estimated_area_m2': 1100,
        'description_es': 'Basural grande con residuos domésticos.',
        'false_positive_reason': None,
    }
    dating = {
        'first_detected_year': 2015,
        'yearly_presence': [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024],
        'confidence_trend': 'stable',
    }
    record = build_seed_record(candidate, classification, dating)

    assert record['latitude'] == pytest.approx(-24.185)
    assert record['longitude'] == pytest.approx(-65.300)
    assert record['first_detected_year'] == 2015
    assert record['severity'] == 'high'
    assert record['waste_type'] == 'doméstico'
    assert record['confidence'] == pytest.approx(0.91)
    assert record['source'] == 'satellite'
    assert 'satellite_tile_url' in record
    assert record['report_id'] is None


def test_save_output_creates_json_and_csv(tmp_path):
    records = [{
        'latitude': -24.185,
        'longitude': -65.300,
        'first_detected_year': 2015,
        'yearly_presence': [2015, 2016],
        'severity': 'high',
        'waste_type': 'doméstico',
        'confidence': 0.91,
        'estimated_area_m2': 1100,
        'description_es': 'Basural.',
        'satellite_tile_url': 'data/candidates/tile.png',
        'report_id': None,
        'source': 'satellite',
        'confidence_trend': 'stable',
    }]
    json_path, csv_path = save_output(records, output_dir=str(tmp_path))
    assert Path(json_path).exists()
    assert Path(csv_path).exists()
    loaded = json.loads(Path(json_path).read_text())
    assert len(loaded) == 1
    assert loaded[0]['latitude'] == pytest.approx(-24.185)
