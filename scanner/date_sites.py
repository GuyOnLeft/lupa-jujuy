# satellite-scanner/scanner/date_sites.py
import ee
from scanner.config import BSI_THRESHOLD, NDVI_THRESHOLD, EE_PROJECT


def initialize_ee():
    ee.Initialize(project=EE_PROJECT)


def get_landsat_collection_id(year):
    """
    Return (collection_id, band_names_dict) for the appropriate Landsat mission.
    band_names_dict keys: swir, red, nir, blue
    """
    if year >= 2013:
        return ('LANDSAT/LC08/C02/T1_L2', {
            'swir': 'SR_B6', 'red': 'SR_B4', 'nir': 'SR_B5', 'blue': 'SR_B2'
        })
    elif year >= 2003:
        return ('LANDSAT/LE07/C02/T1_L2', {
            'swir': 'SR_B5', 'red': 'SR_B3', 'nir': 'SR_B4', 'blue': 'SR_B1'
        })
    else:
        return ('LANDSAT/LT05/C02/T1_L2', {
            'swir': 'SR_B5', 'red': 'SR_B3', 'nir': 'SR_B4', 'blue': 'SR_B1'
        })


def _site_detected_in_year(lat, lng, year):
    """
    Query GEE to check if a waste site anomaly is detectable at (lat, lng) in (year).
    Returns True if BSI > threshold AND NDVI < threshold in the annual composite.
    """
    collection_id, bands = get_landsat_collection_id(year)
    point = ee.Geometry.Point([lng, lat])
    buffer = point.buffer(100)

    composite = (
        ee.ImageCollection(collection_id)
        .filterDate(f'{year}-01-01', f'{year}-12-31')
        .filterBounds(buffer)
        .filter(ee.Filter.lt('CLOUD_COVER', 30))
        .median()
        .multiply(0.0000275)
        .add(-0.2)
    )

    swir1 = composite.select(bands['swir'])
    red   = composite.select(bands['red'])
    nir   = composite.select(bands['nir'])
    blue  = composite.select(bands['blue'])

    bsi = (swir1.add(red).subtract(nir.add(blue))).divide(
           swir1.add(red).add(nir.add(blue)))
    ndvi = composite.normalizedDifference([bands['nir'], bands['red']])

    sample = (
        bsi.rename('BSI').addBands(ndvi.rename('NDVI'))
        .sample(region=buffer, scale=30, numPixels=10)
        .first()
    )

    try:
        values = sample.getInfo()
        if values is None:
            return False
        bsi_val  = values['properties'].get('BSI', 0)
        ndvi_val = values['properties'].get('NDVI', 1)
        return bsi_val > BSI_THRESHOLD and ndvi_val < NDVI_THRESHOLD
    except Exception:
        return False


def determine_confidence_trend(yearly_presence):
    """Classify site trend as growing / stable / shrinking / unknown."""
    if not yearly_presence:
        return 'unknown'
    recent = [y for y in yearly_presence if y >= 2020]
    older  = [y for y in yearly_presence if y < 2020]
    if not older:
        return 'growing'
    ratio = len(recent) / max(len(older), 1)
    if ratio > 1.5:
        return 'growing'
    if ratio < 0.3:
        return 'shrinking'
    return 'stable'


def date_site(lat, lng):
    """
    Walk Landsat time-series backward from 2025 to 1984.
    Returns dict: {first_detected_year, yearly_presence, confidence_trend}

    Precondition: GEE must already be initialized via initialize_ee() before calling this.
    """
    years = list(range(2025, 1983, -1))
    yearly_presence = []

    for year in years:
        if _site_detected_in_year(lat, lng, year):
            yearly_presence.append(year)

    first_year = min(yearly_presence) if yearly_presence else None
    return {
        'first_detected_year': first_year,
        'yearly_presence': sorted(yearly_presence),
        'confidence_trend': determine_confidence_trend(yearly_presence),
    }
