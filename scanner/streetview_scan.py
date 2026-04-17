# scanner/streetview_scan.py
"""
Street View-based scanner.
Samples points along OSM roads, checks Street View availability,
fetches images for confirmed locations, returns candidates for classification.
"""
import math
import requests
from pathlib import Path
from urllib.parse import urlencode

from scanner.config import STREETVIEW_API_KEY
from scanner.osm_roads import fetch_road_segments

METADATA_URL = 'https://maps.googleapis.com/maps/api/streetview/metadata'
IMAGE_URL    = 'https://maps.googleapis.com/maps/api/streetview'
SAMPLE_INTERVAL_M = 150   # meters between sample points along roads
SV_RADIUS_M       = 50    # meters — how far off-road to look for SV imagery
IMAGE_SIZE        = '640x480'


def _bearing(lon1, lat1, lon2, lat2):
    """Calculate compass bearing from point 1 to point 2 (degrees, 0=N)."""
    dlng = math.radians(lon2 - lon1)
    lat1r = math.radians(lat1)
    lat2r = math.radians(lat2)
    x = math.sin(dlng) * math.cos(lat2r)
    y = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlng)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _dist_m(lon1, lat1, lon2, lat2):
    """Approximate distance in meters between two lat/lon points."""
    avg_lat = math.radians((lat1 + lat2) / 2)
    dlat = (lat2 - lat1) * 111_000
    dlng = (lon2 - lon1) * 111_000 * math.cos(avg_lat)
    return math.sqrt(dlat ** 2 + dlng ** 2)


def sample_points_along_roads(segments, interval_m=SAMPLE_INTERVAL_M):
    """
    Sample evenly-spaced points along road segments.
    Returns list of dicts: {lat, lng, heading}
    heading = direction of travel along the road at that point.
    """
    points = []
    seen = set()  # deduplicate nearby points

    for seg in segments:
        accumulated = 0.0
        for i in range(len(seg) - 1):
            lon1, lat1 = seg[i]
            lon2, lat2 = seg[i + 1]
            seg_len = _dist_m(lon1, lat1, lon2, lat2)
            if seg_len == 0:
                continue
            heading = _bearing(lon1, lat1, lon2, lat2)

            while accumulated <= seg_len:
                t = accumulated / seg_len
                lat = lat1 + t * (lat2 - lat1)
                lng = lon1 + t * (lon2 - lon1)

                # Deduplicate: round to ~10m grid
                key = (round(lat, 4), round(lng, 4))
                if key not in seen:
                    seen.add(key)
                    points.append({'lat': lat, 'lng': lng, 'heading': heading})

                accumulated += interval_m

            accumulated -= seg_len

    return points


def check_streetview_available(lat, lng, api_key, radius=SV_RADIUS_M):
    """
    Free metadata check — returns (available: bool, pano_lat, pano_lng).
    Does NOT count toward billing.
    """
    params = {
        'location': f'{lat},{lng}',
        'radius': radius,
        'key': api_key,
    }
    resp = requests.get(METADATA_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get('status') == 'OK':
        loc = data.get('location', {})
        return True, loc.get('lat', lat), loc.get('lng', lng)
    return False, lat, lng


def fetch_streetview_image(lat, lng, heading, output_dir, api_key, retries=3):
    """
    Fetch one Street View image. Returns local file path.
    Fetches two headings (road direction + 90° right) and saves as separate files.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    paths = []

    for offset, label in [(0, 'f'), (90, 'r')]:
        h = (heading + offset) % 360
        params = {
            'size': IMAGE_SIZE,
            'location': f'{lat},{lng}',
            'heading': int(h),
            'fov': 90,
            'pitch': 5,
            'key': api_key,
        }
        url = f'{IMAGE_URL}?{urlencode(params)}'
        filename = f'sv_{lat:.5f}_{lng:.5f}_{label}.jpg'
        path = Path(output_dir) / filename

        for attempt in range(retries):
            try:
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                path.write_bytes(resp.content)
                break
            except requests.exceptions.RequestException:
                if attempt == retries - 1:
                    raise

        paths.append(str(path))

    return paths  # [forward_path, right_side_path]


def scan_roads_for_candidates(bbox, output_dir='data/sv_candidates', api_key=None):
    """
    Full street view scan pipeline.
    1. Fetch road segments from OSM
    2. Sample points every SAMPLE_INTERVAL_M meters
    3. Check Street View availability (free)
    4. Fetch images for available points
    Returns list of candidate dicts with 'sv_paths' key.
    """
    if api_key is None:
        api_key = STREETVIEW_API_KEY

    print('  [SV 1/4] Fetching road network from OpenStreetMap...')
    segments = fetch_road_segments(bbox)
    print(f'           {len(segments)} road segments loaded')

    print('  [SV 2/4] Sampling points along roads...')
    points = sample_points_along_roads(segments)
    print(f'           {len(points)} sample points at {SAMPLE_INTERVAL_M}m intervals')

    print('  [SV 3/4] Checking Street View availability (free metadata API)...')
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _check(pt):
        ok, plat, plng = check_streetview_available(pt['lat'], pt['lng'], api_key)
        return ({**pt, 'lat': plat, 'lng': plng} if ok else None)

    available = []
    completed = 0
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(_check, pt): pt for pt in points}
        for future in as_completed(futures):
            result = future.result()
            if result:
                available.append(result)
            completed += 1
            if completed % 500 == 0:
                print(f'           Checked {completed}/{len(points)} — {len(available)} with coverage so far')
    print(f'           {len(available)} points have Street View coverage')

    print('  [SV 4/4] Fetching Street View images...')
    candidates = []
    for i, pt in enumerate(available):
        try:
            paths = fetch_streetview_image(pt['lat'], pt['lng'], pt['heading'], output_dir, api_key)
            candidates.append({**pt, 'sv_paths': paths})
        except Exception as e:
            print(f'           Warning: skipped {pt["lat"]:.4f},{pt["lng"]:.4f} — {e}')
        if (i + 1) % 50 == 0:
            print(f'           Fetched {i+1}/{len(available)} images')

    print(f'           Done — {len(candidates)} locations with images')
    return candidates
