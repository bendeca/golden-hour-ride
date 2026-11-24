"""Builds assets/<course>.js for a Swiss course: the road line plus a terrain height grid.

Route: OpenStreetMap routing service (car profile) through the course's waypoints.
Heights: swisstopo swissALTI3D (2 m grid, open data, © swisstopo), 1 km tiles found through the STAC API.
  Road profile sampled from the 2 m grid; surrounding terrain at the course's cell size (15 m for Basel).
Same steps and output format as build_leckhampton.py, which stays the builder for the English course.
Needs:  pip install tifffile imagecodecs numpy
Run from the project folder:  python3 tools/build_course.py basel
"""
import base64, json, math, os, struct, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
import tifffile

COURSES = {
    'basel': {
        'name': 'Gempen loop, Basel',
        # St. Jakob – Münchenstein – Dornach – up the Gempenstrasse – Gempen – Schönmatt – down to Arlesheim – St. Jakob
        'waypoints': [[47.5385, 7.6215], [47.4830, 7.6125], [47.4757, 7.6608], [47.4845, 7.6610], [47.4940, 7.6230], [47.5385, 7.6215]],
        'start': 6600,           # metres along the route: Dornach, about 500 m before the Gempenstrasse climb starts
        'margin': 1300,          # terrain beyond the road on every side, metres
        'cell': 15,              # 15 m keeps the mesh near Leckhampton's size (693 x 693 against 620 x 620)
    },
}
COURSE = sys.argv[1] if len(sys.argv) > 1 else 'basel'
C = COURSES[COURSE]
CACHE = os.path.join('tools/.cache', COURSE)
os.makedirs(CACHE, exist_ok=True)
UA = {'User-Agent': 'golden-hour-ride-poc'}
STAC = 'https://data.geo.admin.ch/api/stac/v0.9/collections/ch.swisstopo.swissalti3d/items'

def get(url, name):
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        for attempt in range(6):
            try:
                data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read(); break
            except (urllib.error.URLError, TimeoutError) as ex:
                if attempt == 5 or (isinstance(ex, urllib.error.HTTPError) and ex.code not in (429, 500, 502, 503, 504)): raise
                time.sleep(3 + attempt * 3)
        open(path, 'wb').write(data)
    return open(path, 'rb').read()

def to_lv95(lat, lon):
    """WGS84 to Swiss LV95 (E, N), swisstopo's approximate formulas: within about a metre."""
    p, l = (lat * 3600 - 169028.66) / 10000, (lon * 3600 - 26782.5) / 10000
    E = 2600072.37 + 211455.93 * l - 10938.51 * l * p - 0.36 * l * p * p - 44.54 * l ** 3
    N = 1200147.07 + 308807.95 * p + 3745.25 * l * l + 76.63 * p * p - 194.56 * l * l * p + 119.79 * p ** 3
    return E, N

def from_lv95(E, N):
    y, x = (E - 2600000) / 1e6, (N - 1200000) / 1e6
    lon = 2.6779094 + 4.728982 * y + 0.791484 * y * x + 0.1306 * y * x * x - 0.0436 * y ** 3
    lat = 16.9023892 + 3.238272 * x - 0.270978 * y * y - 0.002528 * x * x - 0.0447 * y * y * x - 0.0140 * x ** 3
    return lat * 100 / 36, lon * 100 / 36

# ---- swissALTI3D: which 1 km tiles exist, newest survey of each
def tile_index(E0, N0, E1, N1):
    (la0, lo0), (la1, lo1) = from_lv95(E0, N0), from_lv95(E1, N1)
    url = f'{STAC}?bbox={lo0 - 0.01:.4f},{la0 - 0.01:.4f},{lo1 + 0.01:.4f},{la1 + 0.01:.4f}&limit=100'
    best, page = {}, 0
    while url:
        d = json.loads(get(url, f'stac_{round(E0)}_{round(N0)}_{page}.json')); page += 1
        for f in d['features']:
            _, year, ij = f['id'].split('_'); i, j = map(int, ij.split('-'))
            href = next((a['href'] for k, a in f['assets'].items() if k.endswith('.tif') and '_2_2056_' in k), None)
            if href and (i, j) not in best or href and int(year) > best[(i, j)][0]: best[(i, j)] = (int(year), href)
        url = next((l['href'] for l in d.get('links', []) if l.get('rel') == 'next'), None)
    return {k: v[1] for k, v in best.items()}

class Tiles:
    """swissALTI3D 1 km tiles at 2 m, with bilinear lookup. Tile (i, j) covers E i..i+1 km, N j..j+1 km."""
    def __init__(self, index): self.index, self.g = index, {}
    def load(self, k):
        href = self.index.get(k)
        if not href: return None
        try:
            get(href, os.path.basename(href))
            return tifffile.imread(os.path.join(CACHE, os.path.basename(href))).astype('float32')
        except Exception as ex: print('  tile failed', k, ex); return None
    def need(self, keys):
        keys = [k for k in keys if k not in self.g]
        with ThreadPoolExecutor(4) as ex:
            for k, r in zip(keys, ex.map(self.load, keys)): self.g[k] = r
    def at(self, E, N):
        i, j = math.floor(E / 1000), math.floor(N / 1000); d = self.g.get((i, j))
        if d is None: return None
        h, w = d.shape
        x = (E - i * 1000) / 2 - 0.5; y = ((j + 1) * 1000 - N) / 2 - 0.5
        x0 = max(0, min(w - 2, math.floor(x))); y0 = max(0, min(h - 2, math.floor(y)))
        u = min(1, max(0, x - x0)); v = min(1, max(0, y - y0))
        q = [float(d[y0, x0]), float(d[y0, x0 + 1]), float(d[y0 + 1, x0]), float(d[y0 + 1, x0 + 1])]
        if any(not (-500 < hh < 5000) for hh in q): return None
        return (q[0] * (1 - u) + q[1] * u) * (1 - v) + (q[2] * (1 - u) + q[3] * u) * v

# ---- route
W = C['waypoints']
url = 'https://routing.openstreetmap.de/routed-car/route/v1/driving/' + ';'.join(f'{lon},{lat}' for lat, lon in W) + '?overview=full&geometries=geojson'
data = json.loads(get(url, 'route.json'))
latlon = [(lat, lon) for lon, lat in data['routes'][0]['geometry']['coordinates']]
print('router:', len(latlon), 'points,', round(data['routes'][0]['distance']), 'm')

def hav(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0]); dp = p2 - p1; dl = math.radians(b[1] - a[1])
    return 2 * 6371000 * math.asin(math.sqrt(math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))
out, i = [], 0                      # cut out-and-back spurs the router adds at waypoints
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
course = {'name': C['name'], 'size': size, 'cells': cells, 'origin': [cE, cN], 'crs': 'LV95', 'start': C['start'],
          'bounds': [round(lat0, 5), round(lon0, 5), round(lat1, 5), round(lon1, 5)], 'demMin': lo, 'demMax': hi, 'road': road,
          'credit': 'Route © OpenStreetMap contributors. Heights: swissALTI3D © swisstopo.',
          'dem': base64.b64encode(q).decode()}
open(f'assets/{COURSE}.js', 'w').write(f'window.RIDE_COURSES = window.RIDE_COURSES || {{}};\nwindow.RIDE_COURSES.{COURSE} = ' + json.dumps(course) + ';\n')
print(f'wrote assets/{COURSE}.js', os.path.getsize(f'assets/{COURSE}.js') // 1024, 'KB;', len(road), 'road points')
