# scanner/gemini_classify.py
"""
Gemini Flash classification of Street View images — used as fallback when
Anthropic API limits are hit. Free tier: 1,500 requests/day, 15 RPM.
"""
import base64
import json
import re
import time
from pathlib import Path

import google.generativeai as genai

GEMINI_MODEL = 'gemini-2.0-flash'
REQUESTS_PER_MINUTE = 14   # stay just under 15 RPM free tier limit

CLASSIFICATION_PROMPT = """You are reviewing a street-level photo taken in San Salvador de Jujuy, Argentina.

Your job is to identify any visible roadside trash, illegal dumping, or informal waste accumulation.

Look for:
- Piles of household garbage or mixed waste on or near the road
- Construction debris dumped on public land
- Bags, mattresses, appliances, or other large items abandoned roadside
- Informal dumping areas where multiple items have accumulated
- Burned waste or ash piles on roadsides

Do NOT flag:
- Legitimate garbage bins or collection points
- Neatly bagged trash at a curb awaiting pickup
- Construction sites with proper enclosures
- Normal street clutter or parked vehicles

Respond ONLY with valid JSON in this exact format:
{
  "is_waste_site": true or false,
  "confidence": 0.0 to 1.0,
  "severity": "low" or "medium" or "high",
  "waste_type": "household" or "construction" or "mixed" or "industrial" or "none",
  "description": "One sentence in English describing what you see.",
  "visible_from_street": true or false
}"""


def _encode_image(path):
    return base64.standard_b64encode(Path(path).read_bytes()).decode('utf-8')


def _classify_single(image_paths, model):
    """Classify one location using Gemini Flash."""
    parts = []
    for path in image_paths:
        parts.append({
            'inline_data': {
                'mime_type': 'image/jpeg',
                'data': _encode_image(path),
            }
        })
    parts.append(CLASSIFICATION_PROMPT)

    response = model.generate_content(parts)
    raw = response.text.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f'Bad JSON from Gemini: {e}\nRaw: {raw}')


def classify_with_gemini(candidates, api_key, confidence_threshold=0.40, checkpoint_path=None):
    """
    Classify candidates using Gemini Flash.
    Saves checkpoint after every 50 locations so progress isn't lost.
    Rate-limited to stay within free tier (15 RPM).
    """
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL)

    # Load existing checkpoint if resuming
    done_coords = set()
    confirmed = []
    if checkpoint_path and Path(checkpoint_path).exists():
        with open(checkpoint_path) as f:
            checkpoint = json.load(f)
            confirmed = checkpoint.get('confirmed', [])
            done_coords = {(c['lat'], c['lng']) for c in checkpoint.get('processed', [])}
        print(f'  Resuming from checkpoint — {len(done_coords)} already processed, {len(confirmed)} confirmed')

    remaining = [c for c in candidates if (c['lat'], c['lng']) not in done_coords]
    print(f'  {len(remaining)} locations to classify with Gemini Flash...')

    processed = list(done_coords)
    interval = 60.0 / REQUESTS_PER_MINUTE  # seconds between requests

    for i, c in enumerate(remaining):
        t0 = time.time()
        try:
            result = _classify_single(c['sv_paths'], model)
            if result.get('is_waste_site') and result.get('confidence', 0) >= confidence_threshold:
                confirmed.append({**c, 'classification': result, 'reviewed_by': 'gemini-flash'})
        except Exception as e:
            print(f'      Warning: Gemini failed at {c["lat"]:.4f},{c["lng"]:.4f} — {e}')

        processed.append((c['lat'], c['lng']))

        # Checkpoint every 50 locations
        if checkpoint_path and (i + 1) % 50 == 0:
            with open(checkpoint_path, 'w') as f:
                json.dump({'confirmed': confirmed, 'processed': [{'lat': l, 'lng': g} for l, g in processed]}, f)

        if (i + 1) % 50 == 0:
            print(f'      Gemini: {i+1}/{len(remaining)} — {len(confirmed)} confirmed so far')

        # Rate limit
        elapsed = time.time() - t0
        if elapsed < interval:
            time.sleep(interval - elapsed)

    print(f'  Done — {len(confirmed)} confirmed sites')
    return confirmed
