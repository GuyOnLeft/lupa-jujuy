#!/usr/bin/env python3
"""
NBI Enrichment Script.
Downloads INDEC 2010 census tract shapefile for Argentina,
does a spatial join to attach NBI (Necesidades Básicas Insatisfechas)
data to each confirmed waste site.

Usage:
  python enrich_nbi.py data/output/seed_*.json data/output/sv_*.json
  python enrich_nbi.py data/output/approved.json   # single file
"""
import sys
import json
import zipfile
import shutil
import requests
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

# INDEC 2010 census radios with NBI — hosted on CONICET, free, no login needed
RADIOS_URL = 'https://ri.conicet.gov.ar/bitstream/handle/11336/149711/RADIOS_2010_V2025-1.zip'
CACHE_DIR  = Path('data/nbi_cache')
ZIP_PATH   = CACHE_DIR / 'RADIOS_2010.zip'
SHP_DIR    = CACHE_DIR / 'RADIOS_2010'

# Jujuy province code in INDEC = 38
JUJUY_CODE = '38'


def download_radios():
    """Download and cache the INDEC census tract shapefile."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not ZIP_PATH.exists():
        print('Downloading INDEC census tract data (~47MB)...')
        resp = requests.get(RADIOS_URL, stream=True, timeout=120)
        resp.raise_for_status()
        with open(ZIP_PATH, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        print('Downloaded.')
    else:
        print('Using cached INDEC data.')

    if not SHP_DIR.exists():
        print('Extracting...')
        with zipfile.ZipFile(ZIP_PATH, 'r') as zf:
            zf.extractall(SHP_DIR)
        print('Extracted.')


def load_jujuy_radios():
    """Load census tracts for Jujuy province only."""
    # Find the shapefile
    shp_files = list(SHP_DIR.rglob('*.shp'))
    if not shp_files:
        raise FileNotFoundError(f'No .shp file found in {SHP_DIR}')

    print(f'Loading shapefile: {shp_files[0].name}')
    gdf = gpd.read_file(shp_files[0])

    print(f'Columns available: {list(gdf.columns)}')

    # Filter to Jujuy (province code 38)
    # INDEC uses 'link' or 'codigo' fields — try common ones
    for col in ['link', 'LINK', 'codigo', 'CODIGO', 'prov', 'PROV', 'cod_prov']:
        if col in gdf.columns:
            mask = gdf[col].astype(str).str.startswith(JUJUY_CODE)
            if mask.sum() > 0:
                gdf = gdf[mask].copy()
                print(f'Filtered to Jujuy using column "{col}": {len(gdf)} tracts')
                break

    # Ensure WGS84
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    return gdf


def find_nbi_column(gdf):
    """Find the NBI percentage column in the shapefile."""
    # Known column names in INDEC RADIOS_2010_V2025-1 shapefile
    known = ['DP_AB_POB', 'dp_ab_pob', 'NBI_PCT', 'nbi_pct']
    for col in known:
        if col in gdf.columns:
            print(f'NBI column found: {col}')
            return col

    # Generic search
    candidates = [c for c in gdf.columns if 'nbi' in c.lower()]
    if candidates:
        print(f'NBI columns found: {candidates}')
        return candidates[0]

    # Fallback: print all columns so we can inspect
    print('No NBI column found. Available columns:')
    for c in gdf.columns:
        print(f'  {c}: {gdf[c].dtype} — sample: {gdf[c].iloc[0] if len(gdf) > 0 else "N/A"}')
    return None


def enrich_sites(sites, radios_gdf, nbi_col):
    """
    Spatial join: attach NBI data to each site.
    Adds 'nbi_pct', 'nbi_label', 'census_tract_id' to each site dict.
    """
    # Build GeoDataFrame of sites
    points = gpd.GeoDataFrame(
        sites,
        geometry=[Point(s['longitude'], s['latitude']) for s in sites],
        crs='EPSG:4326'
    )

    joined = gpd.sjoin(points, radios_gdf, how='left', predicate='within')

    enriched = []
    for i, row in joined.iterrows():
        site = sites[i].copy()
        if nbi_col and nbi_col in row and row[nbi_col] is not None:
            try:
                nbi_val = float(row[nbi_col])
                site['nbi_pct'] = round(nbi_val, 1)
                if nbi_val >= 40:
                    site['nbi_label'] = 'very high'
                elif nbi_val >= 25:
                    site['nbi_label'] = 'high'
                elif nbi_val >= 15:
                    site['nbi_label'] = 'medium'
                else:
                    site['nbi_label'] = 'low'
            except (ValueError, TypeError):
                site['nbi_pct'] = None
                site['nbi_label'] = 'unknown'
        else:
            site['nbi_pct'] = None
            site['nbi_label'] = 'unknown'

        # Attach tract ID if available
        for id_col in ['link', 'LINK', 'codigo', 'CODIGO']:
            if id_col in row:
                site['census_tract_id'] = str(row[id_col])
                break

        enriched.append(site)

    return enriched


def main():
    input_files = sys.argv[1:] if len(sys.argv) > 1 else []
    if not input_files:
        # Default: latest output files
        output_dir = Path('data/output')
        input_files = sorted(output_dir.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:2]
        input_files = [str(p) for p in input_files]
        if not input_files:
            print('No JSON files found in data/output/. Pass file paths as arguments.')
            sys.exit(1)

    print(f'Input files: {input_files}')

    # Load all sites
    all_sites = []
    for path in input_files:
        with open(path) as f:
            sites = json.load(f)
            all_sites.extend(sites)
    print(f'Loaded {len(all_sites)} total sites')

    # Download and load census data
    download_radios()
    radios = load_jujuy_radios()
    nbi_col = find_nbi_column(radios)

    if nbi_col is None:
        print('\nCould not find NBI column automatically.')
        print('Run this script once to see available columns, then set nbi_col manually.')
        sys.exit(1)

    # Enrich
    print(f'\nEnriching {len(all_sites)} sites with NBI data (column: {nbi_col})...')
    enriched = enrich_sites(all_sites, radios, nbi_col)

    # Save
    output_path = Path('data/output/enriched_sites.json')
    output_path.write_text(json.dumps(enriched, ensure_ascii=False, indent=2))
    print(f'\nSaved {len(enriched)} enriched sites to {output_path}')

    # Summary
    with_nbi = [s for s in enriched if s.get('nbi_pct') is not None]
    print(f'{len(with_nbi)}/{len(enriched)} sites matched to a census tract')
    if with_nbi:
        avg = sum(s['nbi_pct'] for s in with_nbi) / len(with_nbi)
        print(f'Average NBI in affected tracts: {avg:.1f}%')


if __name__ == '__main__':
    main()
