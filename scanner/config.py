# satellite-scanner/scanner/config.py
import os
from dotenv import load_dotenv

load_dotenv()

# San Salvador de Jujuy metro bounding box [west, south, east, north]
METRO_BBOX = [-65.40, -24.25, -65.20, -24.10]

# Spectral thresholds
BSI_THRESHOLD = 0.05   # Bare Soil Index minimum
NDVI_THRESHOLD = 0.15  # Max vegetation index (low = bare)
MIN_AREA_M2 = 500      # Minimum waste site area in m²

# Tile export
TILE_SIZE = 400        # px
TILE_ZOOM = 18         # ~0.6m/px at this zoom

# Claude Vision
CONFIDENCE_THRESHOLD = 0.40
MODEL = 'claude-sonnet-4-6'

# API keys from environment
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')
STREETVIEW_API_KEY  = os.getenv('STREETVIEW_API_KEY', os.getenv('GOOGLE_MAPS_API_KEY'))
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
EE_PROJECT = os.getenv('EE_PROJECT')
