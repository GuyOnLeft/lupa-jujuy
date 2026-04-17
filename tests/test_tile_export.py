# satellite-scanner/tests/test_tile_export.py
import pytest
import responses
import os
from pathlib import Path
from unittest.mock import patch
from scanner.tile_export import build_tile_url, fetch_tile, export_candidate_tiles


def test_build_tile_url_contains_required_params():
    url = build_tile_url(lat=-24.185, lng=-65.300, api_key='TEST_KEY')
    assert 'center=-24.185%2C-65.3' in url or 'center=-24.185,-65.3' in url
    assert 'zoom=18' in url
    assert 'maptype=satellite' in url
    assert 'size=400x400' in url
    assert 'TEST_KEY' in url


@responses.activate
def test_fetch_tile_saves_png(tmp_path):
    fake_png = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
    responses.add(
        responses.GET,
        'https://maps.googleapis.com/maps/api/staticmap',
        body=fake_png,
        status=200,
        content_type='image/png'
    )
    path = fetch_tile(lat=-24.185, lng=-65.300, output_dir=str(tmp_path), api_key='KEY')
    assert Path(path).exists()
    assert Path(path).suffix == '.png'
    assert Path(path).read_bytes() == fake_png


def test_fetch_tile_filename_encodes_coords(tmp_path):
    import responses as resp_lib
    with resp_lib.RequestsMock() as rsps:
        rsps.add(rsps.GET, 'https://maps.googleapis.com/maps/api/staticmap',
                 body=b'fake', status=200)
        path = fetch_tile(lat=-24.185, lng=-65.300, output_dir=str(tmp_path), api_key='K')
    assert '-24.185000' in path
    assert '-65.300000' in path


@responses.activate
def test_export_candidate_tiles_returns_list(tmp_path):
    responses.add(
        responses.GET,
        'https://maps.googleapis.com/maps/api/staticmap',
        body=b'fakepng',
        status=200
    )
    candidates = [{'lat': -24.185, 'lng': -65.300, 'area_m2': 800, 'geometry': {}}]
    result = export_candidate_tiles(candidates, output_dir=str(tmp_path), api_key='KEY')
    assert len(result) == 1
    assert 'tile_path' in result[0]
    assert result[0]['lat'] == -24.185
