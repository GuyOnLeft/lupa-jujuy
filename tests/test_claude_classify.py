# satellite-scanner/tests/test_claude_classify.py
import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from scanner.claude_classify import (
    parse_classification_response,
    is_confirmed_site,
    classify_candidates,
    CLASSIFICATION_PROMPT,
)


def test_classification_prompt_is_in_spanish():
    assert 'Jujuy' in CLASSIFICATION_PROMPT
    assert 'JSON' in CLASSIFICATION_PROMPT
    assert 'description_es' in CLASSIFICATION_PROMPT


def test_parse_classification_response_valid():
    raw = json.dumps({
        'is_waste_site': True,
        'confidence': 0.92,
        'waste_type': 'doméstico',
        'severity': 'high',
        'estimated_area_m2': 1500,
        'description_es': 'Basural a cielo abierto con residuos domésticos.',
        'false_positive_reason': None
    })
    result = parse_classification_response(raw)
    assert result['is_waste_site'] is True
    assert result['confidence'] == pytest.approx(0.92)
    assert result['waste_type'] == 'doméstico'


def test_parse_classification_response_strips_markdown():
    """Claude sometimes wraps JSON in ```json blocks."""
    raw = '```json\n{"is_waste_site": false, "confidence": 0.2, "waste_type": "false_positive", "severity": "low", "estimated_area_m2": 0, "description_es": "No es basural.", "false_positive_reason": "parking_lot"}\n```'
    result = parse_classification_response(raw)
    assert result['is_waste_site'] is False


def test_is_confirmed_site_true_above_threshold():
    classification = {'is_waste_site': True, 'confidence': 0.85}
    assert is_confirmed_site(classification, threshold=0.70) is True


def test_is_confirmed_site_false_below_threshold():
    classification = {'is_waste_site': True, 'confidence': 0.50}
    assert is_confirmed_site(classification, threshold=0.70) is False


def test_is_confirmed_site_false_not_waste():
    classification = {'is_waste_site': False, 'confidence': 0.95}
    assert is_confirmed_site(classification, threshold=0.70) is False


def test_classify_candidates_filters_by_threshold(tmp_path):
    # Create a fake tile file
    tile = tmp_path / '-24.185000_-65.300000.png'
    tile.write_bytes(b'\x89PNG fake')

    high_conf_response = json.dumps({
        'is_waste_site': True, 'confidence': 0.95,
        'waste_type': 'doméstico', 'severity': 'high',
        'estimated_area_m2': 800,
        'description_es': 'Basural grande.', 'false_positive_reason': None
    })

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=high_conf_response)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message

    candidates = [{'lat': -24.185, 'lng': -65.300, 'area_m2': 800, 'tile_path': str(tile)}]

    with patch('scanner.claude_classify.anthropic.Anthropic', return_value=mock_client):
        confirmed = classify_candidates(candidates, confidence_threshold=0.70)

    assert len(confirmed) == 1
    assert confirmed[0]['classification']['waste_type'] == 'doméstico'
