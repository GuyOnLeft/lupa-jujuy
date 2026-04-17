# satellite-scanner/scanner/claude_classify.py
import anthropic
import base64
import json
import re
from pathlib import Path
from scanner.config import CONFIDENCE_THRESHOLD, MODEL

CLASSIFICATION_PROMPT = """Analizá esta imagen satelital de un lugar en la Provincia de Jujuy, Argentina.
Determiná si la imagen muestra un basural informal o microbasural a cielo abierto.

Respondé ÚNICAMENTE con JSON válido sin ningún otro texto:
{
  "is_waste_site": true o false,
  "confidence": valor entre 0.0 y 1.0,
  "waste_type": "doméstico" o "industrial" o "construcción" o "tóxico" o "mixto" o "false_positive",
  "severity": "low" o "medium" o "high",
  "estimated_area_m2": número entero,
  "description_es": "Descripción breve en castellano argentino usando voseo",
  "false_positive_reason": "parking_lot" o "construction" o "bare_soil" o "other" o null
}"""


def _encode_image(path):
    with open(path, 'rb') as f:
        return base64.standard_b64encode(f.read()).decode('utf-8')


def parse_classification_response(raw_text):
    """Parse Claude's response, stripping markdown code fences if present."""
    text = raw_text.strip()
    # Strip ```json ... ``` or ``` ... ```
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError as e:
        raise ValueError(f'Claude returned invalid JSON: {e}\nRaw: {raw_text[:200]}')


def is_confirmed_site(classification, threshold=CONFIDENCE_THRESHOLD):
    """Return True if classification meets waste site criteria."""
    return (
        classification.get('is_waste_site') is True
        and classification.get('confidence', 0) >= threshold
    )


def _classify_tile(tile_path, client):
    """Send one tile to Claude Vision. Returns parsed classification dict."""
    image_data = _encode_image(tile_path)
    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        messages=[{
            'role': 'user',
            'content': [
                {
                    'type': 'image',
                    'source': {
                        'type': 'base64',
                        'media_type': 'image/png',
                        'data': image_data,
                    },
                },
                {'type': 'text', 'text': CLASSIFICATION_PROMPT},
            ],
        }],
    )
    return parse_classification_response(response.content[0].text)


def classify_candidates(candidates, confidence_threshold=CONFIDENCE_THRESHOLD):
    """
    Classify all candidate tiles. Returns list of confirmed site dicts.
    Each confirmed dict is the original candidate dict + 'classification' key.
    """
    client = anthropic.Anthropic()
    confirmed = []
    for c in candidates:
        classification = _classify_tile(c['tile_path'], client)
        if is_confirmed_site(classification, threshold=confidence_threshold):
            confirmed.append({**c, 'classification': classification})
    return confirmed
