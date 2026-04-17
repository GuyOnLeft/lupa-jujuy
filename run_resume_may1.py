#!/usr/bin/env python3
"""
Resume Street View classification from where we left off on April 16.
Run this on May 1 when Anthropic limit resets.

New 4-stage pipeline (much cheaper, much more accurate):
  Stage 0: Proximity filter — keep only SV candidates within 100m of a satellite anomaly
  Stage 1: CV pre-filter  — reject obvious negatives (vegetation, sky, blur) using PIL
  Stage 2: Haiku pass     — fast classification on remaining ~200 candidates
  Stage 3: Sonnet review  — uncertain cases (0.65–0.85 confidence) only

Usage:
  venv/bin/python3 run_resume_may1.py
"""
import json
import math
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from scanner.streetview_classify import classify_streetview_candidates
from scanner.cv_prefilter import prefilter_candidates

RESUME_FILE    = Path('data/output/resume_candidates.json')
EXISTING_FILE  = Path('data/output/sv_20260416_192626.json')
SATELLITE_FILE = Path('data/output/seed_20260416_014134.json')
OUTPUT_DIR     = Path('data/output')

# Stage 0: Only keep SV candidates within this distance of a satellite anomaly centroid
PROXIMITY_RADIUS_M = 200.0


def haversine_m(lat1, lng1, lat2, lng2) -> float:
    """Distance in metres between two lat/lng points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def stage0_proximity_filter(candidates: list[dict], satellite_sites: list[dict]) -> list[dict]:
    """
    Keep only SV candidates within PROXIMITY_RADIUS_M of any satellite anomaly centroid.
    Attaches 'nearest_satellite_m' and 'nearest_satellite_idx' to each kept candidate.
    """
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
    # Load remaining unclassified locations
    with open(RESUME_FILE) as f:
        candidates = json.load(f)
    print(f'Loaded {len(candidates)} unclassified locations from {RESUME_FILE}')

    # Load satellite anomaly centroids
    with open(SATELLITE_FILE) as f:
        satellite_sites = json.load(f)
    print(f'Loaded {len(satellite_sites)} satellite anomaly centroids')

    # Load already confirmed sites from April 16 partial run
    with open(EXISTING_FILE) as f:
        existing = json.load(f)
    print(f'Loaded {len(existing)} previously confirmed sites from April 16')

    # --- Stage 0: Proximity filter ---
    print(f'\n[Stage 0] Proximity filter: keep only SV within {PROXIMITY_RADIUS_M}m of satellite anomaly...')
    stage0_passed = stage0_proximity_filter(candidates, satellite_sites)
    stage0_rejected = len(candidates) - len(stage0_passed)
    print(f'  Kept: {len(stage0_passed)} | Rejected: {stage0_rejected}')

    # --- Stage 1: CV pre-filter ---
    print(f'\n[Stage 1] CV pre-filter: reject vegetation/sky/blur using pixel analysis...')
    stage1_passed, stage1_rejected = prefilter_candidates(stage0_passed)
    reason_counts = {}
    for c in stage1_rejected:
        r = c.get('prefilter_reason', 'unknown').split('(')[0].strip()
        reason_counts[r] = reason_counts.get(r, 0) + 1
    print(f'  Kept: {len(stage1_passed)} | Rejected: {len(stage1_rejected)}')
    print(f'  Rejection reasons: {reason_counts}')

    # --- Stage 2+3: Two-stage Claude classification ---
    print(f'\n[Stage 2+3] Running two-stage Haiku→Sonnet on {len(stage1_passed)} candidates...')
    new_confirmed = classify_streetview_candidates(stage1_passed, confidence_threshold=0.65)

    # Normalize new confirmed format to match existing
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
            'reviewed_by':         site.get('reviewed_by', 'haiku'),
            'nearest_satellite_m': site.get('nearest_satellite_m'),
        })

    # Merge and save
    all_confirmed = existing + normalized
    print(f'\nTotal: {len(existing)} (April 16) + {len(normalized)} (new) = {len(all_confirmed)} confirmed sites')

    out_path = OUTPUT_DIR / 'sv_final.json'
    out_path.write_text(json.dumps(all_confirmed, ensure_ascii=False, indent=2))
    print(f'Saved to {out_path}')

    # Pipeline summary
    print(f'\n=== Pipeline Summary ===')
    print(f'  Stage 0 (proximity): {len(candidates):,} → {len(stage0_passed):,} ({stage0_rejected:,} rejected)')
    print(f'  Stage 1 (CV filter): {len(stage0_passed):,} → {len(stage1_passed):,} ({len(stage1_rejected):,} rejected)')
    print(f'  Stage 2+3 (Claude):  {len(stage1_passed):,} → {len(new_confirmed):,} confirmed')
    print(f'\nNext steps:')
    print('  1. Run review.html to do human spot-check on sv_final.json')
    print('  2. Run: venv/bin/python3 enrich_nbi.py data/output/sv_final.json data/output/seed_20260416_014134.json')


if __name__ == '__main__':
    main()
