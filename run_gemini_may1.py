#!/usr/bin/env python3
"""
Run the improved May 1 pipeline using Gemini Flash instead of Claude.
Uses stages 0 (proximity filter) and 1 (CV filter) for free,
then Gemini Flash for classification.

Usage:
  venv/bin/python3 run_gemini_may1.py
"""
import json
import math
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import os
from scanner.cv_prefilter import prefilter_candidates
from scanner.gemini_classify import classify_with_gemini

RESUME_FILE    = Path('data/output/resume_candidates.json')
EXISTING_FILE  = Path('data/output/sv_20260416_192626.json')
SATELLITE_FILE = Path('data/output/seed_20260416_014134.json')
OUTPUT_DIR     = Path('data/output')
CHECKPOINT     = Path('data/output/gemini_checkpoint.json')

PROXIMITY_RADIUS_M = 200.0
CONFIDENCE_THRESHOLD = 0.65

GEMINI_KEY = os.getenv('GEMINI_API_KEY')


def haversine_m(lat1, lng1, lat2, lng2) -> float:
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def stage0_proximity_filter(candidates, satellite_sites):
    kept = []
    for c in candidates:
        lat, lng = c['lat'], c['lng']
        min_dist = float('inf')
        min_idx = -1
        for i, sat in enumerate(satellite_sites):
            d = haversine_m(lat, lng, sat['latitude'], sat['longitude'])
            if d < min_dist:
                min_dist = d
                min_idx = i
        if min_dist <= PROXIMITY_RADIUS_M:
            c['nearest_satellite_m'] = round(min_dist, 1)
            c['nearest_satellite_idx'] = min_idx
            kept.append(c)
    return kept


def main():
    if not GEMINI_KEY:
        print('ERROR: GEMINI_API_KEY not set in .env')
        return

    with open(RESUME_FILE) as f:
        candidates = json.load(f)
    print(f'Loaded {len(candidates)} unclassified locations')

    with open(SATELLITE_FILE) as f:
        satellite_sites = json.load(f)
    print(f'Loaded {len(satellite_sites)} satellite anomaly centroids')

    with open(EXISTING_FILE) as f:
        existing = json.load(f)
    print(f'Loaded {len(existing)} previously confirmed sites')

    # Stage 0: proximity filter
    print(f'\n[Stage 0] Proximity filter ({PROXIMITY_RADIUS_M}m)...')
    stage0_passed = stage0_proximity_filter(candidates, satellite_sites)
    print(f'  Kept: {len(stage0_passed)} | Rejected: {len(candidates) - len(stage0_passed)}')

    # Stage 1: CV pre-filter
    print(f'\n[Stage 1] CV pre-filter...')
    stage1_passed, stage1_rejected = prefilter_candidates(stage0_passed)
    reason_counts = {}
    for c in stage1_rejected:
        r = c.get('prefilter_reason', 'unknown').split('(')[0].strip()
        reason_counts[r] = reason_counts.get(r, 0) + 1
    print(f'  Kept: {len(stage1_passed)} | Rejected: {len(stage1_rejected)}')
    print(f'  Rejection reasons: {reason_counts}')

    # Stage 2: Gemini Flash
    print(f'\n[Stage 2] Gemini Flash on {len(stage1_passed)} candidates...')
    print(f'  Free tier: 1,500 req/day, 15 RPM — est. {len(stage1_passed) / 14:.0f} min')
    new_confirmed = classify_with_gemini(
        stage1_passed,
        api_key=GEMINI_KEY,
        confidence_threshold=CONFIDENCE_THRESHOLD,
        checkpoint_path=str(CHECKPOINT),
    )

    # Normalize and merge
    normalized = []
    for site in new_confirmed:
        cl = site.get('classification', {})
        normalized.append({
            'latitude':            site['lat'],
            'longitude':           site['lng'],
            'confidence':          cl.get('confidence'),
            'severity':            cl.get('severity', 'low'),
            'waste_type':          cl.get('waste_type', 'mixed'),
            'description_es':      cl.get('description', ''),
            'sv_path_forward':     site['sv_paths'][0] if site.get('sv_paths') else None,
            'sv_path_right':       site['sv_paths'][1] if site.get('sv_paths') and len(site['sv_paths']) > 1 else None,
            'source':              'streetview',
            'reviewed_by':         'gemini-flash',
            'nearest_satellite_m': site.get('nearest_satellite_m'),
        })

    all_confirmed = existing + normalized
    print(f'\nTotal: {len(existing)} (existing) + {len(normalized)} (new) = {len(all_confirmed)}')

    out_path = OUTPUT_DIR / 'sv_final.json'
    out_path.write_text(json.dumps(all_confirmed, ensure_ascii=False, indent=2))
    print(f'Saved to {out_path}')

    print(f'\n=== Pipeline Summary ===')
    print(f'  Stage 0 (proximity): {len(candidates):,} → {len(stage0_passed):,}')
    print(f'  Stage 1 (CV filter): {len(stage0_passed):,} → {len(stage1_passed):,}')
    print(f'  Stage 2 (Gemini):    {len(stage1_passed):,} → {len(normalized):,} confirmed')


if __name__ == '__main__':
    main()
