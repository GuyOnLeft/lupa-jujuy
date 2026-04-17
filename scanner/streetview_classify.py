# scanner/streetview_classify.py
"""
Two-stage Claude classification of Street View images for roadside trash detection.
Stage 1: Haiku does fast first pass on all locations.
Stage 2: Sonnet re-reviews uncertain cases (confidence 0.35–0.70).
"""
import base64
import json
import re
from pathlib import Path

import anthropic

from scanner.config import ANTHROPIC_API_KEY

MODEL_FAST   = 'claude-haiku-4-5-20251001'  # Stage 1: cheap, fast
MODEL_REVIEW = 'claude-sonnet-4-6'           # Stage 2: uncertain cases only

# Confidence band that triggers Stage 2 re-review.
# Haiku must exceed UNCERTAIN_HIGH (0.85) to auto-confirm — otherwise Sonnet reviews.
UNCERTAIN_LOW  = 0.55
UNCERTAIN_HIGH = 0.85

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


def _classify_single(image_paths, client, model):
    """
    Classify one location using its Street View images.
    Returns parsed classification dict or None on failure.
    """
    content = []
    for path in image_paths:
        content.append({
            'type': 'image',
            'source': {
                'type': 'base64',
                'media_type': 'image/jpeg',
                'data': _encode_image(path),
            }
        })
    content.append({'type': 'text', 'text': CLASSIFICATION_PROMPT})

    resp = client.messages.create(
        model=model,
        max_tokens=300,
        messages=[{'role': 'user', 'content': content}],
    )
    raw = resp.content[0].text.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f'Bad JSON from Claude: {e}\nRaw: {raw}')


def classify_streetview_candidates(candidates, confidence_threshold=0.40):
    """
    Two-stage classification:
      Stage 1 — Haiku reviews all candidates (cheap).
      Stage 2 — Sonnet re-reviews uncertain cases (UNCERTAIN_LOW <= conf <= UNCERTAIN_HIGH).
    Returns list of confirmed waste site dicts (is_waste_site=True, confidence >= threshold).
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    stage1_confirmed = []
    stage1_rejected  = []
    uncertain        = []

    print(f'  [Stage 1] Haiku fast-pass on {len(candidates)} locations...')
    for i, c in enumerate(candidates):
        try:
            result = _classify_single(c['sv_paths'], client, MODEL_FAST)
            conf = result.get('confidence', 0)
            is_waste = result.get('is_waste_site', False)

            if is_waste and conf > UNCERTAIN_HIGH:
                # High confidence positive — confirmed without Stage 2
                stage1_confirmed.append({**c, 'classification': result, 'reviewed_by': 'haiku'})
            elif conf >= UNCERTAIN_LOW and conf <= UNCERTAIN_HIGH:
                # Uncertain — queue for Sonnet review
                uncertain.append({**c, 'stage1': result})
            else:
                stage1_rejected.append(c)

        except Exception as e:
            print(f'      Warning: stage1 failed at {c["lat"]:.4f},{c["lng"]:.4f} — {e}')

        if (i + 1) % 100 == 0:
            print(f'      Stage 1: {i+1}/{len(candidates)} — '
                  f'{len(stage1_confirmed)} confirmed, {len(uncertain)} uncertain')

    print(f'  [Stage 1] Done — {len(stage1_confirmed)} confirmed, '
          f'{len(uncertain)} uncertain, {len(stage1_rejected)} rejected')

    print(f'  [Stage 2] Sonnet re-reviewing {len(uncertain)} uncertain locations (both angles)...')
    stage2_confirmed = []
    for i, c in enumerate(uncertain):
        try:
            # Use ALL available images (forward + right) for richer context
            result = _classify_single(c['sv_paths'], client, MODEL_REVIEW)
            conf = result.get('confidence', 0)
            if result.get('is_waste_site') and conf >= confidence_threshold:
                stage2_confirmed.append({**c, 'classification': result, 'reviewed_by': 'sonnet'})
        except Exception as e:
            print(f'      Warning: stage2 failed at {c["lat"]:.4f},{c["lng"]:.4f} — {e}')

        if (i + 1) % 10 == 0:
            print(f'      Stage 2: {i+1}/{len(uncertain)} — {len(stage2_confirmed)} confirmed so far')

    confirmed = stage1_confirmed + stage2_confirmed
    print(f'  [Stage 2] Done — {len(stage2_confirmed)} additional confirmed')
    print(f'  Total confirmed: {len(confirmed)} sites')
    return confirmed
