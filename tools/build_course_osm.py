"""Builds assets/<course>_osm.js for a Swiss course: buildings, woods, single trees, hedges and walls.

Source: OpenStreetMap (© OpenStreetMap contributors, ODbL), fetched from the Overpass API for the course's square and
kept in tools/.cache/<course>/. Same steps and output as build_leckhampton_osm.py.
Run after build_course.py:  python3 tools/build_course_osm.py basel
"""
import base64, json, math, os, sys, time, urllib.parse, urllib.request

COURSE = sys.argv[1] if len(sys.argv) > 1 else 'basel'
CACHE = os.path.join('tools/.cache', COURSE); os.makedirs(CACHE, exist_ok=True)
course = json.loads(open(f'assets/{COURSE}.js').read().split(' = ', 2)[2].rstrip().rstrip(';'))
cE, cN = course['origin']; SIZE, CELLS = course['size'], course['cells']; HALF = SIZE / 2
road = [(p[0], p[2]) for p in course['road']]
lat0, lon0, lat1, lon1 = course['bounds']

def to_lv95(lat, lon):                     # as in build_course.py
    p, l = (lat * 3600 - 169028.66) / 10000, (lon * 3600 - 26782.5) / 10000
    E = 2600072.37 + 211455.93 * l - 10938.51 * l * p - 0.36 * l * p * p - 44.54 * l ** 3
    N = 1200147.07 + 308807.95 * p + 3745.25 * l * l + 76.63 * p * p - 194.56 * l * l * p + 119.79 * p ** 3
    return E, N
def local(lat, lon):
    E, N = to_lv95(lat, lon); return (E - cE, -(N - cN))

# distance to the nearest point of the road line
def road_dist(x, z):
    return math.sqrt(min((px - x) ** 2 + (pz - z) ** 2 for px, pz in road))

path = os.path.join(CACHE, 'overpass.json')
if not os.path.exists(path):
    bb = f'{lat0},{lon0},{lat1},{lon1}'
    q = (f'[out:json][timeout:180];(way["building"]({bb});way["natural"="wood"]({bb});way["landuse"="forest"]({bb});'
         f'relation["natural"="wood"]({bb});relation["landuse"="forest"]({bb});node["natural"="tree"]({bb});'
         f'way["barrier"~"^(hedge|wall|retaining_wall)$"]({bb}););out geom;')
    for attempt in range(5):
        try:
            req = urllib.request.Request('https://overpass-api.de/api/interpreter', data=urllib.parse.urlencode({'data': q}).encode(),
                                         headers={'User-Agent': 'golden-hour-ride-poc'})
            body = urllib.request.urlopen(req, timeout=240).read()
            json.loads(body); open(path, 'wb').write(body); break       # keep only a complete answer
        except Exception as ex:
            if attempt == 4: raise
            print('  overpass busy, retrying:', ex); time.sleep(15 + attempt * 15)
els = {}
for e in json.load(open(path)).get('elements', []):
    els[(e['type'], e['id'])] = e
print('elements:', len(els))
ring = lambda geom: [local(p['lat'], p['lon']) for p in geom]
inside = lambda x, z, m=0: abs(x) < HALF - m and abs(z) < HALF - m

def best_box(pts):                       # smallest rectangle around a footprint, trying each wall's direction
    best = None
    for (x1, z1), (x2, z2) in zip(pts, pts[1:]):
        L = math.hypot(x2 - x1, z2 - z1)
        if L < 0.5: continue
        ux, uz = (x2 - x1) / L, (z2 - z1) / L
        us = [x * ux + z * uz for x, z in pts]; vs = [-x * uz + z * ux for x, z in pts]
        w, d = max(us) - min(us), max(vs) - min(vs)
        if best is None or w * d < best[0]:
            cu, cv = (max(us) + min(us)) / 2, (max(vs) + min(vs)) / 2
            best = (w * d, cu * ux - cv * uz, cu * uz + cv * ux, w, d, math.atan2(uz, ux))
    return best

def height(t):
    try: return max(2.5, float(str(t.get('height', '')).replace('m', '').strip()))
    except ValueError: pass
    try: return max(2.5, float(t['building:levels']) * 3)
    except (KeyError, ValueError): pass
    b = t.get('building')
    if b == 'church' or t.get('amenity') == 'place_of_worship': return 13
    if b in ('garage', 'garages', 'shed', 'hut', 'carport', 'roof', 'greenhouse'): return 2.6
    return 5.6

