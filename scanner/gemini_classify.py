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

from google import genai
from google.genai import types

GEMINI_MODEL = 'gemini-2.5-flash'
REQUESTS_PER_MINUTE = 8    # conservative — image requests are token-heavy

CLASSIFICATION_PROMPT = """You are analyzing a street-level photo from San Salvador de Jujuy, Argentina to detect ILLEGAL DUMP SITES (microbasurales).

A microbasural is a VISIBLE PILE of mixed solid household waste: plastic bags, bottles, household items, mattresses, or similar refuse — accumulated informally on public land.

CONFIRM as waste site ONLY if you clearly see:
- A pile or accumulation of plastic bags, bottles, or household trash (NOT just a few scattered pieces of litter)
- Multiple thrown-away items covering several square meters of ground
- Clear illegal dumping of household or mixed solid waste on a roadside, vacant lot, or ravine

REJECT (mark is_waste_site: false) if you see ANY of the following — even if the scene looks "rough" or informal:
- Normal unpaved or dirt roads (very common in Jujuy — not a waste indicator)
- Overgrown vacant lots, weeds, or dry vegetation
- Under-construction buildings or construction materials (bricks, sand, scaffolding)
- Highway embankments, road cuts, or burned roadside vegetation
- Scrap metal yards, junkyards, or vehicle storage
- Roadside litter (a few pieces scattered — not a dump)
- Clean residential streets, even if unpaved or informal
- Agricultural or industrial areas without visible waste piles
- Anything where you are uncertain — err strongly toward rejection

Important context: San Salvador de Jujuy is a mid-sized Argentine city with many informal neighborhoods. Unpaved roads, exposed brick buildings, and overgrown lots are NORMAL and should NOT be flagged.

Respond ONLY with valid JSON:
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


def _classify_single(client, image_paths, max_retries=5):
    """Classify one location using Gemini Flash. Retries on quota errors."""
    img_data = _encode_image(image_paths[0])  # forward image only — halves token usage
    contents = [
        types.Part.from_bytes(data=base64.b64decode(img_data), mime_type='image/jpeg'),
        CLASSIFICATION_PROMPT,
    ]

    delay = 30
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(model=GEMINI_MODEL, contents=contents)
            raw = response.text.strip()
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
            return json.loads(raw)
        except Exception as e:
            msg = str(e)
            if '429' in msg or 'quota' in msg.lower() or 'rate' in msg.lower():
                if attempt < max_retries - 1:
                    print(f'      Rate limit — waiting {delay}s (attempt {attempt+1}/{max_retries})')
                    time.sleep(delay)
                    delay = min(delay * 2, 120)
                    continue
            raise
    raise RuntimeError('Max retries exceeded')


def classify_with_gemini(candidates, api_key, confidence_threshold=0.40, checkpoint_path=None):
    """
    Classify candidates using Gemini Flash.
    Saves checkpoint after every 50 locations so progress isn't lost.
    Rate-limited to stay within free tier (15 RPM).
    """
    client = genai.Client(api_key=api_key)

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
            result = _classify_single(client, c['sv_paths'])
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
