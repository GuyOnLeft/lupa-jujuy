"""
Stage 1: Rules-based image pre-filter.

Runs locally on downloaded Street View images using only PIL + numpy.
No API calls, no cost. Rejects ~60% of candidates before any LLM sees them.

Rejection rules:
  - Green dominant (>60% pixels): vegetation / overgrown lot
  - Sky dominant (>50% pixels): highway, bridge, open sky shot
  - Too bright overall (>50% pixels): overexposed, no-image placeholder
  - Blurry (Laplacian variance < threshold): no-image or motion blur
"""
import numpy as np
from pathlib import Path
from PIL import Image


# Thresholds — tuned from manual review observations
GREEN_RATIO_THRESHOLD  = 0.55   # >55% green pixels → vegetation
SKY_RATIO_THRESHOLD    = 0.45   # >45% sky-blue pixels → highway/bridge
BRIGHT_RATIO_THRESHOLD = 0.60   # >60% very bright pixels → overexposed/blank
BLUR_VARIANCE_THRESHOLD = 80.0  # Laplacian variance < 80 → blurry/blank


def _load_rgb(path: str) -> np.ndarray:
    img = Image.open(path).convert('RGB').resize((320, 240))
    return np.array(img, dtype=np.float32)


def _green_ratio(arr: np.ndarray) -> float:
    """Fraction of pixels where green channel dominates."""
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    green_dominant = (g > r * 1.15) & (g > b * 1.15) & (g > 60)
    return float(green_dominant.mean())


def _sky_ratio(arr: np.ndarray) -> float:
    """Fraction of pixels that look like sky (light blue or light gray-blue)."""
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    brightness = (r + g + b) / 3.0
    # Sky: bluish tint, reasonably bright, not saturated
    sky_like = (b >= r) & (b >= g) & (brightness > 120) & (brightness < 240)
    return float(sky_like.mean())


def _bright_ratio(arr: np.ndarray) -> float:
    """Fraction of pixels that are very bright (overexposed / blank placeholder)."""
    brightness = (arr[:, :, 0] + arr[:, :, 1] + arr[:, :, 2]) / 3.0
    return float((brightness > 220).mean())


def _blur_score(arr: np.ndarray) -> float:
    """Laplacian variance as a proxy for image sharpness."""
    gray = arr.mean(axis=2)
    # Simple Laplacian: center - neighbors
    lap = (
        4 * gray[1:-1, 1:-1]
        - gray[:-2, 1:-1]
        - gray[2:, 1:-1]
        - gray[1:-1, :-2]
        - gray[1:-1, 2:]
    )
    return float(np.var(lap))


def passes_prefilter(image_path: str) -> tuple[bool, str]:
    """
    Returns (passes: bool, reason: str).
    passes=True means the image should proceed to LLM classification.
    passes=False means it should be rejected here with reason given.
    """
    path = Path(image_path)
    if not path.exists():
        return False, 'no_image'

    try:
        arr = _load_rgb(str(path))
    except Exception as e:
        return False, f'load_error: {e}'

    blur = _blur_score(arr)
    if blur < BLUR_VARIANCE_THRESHOLD:
        return False, f'blurry ({blur:.1f})'

    bright = _bright_ratio(arr)
    if bright > BRIGHT_RATIO_THRESHOLD:
        return False, f'overexposed ({bright:.2f})'

    sky = _sky_ratio(arr)
    if sky > SKY_RATIO_THRESHOLD:
        return False, f'sky_dominant ({sky:.2f})'

    green = _green_ratio(arr)
    if green > GREEN_RATIO_THRESHOLD:
        return False, f'vegetation ({green:.2f})'

    return True, 'pass'


def prefilter_candidates(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Filter a list of SV candidate dicts.
    Each dict must have 'sv_paths' key with list of image paths.

    Returns (passed, rejected) lists.
    """
    passed = []
    rejected = []

    for c in candidates:
        sv_paths = c.get('sv_paths', [])
        if not sv_paths:
            c['prefilter_reason'] = 'no_paths'
            rejected.append(c)
            continue

        # Check forward image (index 0); if it passes, keep candidate
        ok, reason = passes_prefilter(sv_paths[0])
        if ok:
            passed.append(c)
        else:
            c['prefilter_reason'] = reason
            rejected.append(c)

    return passed, rejected


if __name__ == '__main__':
    # Quick self-test on a few images
    import sys
    for path in sys.argv[1:]:
        ok, reason = passes_prefilter(path)
        status = '✓ PASS' if ok else f'✗ REJECT ({reason})'
        print(f'{status}: {path}')
