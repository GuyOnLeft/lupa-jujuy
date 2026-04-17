# scanner/osm_roads.py
"""
Fetch road centerlines from OpenStreetMap via Overpass API.
"""
import requests

OVERPASS_URLS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
    'https://overpass.openstreetmap.ru/api/interpreter',
]

# Road types we care about — excludes footpaths, tracks, etc.
HIGHWAY_FILTER = (
    'primary|secondary|tertiary|residential|unclassified|'
    'trunk|motorway|living_street|service|primary_link|'
    'secondary_link|tertiary_link|trunk_link|motorway_link'
)

ROAD_BUFFER_M = 300  # meters — candidates must be within this distance of a road


def _overpass_query(query, timeout=60):
    """Try each Overpass mirror in order until one succeeds."""
    last_err = None
    for url in OVERPASS_URLS:
        try:
            resp = requests.post(url, data={'data': query}, timeout=timeout + 10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f'All Overpass mirrors failed. Last error: {last_err}')


def fetch_road_segments(bbox, timeout=60):
    """
    Fetch road ways as ordered lists of (lon, lat) node coordinates.
    Returns list of segments, where each segment is a list of (lon, lat) tuples.
    """
    west, south, east, north = bbox
    query = f"""
[out:json][timeout:{timeout}];
(
  way["highway"~"^({HIGHWAY_FILTER})$"]
  ({south},{west},{north},{east});
);
out geom;
"""
    data = _overpass_query(query, timeout)
    segments = []
    for element in data.get('elements', []):
        if element.get('type') != 'way':
            continue
        coords = [(n['lon'], n['lat']) for n in element.get('geometry', [])]
        if len(coords) >= 2:
            segments.append(coords)
    return segments


def fetch_road_coords(bbox, timeout=60):
    """
    Fetch road node coordinates as a flat list of (lon, lat) tuples.
    Used for proximity filtering of satellite candidates.
    """
    west, south, east, north = bbox
    query = f"""
[out:json][timeout:{timeout}];
(
  way["highway"~"^({HIGHWAY_FILTER})$"]
  ({south},{west},{north},{east});
);
out geom;
"""
    data = _overpass_query(query, timeout)
    coords = []
    for element in data.get('elements', []):
        if element.get('type') != 'way':
            continue
        for n in element.get('geometry', []):
            coords.append((n['lon'], n['lat']))
    return coords


def filter_by_road_proximity(candidates, road_coords, buffer_m=ROAD_BUFFER_M):
    """
    Filter candidates to those within buffer_m meters of any road node.
    candidates: list of dicts with 'lat' and 'lng' keys.
    road_coords: list of (lon, lat) tuples from fetch_road_coords().
    """
    if not road_coords:
        return candidates

    import math
    lat_deg = buffer_m / 111_000
    avg_lat = sum(c[1] for c in road_coords) / len(road_coords)
    lon_deg = buffer_m / (111_000 * math.cos(math.radians(avg_lat)))

    kept = []
    for c in candidates:
        clat, clng = c['lat'], c['lng']
        near = False
        for (rlng, rlat) in road_coords:
            if abs(rlat - clat) > lat_deg or abs(rlng - clng) > lon_deg:
                continue
            dlat = (clat - rlat) * 111_000
            dlng = (clng - rlng) * 111_000 * math.cos(math.radians(clat))
            if math.sqrt(dlat ** 2 + dlng ** 2) <= buffer_m:
                near = True
                break
        if near:
            kept.append(c)
    return kept


def build_road_buffer(bbox):
    """Fetch road node coords for the bbox. Returns coord list."""
    print('      Fetching road network from OpenStreetMap...')
    coords = fetch_road_coords(bbox)
    print(f'      Found {len(coords)} road nodes')
    return coords
