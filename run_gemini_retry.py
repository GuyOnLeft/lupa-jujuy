#!/usr/bin/env python3
"""
Retry the 86 candidates that got 503'd in the first Gemini run,
then cross-reference all results against reviewed_sites.json to
flag dual_confirmed sites (appear in both SV scan and existing confirmed).
"""
import json
import math
import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from scanner.gemini_classify import classify_with_gemini
from scanner.cv_prefilter import prefilter_candidates

RESUME_FILE    = Path('data/output/resume_candidates.json')
SATELLITE_FILE = Path('data/output/seed_20260416_014134.json')
FINAL_FILE     = Path('data/output/sv_final.json')
REVIEWED_FILE  = Path('data/output/reviewed_sites.json')
OUTPUT_DIR     = Path('data/output')
CONFIDENCE_THRESHOLD = 0.65
DUAL_CONFIRM_RADIUS_M = 200.0
GEMINI_KEY = os.getenv('GEMINI_API_KEY')


def haversine_m(lat1, lng1, lat2, lng2):
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlam = math.radians(lat2-lat1), math.radians(lng2-lng1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def proximity_filter(candidates, satellite_sites, radius_m=200.0):
    kept = []
    for c in candidates:
        for sat in satellite_sites:
            if haversine_m(c['lat'], c['lng'], sat['latitude'], sat['longitude']) <= radius_m:
                kept.append(c)
                break
    return kept


def main():
    # Load the 503-skipped coords from the log
    skipped_coords = set()
    log = Path('/tmp/gemini_pipeline.log')
    if log.exists():
        import re
        for line in log.read_text().splitlines():
            if '503' in line:
                m = re.search(r'at (-[\d.]+),(-[\d.]+)', line)
                if m:
                    skipped_coords.add((float(m.group(1)), float(m.group(2))))
    print(f'Found {len(skipped_coords)} 503-skipped coordinates to retry')

    # Rebuild candidate list for just the skipped ones
    with open(RESUME_FILE) as f:
        all_candidates = json.load(f)
    with open(SATELLITE_FILE) as f:
        satellite_sites = json.load(f)

    # Re-apply proximity + CV filter, keep only skipped coords
    stage0 = proximity_filter(all_candidates, satellite_sites)
    stage1_passed, _ = prefilter_candidates(stage0)
    retry_candidates = [
        c for c in stage1_passed
        if (round(c['lat'], 4), round(c['lng'], 4)) in
           {(round(lat, 4), round(lng, 4)) for lat, lng in skipped_coords}
    ]
    print(f'Retry candidates after filter: {len(retry_candidates)}')

    if retry_candidates:
        new_confirmed = classify_with_gemini(
            retry_candidates,
            api_key=GEMINI_KEY,
            confidence_threshold=CONFIDENCE_THRESHOLD,
        )
        print(f'Retry found: {len(new_confirmed)} additional confirmed sites')
    else:
        new_confirmed = []

    # Load current sv_final.json and merge
    with open(FINAL_FILE) as f:
        current = json.load(f)

    for site in new_confirmed:
        cl = site.get('classification', {})
        current.append({
            'latitude':        site['lat'],
            'longitude':       site['lng'],
            'confidence':      cl.get('confidence'),
            'severity':        cl.get('severity', 'low'),
            'waste_type':      cl.get('waste_type', 'mixed'),
            'description_es':  cl.get('description', ''),
            'sv_path_forward': site['sv_paths'][0] if site.get('sv_paths') else None,
            'sv_path_right':   site['sv_paths'][1] if site.get('sv_paths') and len(site['sv_paths']) > 1 else None,
            'source':          'streetview',
            'reviewed_by':     'gemini-flash',
        })

    # ── Cross-reference: flag dual_confirmed ─────────────────────────────
    print('\nCross-referencing against reviewed_sites.json...')
    with open(REVIEWED_FILE) as f:
        reviewed = json.load(f)

    confirmed_reviewed = [
        s for s in reviewed
        if s.get('human_verdict') in ('confirmed', 'borderline')
    ]
    print(f'  {len(confirmed_reviewed)} human-confirmed/borderline sites as reference')

    dual_count = 0
    for site in current:
        lat = site.get('latitude') or site.get('lat')
        lng = site.get('longitude') or site.get('lng')
        if not lat or not lng:
            continue
        for ref in confirmed_reviewed:
            d = haversine_m(lat, lng, ref['latitude'], ref['longitude'])
            if d <= DUAL_CONFIRM_RADIUS_M:
                site['dual_confirmed'] = True
                site['dual_confirmed_m'] = round(d, 1)
                dual_count += 1
                break

    print(f'  {dual_count} sites flagged as dual_confirmed (within {DUAL_CONFIRM_RADIUS_M}m of human-confirmed site)')

    # Save
    FINAL_FILE.write_text(json.dumps(current, ensure_ascii=False, indent=2))
    print(f'\nSaved {len(current)} total sites to {FINAL_FILE}')
    print(f'  {len(current) - 647} new Gemini confirmations')
    print(f'  {dual_count} dual confirmed')


if __name__ == '__main__':
    main()
