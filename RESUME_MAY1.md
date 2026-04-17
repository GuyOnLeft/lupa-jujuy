# Resume Street View Classification — May 1

## Where We Left Off

- **Total SV locations scanned:** 8,713
- **Already classified by Haiku:** 644 (hit Anthropic monthly limit mid-run)
- **Remaining to classify:** 8,069
- **Already confirmed sites saved:** `data/output/sv_20260416_192626.json` (647 sites)
- **Resume candidates saved:** `data/output/resume_candidates.json` (8,069 locations)
- **Satellite sites:** `data/output/seed_20260416_014134.json` (18 sites)
- **Manual review results:** `data/output/reviewed_sites.json` (4 confirmed, 14 borderline, 555 pending)

All 17,426 Street View images are already downloaded to `data/sv_candidates/` — no re-downloading needed.

## New Pipeline Architecture (v2)

Manual review showed ~95% false positive rate with the original approach. The fix:

### Stage 0: Proximity Filter (free)
Only keep SV locations within **200m of a satellite anomaly centroid** (18 centroids).
- 8,069 → ~263 candidates (~97% reduction, zero cost)

### Stage 1: CV Pre-filter (free, PIL/numpy)
Reject obvious negatives using pixel analysis:
- Sky dominant > 45% pixels → highway/bridge/overpass → reject
- Very bright > 60% pixels → overexposed/blank → reject
- Blurry → no-image placeholder → reject
- ~263 → ~220 candidates (17% additional reduction)

### Stage 2: Haiku fast pass (cheap)
Improved prompt with explicit rejection criteria for:
- Normal dirt roads, construction sites, overgrown lots, highway embankments
- Threshold: auto-confirm > 0.85, uncertain 0.65–0.85, reject < 0.65
- ~220 → ~30-40 confirmed + ~20-30 uncertain

### Stage 3: Sonnet review (moderate cost)
Both forward AND right-angle images sent together for uncertain cases.
- ~25 uncertain → ~10-15 additional confirmed

**Total estimate: ~45-55 sites confirmed, ~$0.80 cost**

## What To Do On May 1

### Step 1: Run the new pipeline
```bash
cd /Users/jeremymunson/basura-tracker/satellite-scanner
source venv/bin/activate
venv/bin/python3 run_resume_may1.py
```

This will:
1. Filter 8,069 candidates → ~263 near satellite centroids
2. Apply CV pre-filter → ~220 candidates
3. Run Stage 2 Haiku + Stage 3 Sonnet on ~220 candidates
4. Merge with existing 647 confirmed sites
5. Save final output to `data/output/sv_final.json`

**Estimated cost: ~$0.80 (vs original ~$11)**

### Step 2: Human spot-check
Open `review.html` in browser to quickly approve/reject the ~45-55 AI-confirmed sites.
This is the final accuracy gate — 10 minutes of review pushes precision to >85%.

### Step 3: Load into map
Open `map.html`, click Load data, select:
- `data/output/sv_final.json` (or `reviewed_sites.json` after spot-check)
- `data/output/seed_20260416_014134.json`

### Step 4: NBI enrichment
```bash
venv/bin/python3 enrich_nbi.py data/output/sv_final.json data/output/seed_20260416_014134.json
```
Output: `data/output/enriched_sites.json`

## Human-Reviewed Sites (available now)

From manual review of ~155 sites in this session:
- **4 confirmed waste dumps** (ready to show)
- **14 borderline** (worth a second look)
- Load `data/output/reviewed_sites.json` into map.html to see them

## Current MVP Data (use now for demo)
- 647 street view sites + 18 satellite = **665 total**
- Load `sv_20260416_192626.json` + `seed_20260416_014134.json` into map.html
- Or load `reviewed_sites.json` to see with human verdict layer

## Note on Architecture
The original SV scan sampled a city-wide grid. This found some real dumps (sites 70, 73, 75, 136) but also flagged ~95% false positives. The new pipeline focuses SV on satellite anomaly centroids — trading broader discovery for much higher precision. The 4 manually-confirmed sites are outside 200m of satellite centroids and represent independent SV finds; they are preserved in `reviewed_sites.json`.
