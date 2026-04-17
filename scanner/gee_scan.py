# satellite-scanner/scanner/gee_scan.py
import ee
import os
from scanner.config import METRO_BBOX, BSI_THRESHOLD, NDVI_THRESHOLD, MIN_AREA_M2, EE_PROJECT


def initialize_ee():
    """Initialize Earth Engine with project credentials."""
    ee.Initialize(project=EE_PROJECT)


def compute_bsi_expression():
    """Return the BSI formula as a string (for documentation/testing)."""
    return '((B11 + B4) - (B8 + B2)) / ((B11 + B4) + (B8 + B2))'


def _compute_bsi(image):
    """Compute Bare Soil Index on a Sentinel-2 image."""
    swir1 = image.select('B11')
    red   = image.select('B4')
    nir   = image.select('B8')
    blue  = image.select('B2')
    numerator   = swir1.add(red).subtract(nir.add(blue))
    denominator = swir1.add(red).add(nir.add(blue))
    return numerator.divide(denominator).rename('BSI')


def _compute_ndvi(image):
    """Compute NDVI on a Sentinel-2 image."""
    return image.normalizedDifference(['B8', 'B4']).rename('NDVI')


def find_candidate_sites(bbox=None):
    """
    Run spectral scan over bbox and return raw GEE FeatureCollection info dict.
    bbox: [west, south, east, north]. Defaults to METRO_BBOX.
    """
    if bbox is None:
        bbox = METRO_BBOX

    region = ee.Geometry.Rectangle(bbox)

    composite = (
        ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
        .filterDate('2024-01-01', '2024-12-31')
        .filterBounds(region)
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))
        .median()
    )

    bsi  = _compute_bsi(composite)
    ndvi = _compute_ndvi(composite)

    mask = bsi.gt(BSI_THRESHOLD).And(ndvi.lt(NDVI_THRESHOLD))

    candidates = mask.selfMask().reduceToVectors(
        geometry=region,
        scale=10,
        geometryType='polygon',
        eightConnected=True,
        maxPixels=int(1e8)
    )

    candidates = candidates.map(
        lambda f: f.set('area', f.geometry().area(1))
    ).filter(ee.Filter.gt('area', MIN_AREA_M2))

    candidates = candidates.map(lambda f: f.set({
        'centroid_lat': f.geometry().centroid(1).coordinates().get(1),
        'centroid_lng': f.geometry().centroid(1).coordinates().get(0),
    }))

    # Take top 200 by area (largest first) to keep cost and runtime manageable
    candidates = candidates.sort('area', False).limit(200)

    return candidates.getInfo()


def parse_candidates(gee_info):
    """
    Convert raw GEE FeatureCollection info into a list of candidate dicts.
    Each dict: {lat, lng, area_m2, geometry}
    """
    results = []
    for feature in gee_info.get('features', []):
        props = feature.get('properties', {})
        lat = props.get('centroid_lat')
        lng = props.get('centroid_lng')
        area = props.get('area')
        if lat is None or lng is None:
            continue
        results.append({
            'lat': lat,
            'lng': lng,
            'area_m2': area,
            'geometry': feature.get('geometry'),
        })
    return results
