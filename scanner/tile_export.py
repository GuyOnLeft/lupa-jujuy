# satellite-scanner/scanner/tile_export.py
import requests
from pathlib import Path
from urllib.parse import urlencode
from scanner.config import TILE_SIZE, TILE_ZOOM, GOOGLE_MAPS_API_KEY


BASE_URL = 'https://maps.googleapis.com/maps/api/staticmap'


def build_tile_url(lat, lng, api_key):
    """Build Google Maps Static API URL for a satellite tile."""
    params = {
        'center': f'{lat},{lng}',
        'zoom': TILE_ZOOM,
        'size': f'{TILE_SIZE}x{TILE_SIZE}',
        'maptype': 'satellite',
        'format': 'png',
        'key': api_key,
    }
    return f'{BASE_URL}?{urlencode(params)}'


def fetch_tile(lat, lng, output_dir, api_key, retries=3):
    """Fetch one satellite tile and save to output_dir. Returns file path."""
    url = build_tile_url(lat, lng, api_key)
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            break
        except requests.exceptions.RequestException:
            if attempt == retries - 1:
                raise

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filename = f'{lat:.6f}_{lng:.6f}.png'
    path = Path(output_dir) / filename
    path.write_bytes(resp.content)
    return str(path)


def export_candidate_tiles(candidates, output_dir=None, api_key=None):
    """
    Fetch satellite tiles for all candidates.
    Returns list of candidate dicts enriched with 'tile_path'.
    Skips candidates that fail after retries (logs warning).
    """
    if output_dir is None:
        output_dir = 'data/candidates'
    if api_key is None:
        api_key = GOOGLE_MAPS_API_KEY

    results = []
    for i, c in enumerate(candidates):
        try:
            tile_path = fetch_tile(c['lat'], c['lng'], output_dir, api_key)
            results.append({**c, 'tile_path': tile_path})
            if (i + 1) % 10 == 0:
                print(f'      Tiles: {i+1}/{len(candidates)}')
        except Exception as e:
            print(f'      Warning: skipped tile {c["lat"]:.4f},{c["lng"]:.4f} — {e}')
    return results
