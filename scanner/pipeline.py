# satellite-scanner/scanner/pipeline.py
import json
import csv
from pathlib import Path
from datetime import datetime


def build_seed_record(candidate, classification, dating):
    """Combine candidate + classification + dating into one output record."""
    return {
        'latitude':           candidate['lat'],
        'longitude':          candidate['lng'],
        'first_detected_year': dating['first_detected_year'],
        'yearly_presence':    dating['yearly_presence'],
        'confidence_trend':   dating['confidence_trend'],
        'severity':           classification['severity'],
        'waste_type':         classification['waste_type'],
        'confidence':         classification['confidence'],
        'estimated_area_m2':  classification['estimated_area_m2'],
        'description_es':     classification['description_es'],
        'satellite_tile_url': candidate.get('tile_path', ''),
        'report_id':          None,
        'source':             'satellite',
    }


def save_output(records, output_dir='data/output'):
    """Save records as seed.json and seed.csv. Returns (json_path, csv_path)."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')

    json_path = Path(output_dir) / f'seed_{ts}.json'
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2))

    csv_path = Path(output_dir) / f'seed_{ts}.csv'
    fieldnames = [
        'latitude', 'longitude', 'first_detected_year', 'confidence_trend',
        'severity', 'waste_type', 'confidence', 'estimated_area_m2',
        'description_es', 'satellite_tile_url', 'report_id', 'source',
    ]
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            row = {k: v for k, v in r.items() if k in fieldnames}
            writer.writerow(row)

    return str(json_path), str(csv_path)


def run_pipeline(bbox=None, output_dir='data/output'):
    """
    Orchestrate all pipeline stages. Returns list of seed records.
    Imports GEE modules lazily so unit tests don't require GEE auth.
    """
    from scanner.gee_scan import find_candidate_sites, parse_candidates, initialize_ee as gee_init
    from scanner.tile_export import export_candidate_tiles
    from scanner.claude_classify import classify_candidates
    from scanner.date_sites import date_site

    print('[1/4] Initializing GEE...')
    gee_init()

    print('[2/4] Running spectral scan...')
    raw = find_candidate_sites(bbox)
    candidates = parse_candidates(raw)
    print(f'      Found {len(candidates)} spectral candidates')

    print('[2b/4] Filtering by road proximity...')
    from scanner.osm_roads import build_road_buffer, filter_by_road_proximity
    road_coords = build_road_buffer(bbox or [-65.40, -24.25, -65.20, -24.10])
    candidates = filter_by_road_proximity(candidates, road_coords)
    print(f'      {len(candidates)} candidates within 300m of a road')

    print('[3/4] Exporting satellite tiles...')
    candidates_with_tiles = export_candidate_tiles(candidates)

    print('[4/4a] Classifying with Claude Vision...')
    confirmed = classify_candidates(candidates_with_tiles)
    print(f'      Confirmed {len(confirmed)} waste sites')

    print('[4/4b] Running Landsat historical dating...')
    records = []
    for site in confirmed:
        dating = date_site(site['lat'], site['lng'])
        record = build_seed_record(site, site['classification'], dating)
        records.append(record)
        print(f'      {site["lat"]:.4f},{site["lng"]:.4f} → first seen {dating["first_detected_year"]}')

    json_path, csv_path = save_output(records, output_dir)
    print(f'\nDone. {len(records)} sites saved to:\n  {json_path}\n  {csv_path}')
    return records