buildings, woods, holes, trees, lines = [], [], [], [], []
for e in els.values():
    t = e.get('tags', {})
    if e['type'] == 'node':
        if t.get('natural') == 'tree':
            x, z = local(e['lat'], e['lon'])
            if inside(x, z, 20) and road_dist(x, z) > 4.5: trees.append([round(x, 1), round(z, 1)])
        continue
    if e['type'] == 'way' and 'geometry' in e:
        pts = ring(e['geometry'])
        if t.get('building') and len(pts) >= 4:
            b = best_box(pts)
            if not b: continue
            _, x, z, w, d, ang = b
            if w < d: w, d, ang = d, w, ang + math.pi / 2
            if not inside(x, z, 40) or w > 90 or w < 2 or d < 2: continue
            rd = road_dist(x, z)
            if rd > 700 or rd < d / 2 + 4.5: continue          # skip what you'd never see, and anything overlapping the road
            h = height(t); small = h < 3.5
            buildings.append([round(x, 1), round(z, 1), round(w, 1), round(d, 1), round(ang, 3), round(h, 1), 0 if (small or d > 14) else 1])
        elif t.get('natural') == 'wood' or t.get('landuse') == 'forest':
            if len(pts) >= 4: woods.append(pts)
        elif t.get('barrier') in ('hedge', 'wall', 'retaining_wall'):
            kind = 0 if t['barrier'] == 'hedge' else 1
            for (x1, z1), (x2, z2) in zip(pts, pts[1:]):
                L = math.hypot(x2 - x1, z2 - z1); n = max(1, math.ceil(L / 6))
                for k in range(n):
                    ax, az = x1 + (x2 - x1) * k / n, z1 + (z2 - z1) * k / n; bx, bz = x1 + (x2 - x1) * (k + 1) / n, z1 + (z2 - z1) * (k + 1) / n
                    mx, mz = (ax + bx) / 2, (az + bz) / 2
                    if inside(mx, mz, 20) and 4.4 < road_dist(mx, mz) < 400: lines.append([round(ax, 1), round(az, 1), round(bx, 1), round(bz, 1), kind])
    elif e['type'] == 'relation' and (t.get('natural') == 'wood' or t.get('landuse') == 'forest'):
        for m in e.get('members', []):
            if m.get('type') == 'way' and 'geometry' in m and len(m['geometry']) >= 3:
                (holes if m.get('role') == 'inner' else woods).append(ring(m['geometry']))

# woodland as a grid matching the terrain's vertices
W = CELLS + 1; mask = bytearray(W * W)
def fill(poly, val):
    if poly[0] != poly[-1]: poly = poly + [poly[0]]
    zs = [p[1] for p in poly]
    for iz in range(max(0, math.ceil((min(zs) + HALF) / SIZE * CELLS)), min(CELLS, math.floor((max(zs) + HALF) / SIZE * CELLS)) + 1):
        z = -HALF + iz * SIZE / CELLS; xs = []
        for (x1, z1), (x2, z2) in zip(poly, poly[1:]):
            if (z1 <= z < z2) or (z2 <= z < z1): xs.append(x1 + (z - z1) / (z2 - z1) * (x2 - x1))
        xs.sort()
        for a, b in zip(xs[::2], xs[1::2]):
            for ix in range(max(0, math.ceil((a + HALF) / SIZE * CELLS)), min(CELLS, math.floor((b + HALF) / SIZE * CELLS)) + 1): mask[iz * W + ix] = val
for p in woods: fill(p, 1)
for p in holes: fill(p, 0)
bits = bytearray((len(mask) + 7) // 8)
for i, v in enumerate(mask):
    if v: bits[i >> 3] |= 1 << (i & 7)
print('buildings %d, single trees %d, hedge/wall pieces %d (hedge %d), woodland %.2f km2' % (len(buildings), len(trees), len(lines), sum(1 for l in lines if l[4] == 0), sum(mask) * (SIZE / CELLS) ** 2 / 1e6))
out = {'buildings': buildings, 'trees': trees, 'lines': lines, 'woods': base64.b64encode(bytes(bits)).decode(), 'credit': 'Buildings, woods and hedges © OpenStreetMap contributors.'}
open(f'assets/{COURSE}_osm.js', 'w').write(f'window.RIDE_COURSES.{COURSE}.osm = ' + json.dumps(out, separators=(',', ':')) + ';\n')
print(f'wrote assets/{COURSE}_osm.js', os.path.getsize(f'assets/{COURSE}_osm.js') // 1024, 'KB')
