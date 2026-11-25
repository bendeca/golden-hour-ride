"""Shared helpers for the Swiss course builders: downloads with a cache, Swiss coordinates, and swisstopo's tile index.

All the data is swisstopo open data (credit "© swisstopo"), found through the STAC API at data.geo.admin.ch.
"""
import json, math, os, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'golden-hour-ride-poc'}
STAC = 'https://data.geo.admin.ch/api/stac/v0.9/collections/'
CACHE = 'tools/.cache'

def use_cache(course):
    global CACHE
    CACHE = os.path.join('tools/.cache', course); os.makedirs(CACHE, exist_ok=True)
    return CACHE

def fetch(url, path):
    """Download url to path (once), retrying when the server is busy; a half-finished download is never kept."""
    if os.path.exists(path): return path
    for attempt in range(6):
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180).read(); break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as ex:
            if attempt == 5 or (isinstance(ex, urllib.error.HTTPError) and ex.code not in (429, 500, 502, 503, 504)): raise
            time.sleep(3 + attempt * 3)
    open(path + '.part', 'wb').write(data); os.replace(path + '.part', path)
    return path

def get(url, name):
    return open(fetch(url, os.path.join(CACHE, name)), 'rb').read()

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

def stac_items(collection, E0, N0, E1, N1, tag):
    """Every item of a swisstopo collection that touches the LV95 box, following the pages."""
    (la0, lo0), (la1, lo1) = from_lv95(E0, N0), from_lv95(E1, N1)
    url = f'{STAC}{collection}/items?bbox={lo0 - 0.01:.4f},{la0 - 0.01:.4f},{lo1 + 0.01:.4f},{la1 + 0.01:.4f}&limit=100'
    out, page = [], 0
    while url:
        d = json.loads(get(url, f'{tag}_{round(E0)}_{round(N0)}_{page}.json')); page += 1
        out += d['features']
        url = next((l['href'] for l in d.get('links', []) if l.get('rel') == 'next'), None)
    return out

def km_tiles(collection, E0, N0, E1, N1, pick, tag):
    """{(i, j): href} for a collection of 1 km tiles (item ids like name_2024_2616-1257), newest year of each;
    pick(asset_key) chooses the file within an item."""
    best = {}
    for f in stac_items(collection, E0, N0, E1, N1, tag):
        parts = f['id'].split('_'); year, ij = int(parts[-2]), parts[-1]; i, j = map(int, ij.split('-'))
        href = next((a['href'] for k, a in f['assets'].items() if pick(k)), None)
        if href and ((i, j) not in best or year > best[(i, j)][0]): best[(i, j)] = (year, href)
    return {k: v[1] for k, v in best.items()}

def tile_index(E0, N0, E1, N1):
    """swissALTI3D, 2 m GeoTIFF."""
    return km_tiles('ch.swisstopo.swissalti3d', E0, N0, E1, N1, lambda k: k.endswith('.tif') and '_2_2056_' in k, 'stac')

class Tiles:
    """swissALTI3D 1 km tiles at 2 m, with bilinear lookup. Tile (i, j) covers E i..i+1 km, N j..j+1 km."""
    def __init__(self, index): self.index, self.g = index, {}
    def load(self, k):
        import tifffile
        href = self.index.get(k)
        if not href: return None
        try: return tifffile.imread(fetch(href, os.path.join(CACHE, os.path.basename(href)))).astype('float32')
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
