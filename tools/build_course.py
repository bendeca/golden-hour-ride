"""Builds assets/<course>.js for a Swiss course: the road line plus a terrain height grid.

Route: OpenStreetMap routing service (car profile) through the course's waypoints.
Heights: swisstopo swissALTI3D (2 m grid, open data, © swisstopo), 1 km tiles found through the STAC API.
  Road profile sampled from the 2 m grid; surrounding terrain at the course's cell size (15 m for Basel).
Same steps and output format as build_leckhampton.py, which stays the builder for the English course.
Needs:  pip3 install tifffile imagecodecs numpy
Run from the project folder:  python3 tools/build_course.py basel
"""
import base64, json, math, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from swisstopo import use_cache, get, to_lv95, from_lv95, tile_index, Tiles

COURSES = {
    'basel': {
        'name': 'Gempen loop, Basel',
        # St. Jakob – Münchenstein – Dornach – up the Gempenstrasse – Gempen – Schönmatt – down to Arlesheim – St. Jakob
        'waypoints': [[47.5385, 7.6215], [47.4830, 7.6125], [47.4757, 7.6608], [47.4845, 7.6610], [47.4940, 7.6230], [47.5385, 7.6215]],
        'start': 6600,           # metres along the route: Dornach, about 500 m before the Gempenstrasse climb starts
        'margin': 1300,          # terrain beyond the road on every side, metres
        'cell': 15,              # 15 m keeps the mesh near Leckhampton's size (693 x 693 against 620 x 620)
        'world': True,           # present day: aerial photo, 3D buildings and surveyed trees (build_course_world.py)
    },
    'muttenz': {
        'name': 'Muttenz – Gempen',
        # a ridden loop (Strava GPX): Birsfelden – Muttenz – Wartenberg – Sulz – Schartenflue – Gempen – Arlesheim – Münchenstein
        'gpx': 'tools/routes/muttenz.gpx',
        'start': 4000,           # metres along the track: Muttenz, about 450 m before the climb to Wartenberg
        'margin': 1300,
        'cell': 15,
        'world': True,
    },
}
COURSE = sys.argv[1] if len(sys.argv) > 1 else 'basel'
C = COURSES[COURSE]
use_cache(COURSE)

# ---- route: a recorded track (GPX), or the router through waypoints
if C.get('gpx'):
    import re
    src = open(C['gpx']).read()
    latlon = [(float(a), float(b)) for a, b in re.findall(r'<(?:trk|rte)pt[^>]*?lat="([-\d.]+)"[^>]*?lon="([-\d.]+)"', src)]
    latlon += [(float(b), float(a)) for a, b in re.findall(r'<(?:trk|rte)pt[^>]*?lon="([-\d.]+)"[^>]*?lat="([-\d.]+)"', src)]
    print('gpx:', len(latlon), 'points')
else:
    W = C['waypoints']
    url = 'https://routing.openstreetmap.de/routed-car/route/v1/driving/' + ';'.join(f'{lon},{lat}' for lat, lon in W) + '?overview=full&geometries=geojson'
    data = json.loads(get(url, 'route.json'))
    latlon = [(lat, lon) for lon, lat in data['routes'][0]['geometry']['coordinates']]
    print('router:', len(latlon), 'points,', round(data['routes'][0]['distance']), 'm')

def hav(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0]); dp = p2 - p1; dl = math.radians(b[1] - a[1])
    return 2 * 6371000 * math.asin(math.sqrt(math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))
out, i = [], 0                      # cut out-and-back spurs the router adds at waypoints
if C.get('gpx'):                    # a recorded track has no spurs (and its hairpins must stay), but standing still leaves a cluster
    for p in latlon:                # of jittery points: keep a point only once the rider has moved 3 m
        if not out or hav(out[-1], p) >= 3: out.append(p)
    i = len(latlon)
while i < len(latlon):
    out.append(latlon[i]); skip, run, j = -1, 0, i + 1
    while j < len(latlon) and run < 600:
        run += hav(latlon[j - 1], latlon[j])
        if run > 20 and hav(latlon[i], latlon[j]) < 8: skip = j
        j += 1
    i = skip + 1 if skip > 0 else i + 1
pts = [to_lv95(*p) for p in out]
STEP = 5; line = [pts[0]]; carry = 0          # resample every 5 m
for a, b in zip(pts, pts[1:]):
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    if L == 0: continue
    d = STEP - carry
    while d <= L:
        line.append((a[0] + (b[0] - a[0]) * d / L, a[1] + (b[1] - a[1]) * d / L)); d += STEP
    carry = L - (d - STEP)
if C.get('gpx'):                    # GPS wanders a metre or two either way: average each point with its neighbours (10 m)
    line = [line[0]] + [((line[k - 1][0] + line[k][0] + line[k + 1][0]) / 3, (line[k - 1][1] + line[k][1] + line[k + 1][1]) / 3) for k in range(1, len(line) - 1)] + [line[-1]]
print('route:', len(line) * STEP, 'm after cleaning; gap between ends', round(math.hypot(line[0][0] - line[-1][0], line[0][1] - line[-1][1])), 'm')

