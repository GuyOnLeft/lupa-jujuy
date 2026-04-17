#!/usr/bin/env python3
"""
Resume Street View classification using Gemini Flash.
Run this after run_streetview.py hits Anthropic rate limits.

Usage:
  python run_gemini_resume.py
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from scanner.gemini_classify import classify_with_gemini
from scanner.config import STREETVIEW_API_KEY
from scanner.streetview_scan import scan_roads_for_candidates

BBOX = [-65.40, -24.25, -65.20, -24.10]
OUTPUT_DIR   = Path('data/output')
SV_CACHE_DIR = Path('data/sv_candidates')
CHECKPOINT   = Path('data/output/gemini_checkpoint.json')
GEMINI_KEY   = os.getenv('GEMINI_API_KEY')


def load_existing_sv_candidates():
    """
    Reconstruct candidate list from already-downloaded SV images.
    Avoids re-fetching from Google.
    """
    candidates = []
    forward_images = sorted(SV_CACHE_DIR.glob('sv_*_f.jpg'))
    for fwd in forward_images:
        name = fwd.stem  # sv_-24.12345_-65.12345_f
        parts = name.split('_')
        # format: sv_{lat}_{lng}_f  (lat/lng can be negative so split carefully)
        try:
            lat = float(parts[1])
            lng = float(parts[2])
        except (IndexError, ValueError):
            continue
        right = SV_CACHE_DIR / fwd.name.replace('_f.jpg', '_r.jpg')
        sv_paths = [str(fwd)]
        if right.exists():
            sv_paths.append(str(right))
        candidates.append({'lat': lat, 'lng': lng, 'sv_paths': sv_paths})
    return candidates


def load_already_confirmed():
    """Load confirmed sites from the partial Anthropic run if it saved output."""
    output_files = sorted(OUTPUT_DIR.glob('sv_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    if output_files:
        with open(output_files[0]) as f:
            sites = json.load(f)
        print(f'Loaded {len(sites)} confirmed sites from previous Anthropic run: {output_files[0].name}')
        return sites, {(s['latitude'], s['longitude']) for s in sites}
    return [], set()


def main():
    if not GEMINI_KEY:
        print('ERROR: GEMINI_API_KEY not set in .env')
        print('Get a free key at: aistudio.google.com')
        sys.exit(1)

    OUTPUT_DIR.mkdir(exist_ok=True)

    print('Loading already-downloaded SV images...')
    all_candidates = load_existing_sv_candidates()
    print(f'{len(all_candidates)} locations found on disk')

    # Skip locations already confirmed by Anthropic
    anthropic_confirmed, anthropic_coords = load_already_confirmed()
    remaining = [c for c in all_candidates
                 if (round(c['lat'], 5), round(c['lng'], 5)) not in
                 {(round(lat, 5), round(lng, 5)) for lat, lng in anthropic_coords}]
    print(f'{len(remaining)} locations not yet classified — sending to Gemini Flash')

    # Classify with Gemini
    gemini_confirmed = classify_with_gemini(
        remaining,
        api_key=GEMINI_KEY,
        confidence_threshold=0.40,
        checkpoint_path=str(CHECKPOINT),
    )

    # Merge with Anthropic results
    all_confirmed = anthropic_confirmed + gemini_confirmed
    print(f'\nTotal confirmed: {len(all_confirmed)} ({len(anthropic_confirmed)} Anthropic + {len(gemini_confirmed)} Gemini)')

    # Save merged output
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = OUTPUT_DIR / f'sv_{ts}.json'

    # Normalize format
    output = []
    for site in all_confirmed:
        cl = site.get('classification', {})
        output.append({
            'latitude':       site.get('lat', site.get('latitude')),
            'longitude':      site.get('lng', site.get('longitude')),
            'confidence':     cl.get('confidence', site.get('confidence')),
            'severity':       cl.get('severity', site.get('severity', 'low')),
            'waste_type':     cl.get('waste_type', site.get('waste_type', 'mixed')),
            'description_es': cl.get('description', site.get('description_es', '')),
            'sv_path_forward': site.get('sv_paths', [None])[0] if 'sv_paths' in site else site.get('sv_path_forward'),
            'sv_path_right':   site.get('sv_paths', [None, None])[1] if 'sv_paths' in site and len(site['sv_paths']) > 1 else site.get('sv_path_right'),
            'source':         'streetview',
            'reviewed_by':    site.get('reviewed_by', 'anthropic'),
        })

    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f'Saved to {out_path}')


if __name__ == '__main__':
    main()
