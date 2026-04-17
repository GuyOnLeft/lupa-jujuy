#!/usr/bin/env python3
"""
Street View scanner entry point.
Scans roads for roadside trash using Street View images + Claude Sonnet.
"""
import argparse
import json
import csv
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from scanner.config import METRO_BBOX, GOOGLE_MAPS_API_KEY
from scanner.streetview_scan import scan_roads_for_candidates
from scanner.streetview_classify import classify_streetview_candidates


def build_sv_record(candidate):
    c = candidate['classification']
    return {
        'latitude':           candidate['lat'],
        'longitude':          candidate['lng'],
        'first_detected_year': None,
        'yearly_presence':    [],
        'confidence_trend':   'unknown',
        'severity':           c.get('severity', 'unknown'),
        'waste_type':         c.get('waste_type', 'unknown'),
        'confidence':         c.get('confidence', 0),
        'estimated_area_m2':  None,
        'description_es':     c.get('description', ''),
        'satellite_tile_url': candidate['sv_paths'][0] if candidate.get('sv_paths') else '',
        'sv_path_forward':    candidate['sv_paths'][0] if len(candidate.get('sv_paths', [])) > 0 else '',
        'sv_path_right':      candidate['sv_paths'][1] if len(candidate.get('sv_paths', [])) > 1 else '',
        'report_id':          None,
        'source':             'streetview',
    }


def save_output(records, output_dir='data/output'):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')

    json_path = Path(output_dir) / f'sv_{ts}.json'
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2))

    fieldnames = [
        'latitude', 'longitude', 'severity', 'waste_type', 'confidence',
        'description_es', 'satellite_tile_url', 'sv_path_forward',
        'sv_path_right', 'source', 'report_id',
    ]
    csv_path = Path(output_dir) / f'sv_{ts}.csv'
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(records)

    return str(json_path), str(csv_path)


def main():
    parser = argparse.ArgumentParser(description='Street View roadside trash scanner')
    parser.add_argument('--bbox', nargs=4, type=float, metavar=('W', 'S', 'E', 'N'),
                        default=METRO_BBOX, help='Bounding box to scan')
    parser.add_argument('--output', default='data/output')
    parser.add_argument('--sv-dir', default='data/sv_candidates')
    parser.add_argument('--threshold', type=float, default=0.40,
                        help='Minimum confidence to confirm a site (default 0.40)')
    args = parser.parse_args()

    bbox = args.bbox
    print(f'Street View scanner — bbox: {bbox}')
    print(f'Confidence threshold: {args.threshold}')
    print()

    candidates = scan_roads_for_candidates(bbox, output_dir=args.sv_dir)
    print()
    print(f'Classifying {len(candidates)} locations with Claude Sonnet...')
    confirmed = classify_streetview_candidates(candidates, confidence_threshold=args.threshold)
    print(f'Confirmed {len(confirmed)} waste sites')
    print()

    records = [build_sv_record(c) for c in confirmed]
    json_path, csv_path = save_output(records, args.output)
    print(f'Done. {len(records)} sites saved to:\n  {json_path}\n  {csv_path}')


if __name__ == '__main__':
    main()