# ---- the square of terrain around the route, and the tiles it needs
Es, Ns = [p[0] for p in line], [p[1] for p in line]
CELL = C['cell']
size = math.ceil((max(max(Es) - min(Es), max(Ns) - min(Ns)) + 2 * C['margin']) / 200) * 200
cE, cN = round((min(Es) + max(Es)) / 2 / CELL) * CELL, round((min(Ns) + max(Ns)) / 2 / CELL) * CELL
cells = size // CELL
tiles = Tiles(tile_index(cE - size / 2, cN - size / 2, cE + size / 2, cN + size / 2))
want = sorted({(i, j) for i in range(math.floor((cE - size / 2 - CELL) / 1000), math.floor((cE + size / 2 + CELL) / 1000) + 1)
               for j in range(math.floor((cN - size / 2 - CELL) / 1000), math.floor((cN + size / 2 + CELL) / 1000) + 1)})
tiles.need(want)
print('terrain: %d m square, %d cells; tiles %d, outside Switzerland or missing %d' % (size, cells, len(want), sum(1 for k in want if tiles.g.get(k) is None)))

# ---- road heights from the 2 m grid
hts = []
for k, (E, N) in enumerate(line):
    a, b = line[max(0, k - 1)], line[min(len(line) - 1, k + 1)]
    L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1; pe, pn = -(b[1] - a[1]) / L, (b[0] - a[0]) / L
    best = None
    for off in range(-7, 8):              # the road surface: flattest point across the road
        h0, h1, h2 = tiles.at(E + pe * (off - 1.5), N + pn * (off - 1.5)), tiles.at(E + pe * off, N + pn * off), tiles.at(E + pe * (off + 1.5), N + pn * (off + 1.5))
        if None in (h0, h1, h2): continue
        flat = abs(h2 - h0) + abs(off) * 0.02
        if best is None or flat < best[0]: best = (flat, h1)
    hts.append(best[1] if best else None)
miss = sum(h is None for h in hts)
for k in range(len(hts)):
    if hts[k] is None: hts[k] = hts[k - 1] if k and hts[k - 1] is not None else next(h for h in hts if h is not None)
# bridges: the height model is bare ground, so a road over a river or railway reads as a dip. Where a short stretch
# (up to 120 m) sits more than 1.5 m below the straight line between its ends, carry the road across on that line.
bridged = 0
for k in range(len(hts)):
    for span in range(24, 2, -1):
        e = k + span
        if e >= len(hts): continue
        chord = [hts[k] + (hts[e] - hts[k]) * t / span for t in range(span + 1)]
        below = [chord[t] - hts[k + t] for t in range(1, span)]
        if min(below) > -0.3 and max(below) > 1.5:
            hts[k:e + 1] = chord; bridged += 1; break
print('bridged dips:', bridged)
# robust smoothing: median of 5 (25 m) then two passes of a 35 m moving average
med = [sorted(hts[max(0, k - 2): k + 3])[len(hts[max(0, k - 2): k + 3]) // 2] for k in range(len(hts))]
for _ in range(2):
    med = [sum(med[max(0, k - 3): k + 4]) / len(med[max(0, k - 3): k + 4]) for k in range(len(med))]
hts = med
print('road heights: min %.1f max %.1f, missing %d of %d' % (min(hts), max(hts), miss, len(hts)))
grades = [(hts[k + 4] - hts[k]) / 20 * 100 for k in range(len(hts) - 4)]
print('steepest up %.1f%%, steepest down %.1f%%, climb %.0f m' % (max(grades), min(grades), sum(max(0, hts[k + 1] - hts[k]) for k in range(len(hts) - 1))))

# ---- terrain grid
grid, holes = [], 0
for iz in range(cells + 1):            # row 0 is the north edge (local z = -N)
    N = cN + size / 2 - iz * CELL
    for ix in range(cells + 1):
        h = tiles.at(cE - size / 2 + ix * CELL, N)
        if h is None: holes += 1
        grid.append(h)
for k in range(len(grid)):             # fill no-data (across the border) from the left / above
    if grid[k] is None: grid[k] = grid[k - 1] if k % (cells + 1) and grid[k - 1] is not None else (grid[k - cells - 1] if k > cells and grid[k - cells - 1] is not None else None)
fallback = sum(hts) / len(hts)
grid = [fallback if h is None else h for h in grid]
lo, hi = min(grid), max(grid)
print('terrain heights: %.1f to %.1f m, no-data cells %d' % (lo, hi, holes))
q = struct.pack('<%dH' % len(grid), *[round((h - lo) / (hi - lo) * 65535) for h in grid])

# road line in local metres (x east, z south), a control point every 15 m
road = [[round(line[k][0] - cE, 2), round(hts[k], 2), round(-(line[k][1] - cN), 2)] for k in range(0, len(line) - 1, 3)]
lat0, lon0 = from_lv95(cE - size / 2, cN - size / 2); lat1, lon1 = from_lv95(cE + size / 2, cN + size / 2)
course = {'name': C['name'], 'size': size, 'cells': cells, 'origin': [cE, cN], 'crs': 'LV95', 'start': C['start'], 'world': C.get('world', False),
          'bounds': [round(lat0, 5), round(lon0, 5), round(lat1, 5), round(lon1, 5)], 'demMin': lo, 'demMax': hi, 'road': road,
          'credit': 'Route © OpenStreetMap contributors. Heights: swissALTI3D © swisstopo.',
          'dem': base64.b64encode(q).decode()}
open(f'assets/{COURSE}.js', 'w').write(f'window.RIDE_COURSES = window.RIDE_COURSES || {{}};\nwindow.RIDE_COURSES.{COURSE} = ' + json.dumps(course) + ';\n')
print(f'wrote assets/{COURSE}.js', os.path.getsize(f'assets/{COURSE}.js') // 1024, 'KB;', len(road), 'road points')
