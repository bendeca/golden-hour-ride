"""Builds the present-day world for a Swiss course: assets/<course>_ortho.jpg and assets/<course>_world.js.

  Aerial photo  SWISSIMAGE (the 2 m version), stitched into one picture of the course square.
  Buildings     swissBUILDINGS3D 3.0 (CityGML): real walls and roofs near the road, simple blocks further out.
  Trees         where the laser survey found them: swissSURFACE3D (tops of trees and roofs) minus swissALTI3D
                (bare ground) gives the height of everything standing; its peaks are the trees.
All © swisstopo, open data. Run after build_course.py:
  pip3 install tifffile imagecodecs numpy pillow
  python3 tools/build_course_world.py basel
"""
import base64, io, json, math, os, struct, sys, zipfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
import numpy as np, tifffile
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import swisstopo as S

COURSE = sys.argv[1] if len(sys.argv) > 1 else 'basel'
CACHE = S.use_cache(COURSE)
course = json.loads(open(f'assets/{COURSE}.js').read().split(' = ', 2)[2].rstrip().rstrip(';'))
cE, cN = course['origin']; SIZE, CELLS = course['size'], course['cells']; HALF = SIZE / 2; CELL = SIZE / CELLS
E0, N0, E1, N1 = cE - HALF, cN - HALF, cE + HALF, cN + HALF
PX = 2.0; W = int(round(SIZE / PX))                  # the 2 m working grid over the whole square; row 0 is the north edge
ORTHO = 4096                                         # the picture the page gets: 4096 px across, about 2.5 m a pixel
NEAR = 150                                           # buildings this close to the road get their real shape
TREE_ALL, TREE_FAR, TREE_CAP = 250, 900, 60000       # every tree within 250 m of the road, fewer out to 900 m, at most 60k

def local(E, N): return E - cE, -(N - cN)            # x east, z south, as the page uses
def px_of(x, z): return (x + HALF) / PX, (z + HALF) / PX

# ---- distance to the road, on a 10 m grid (only out to 1.5 km matters)
road = np.array([(p[0], p[2]) for p in course['road']])
RG = 10; RW = int(SIZE / RG) + 1; LIM = 1500
rd = np.full((RW, RW), float(LIM), np.float32)
gx = np.arange(RW) * RG - HALF
for x, z in road:
    i0, i1 = max(0, int((x - LIM + HALF) / RG)), min(RW, int((x + LIM + HALF) / RG) + 1)
    j0, j1 = max(0, int((z - LIM + HALF) / RG)), min(RW, int((z + LIM + HALF) / RG) + 1)
    if i0 >= i1 or j0 >= j1: continue
    d = np.sqrt((gx[None, i0:i1] - x) ** 2 + (gx[j0:j1, None] - z) ** 2)
    np.minimum(rd[j0:j1, i0:i1], d, out=rd[j0:j1, i0:i1])
def road_d(x, z):
    i, j = int(round((x + HALF) / RG)), int(round((z + HALF) / RG))
    return float(rd[min(RW - 1, max(0, j)), min(RW - 1, max(0, i))])

# ---- 1. aerial photo
otiles = S.km_tiles('ch.swisstopo.swissimage-dop10', E0, N0, E1, N1, lambda k: k.endswith('_2_2056.tif'), 'ortho')
want = [(i, j) for i in range(math.floor(E0 / 1000), math.floor(E1 / 1000) + 1) for j in range(math.floor(N0 / 1000), math.floor(N1 / 1000) + 1)]
photo = np.zeros((W, W, 3), np.uint8); have = np.zeros((W, W), bool)
def load_photo(k):
    href = otiles.get(k)
    if not href: return k, None
    try: return k, tifffile.imread(S.fetch(href, os.path.join(CACHE, os.path.basename(href))))
    except Exception as ex: print('  photo tile failed', k, ex); return k, None
def paste(dst, k, img, mask=None):
    """Put a 1 km tile (2 m pixels, top-left at E i km, N j+1 km) into a W x W grid of the square."""
    i, j = k; c0 = int(round((i * 1000 - E0) / PX)); r0 = int(round((N1 - (j + 1) * 1000) / PX))
    h, w = img.shape[:2]
    a0, b0 = max(0, r0), max(0, c0); a1, b1 = min(W, r0 + h), min(W, c0 + w)
    if a0 >= a1 or b0 >= b1: return
    dst[a0:a1, b0:b1] = img[a0 - r0:a1 - r0, b0 - c0:b1 - c0]
    if mask is not None: mask[a0:a1, b0:b1] = True
with ThreadPoolExecutor(4) as ex:
    for k, img in ex.map(load_photo, want):
        if img is not None: paste(photo, k, img[..., :3], have)
fill = photo[have].mean(axis=0) if have.any() else np.array([110, 120, 90])
photo[~have] = fill.astype(np.uint8)                 # across the border: an average colour
Image.fromarray(photo).resize((ORTHO, ORTHO), Image.LANCZOS).save(f'assets/{COURSE}_ortho.jpg', quality=80, optimize=True, progressive=True)
print('photo: %d tiles, %.0f %% of the square covered, wrote assets/%s_ortho.jpg %d KB' % (sum(1 for k in want if k in otiles), have.mean() * 100, COURSE, os.path.getsize(f'assets/{COURSE}_ortho.jpg') // 1024))
def colour_at(x, z, r=1):
    c, rr = px_of(x, z); c, rr = int(c), int(rr)
    a = photo[max(0, rr - r):min(W, rr + r + 1), max(0, c - r):min(W, c + r + 1)].reshape(-1, 3)
    return a.mean(axis=0) if len(a) else fill

# ---- 2. buildings
sheets = {}
for f in S.stac_items('ch.swisstopo.swissbuildings3d_3_0', E0, N0, E1, N1, 'bldg'):
    p = f['id'].split('_')
    if len(p) != 5: continue                         # skip the whole-country editions
    href = next((a['href'] for k, a in f['assets'].items() if k.endswith('citygml.zip')), None)
    if href and (p[4] not in sheets or int(p[3]) > sheets[p[4]][0]): sheets[p[4]] = (int(p[3]), href)
print('building sheets:', len(sheets))

def best_box(pts):                                   # smallest rectangle around a footprint, trying each wall's direction
    best = None
    for (x1, z1), (x2, z2) in zip(pts, pts[1:] + pts[:1]):
        L = math.hypot(x2 - x1, z2 - z1)
        if L < 0.5: continue
        ux, uz = (x2 - x1) / L, (z2 - z1) / L
        us = [x * ux + z * uz for x, z in pts]; vs = [-x * uz + z * ux for x, z in pts]
        w, d = max(us) - min(us), max(vs) - min(vs)
        if best is None or w * d < best[0]:
            cu, cv = (max(us) + min(us)) / 2, (max(vs) + min(vs)) / 2
            best = (w * d, cu * ux - cv * uz, cu * uz + cv * ux, w, d, math.atan2(uz, ux))
    return best

def triangulate(poly):
    """Ear clipping of one flat polygon (list of 3D points, not closed); returns index triples."""
    n = len(poly)
    if n < 3: return []
    if n == 3: return [(0, 1, 2)]
    P = np.array(poly); nrm = np.zeros(3)
    for a in range(n):                               # Newell's normal: which plane to flatten it onto
        b = (a + 1) % n
        nrm += [(P[a, 1] - P[b, 1]) * (P[a, 2] + P[b, 2]), (P[a, 2] - P[b, 2]) * (P[a, 0] + P[b, 0]), (P[a, 0] - P[b, 0]) * (P[a, 1] + P[b, 1])]
    ax = int(np.argmax(np.abs(nrm))); keep = [k for k in range(3) if k != ax]
    Q = P[:, keep]; sgn = 1 if nrm[ax] > 0 else -1
    if ax == 1: sgn = -sgn
    cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    idx, out, guard = list(range(n)), [], 0
    while len(idx) > 3 and guard < n * n:
        guard += 1; found = False
        for t in range(len(idx)):
            i0, i1, i2 = idx[t - 1], idx[t], idx[(t + 1) % len(idx)]
            if cross(Q[i0], Q[i1], Q[i2]) * sgn <= 1e-9: continue
            if any(cross(Q[i0], Q[i1], Q[m]) * sgn > 0 and cross(Q[i1], Q[i2], Q[m]) * sgn > 0 and cross(Q[i2], Q[i0], Q[m]) * sgn > 0 for m in idx if m not in (i0, i1, i2)): continue
            out.append((i0, i1, i2)); idx.pop(t); found = True; break
        if not found: break
    if len(idx) == 3: out.append(tuple(idx))
    elif len(idx) > 3: out += [(idx[0], idx[k], idx[k + 1]) for k in range(1, len(idx) - 1)]   # a twisted ring: fan the rest
    return out

PLASTER = [(236, 229, 214), (228, 222, 207), (241, 237, 229), (219, 211, 196), (233, 223, 201), (224, 214, 199), (238, 232, 220)]
near_a, near_n, near_m, near_v, near_i, near_c, far, foot = [], [], [], [], [], [], [], []
count = {'all': 0, 'near': 0, 'far': 0, 'outside': 0, 'tris': 0}
def building(el):
    surf = {'Roof': [], 'Wall': [], 'Ground': []}
    for s in el.iter():
        t = s.tag.rsplit('}', 1)[-1]
        if t in ('RoofSurface', 'WallSurface', 'GroundSurface'):
            for pl in s.iter():
                if pl.tag.endswith('}posList') and pl.text:
                    v = list(map(float, pl.text.split()))
                    pts = [(*local(v[k], v[k + 1]), v[k + 2]) for k in range(0, len(v) - 2, 3)]
                    if len(pts) > 1 and pts[0] == pts[-1]: pts = pts[:-1]
                    if len(pts) >= 3: surf[t[:-7]].append([(x, y, z) for x, z, y in pts])   # (x, height, z)
    allp = [p for k in surf for poly in surf[k] for p in poly]
    if not allp: return
    count['all'] += 1
    xs, ys, zs = [p[0] for p in allp], [p[1] for p in allp], [p[2] for p in allp]
    cx, cz = (min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2
    if abs(cx) > HALF - 20 or abs(cz) > HALF - 20: count['outside'] += 1; return
    ground = min(p[1] for poly in surf['Ground'] for p in poly) if surf['Ground'] else min(ys)
    fp = [(p[0], p[2]) for poly in surf['Ground'] for p in poly] or [(x, z) for x, z in zip(xs, zs)]
    for poly in surf['Ground']: foot.append([(p[0], p[2]) for p in poly])
    if not surf['Ground']: foot.append([(min(xs), min(zs)), (max(xs), min(zs)), (max(xs), max(zs)), (min(xs), max(zs))])
    d = road_d(cx, cz)
    roof = surf['Roof'] or [poly for poly in surf['Wall']]
    rlo, rhi = (min(p[1] for poly in roof for p in poly), max(p[1] for poly in roof for p in poly)) if roof else (max(ys), max(ys))
    rc = colour_at(cx, cz, 2)
    if d < NEAR:
        count['near'] += 1
        verts, ntri = {}, 0                          # corners shared between a building's triangles
        wall = np.array(PLASTER[count['near'] % len(PLASTER)]) * (0.93 + 0.07 * ((count['near'] * 7919) % 13) / 12)
        for kind in ('Roof', 'Wall'):
            for poly in surf[kind]:
                for a, b, c in triangulate(poly):
                    for p in (poly[a], poly[b], poly[c]):
                        key = (round((p[0] - cx) * 10), round((p[1] - ground) * 10), round((p[2] - cz) * 10))
                        if key not in verts: verts[key] = len(verts); near_v.extend(key)
                        near_i.append(verts[key])
                    ntri += 1
                    if kind == 'Roof':
                        m = [(poly[a][k] + poly[b][k] + poly[c][k]) / 3 for k in (0, 2)]
                        col = colour_at(m[0], m[1], 1) * 0.6 + rc * 0.4     # the photo under that part of the roof
                    else: col = wall
                    near_c.extend(int(min(255, max(0, v))) for v in col)
        if ntri: near_a.extend([cx, ground, cz]); near_n.append(ntri); near_m.append(len(verts)); count['tris'] += ntri
    else:
        b = best_box(fp)
        if not b: return
        _, bx, bz, w, dd, ang = b
        if w < dd: w, dd, ang = dd, w, ang + math.pi / 2
        if w < 2 or dd < 2 or w * dd < 25 or d > 1200: return      # sheds, and anything over 1.2 km off: the photo shows them
        h = max(2.4, rlo - ground); ridge = rhi - rlo
        count['far'] += 1
        far.append([round(bx), round(bz), round(w, 1), round(dd, 1), round(ang, 2), round(h, 1), 1 if ridge > 1.2 else 0, round(min(ridge, 12), 1), *[int(v) for v in rc]])

for sh, (year, href) in sorted(sheets.items()):
    path = S.fetch(href, os.path.join(CACHE, os.path.basename(href)))
    with zipfile.ZipFile(path) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith('.gml'))
        with zf.open(name) as fh:
            for ev, el in ET.iterparse(fh, events=('end',)):
                t = el.tag.rsplit('}', 1)[-1]
                if t == 'Building': building(el); el.clear()
                elif t == 'cityObjectMember': el.clear()
    print('  sheet %s (%d): %d buildings so far' % (sh, year, count['all']))
print('buildings: %(all)d, near the road %(near)d (%(tris)d triangles), further out %(far)d, outside the square %(outside)d' % count)

# footprints on the 2 m grid, a little wider, so roofs are never read as trees
fm = Image.new('L', (W, W), 0); dr = ImageDraw.Draw(fm)
for poly in foot:
    if len(poly) >= 3: dr.polygon([px_of(x, z) for x, z in poly], fill=255)
built = np.array(fm.filter(ImageFilter.MaxFilter(5))) > 0

# ---- 3. canopy: surface minus ground, at 2 m
stiles = S.km_tiles('ch.swisstopo.swisssurface3d-raster', E0, N0, E1, N1, lambda k: k.endswith('.tif'), 'surf')
atiles = S.tile_index(E0, N0, E1, N1)
chm = np.zeros((W, W), np.float32)
CHM = os.path.join(CACHE, 'canopy_2m.npy')            # the result is kept: the 160 source tiles (2 GB) are not
def load_canopy(k):
    sh, ah = stiles.get(k), atiles.get(k)
    if not sh or not ah: return k, None
    path = os.path.join(CACHE, os.path.basename(sh))
    try:
        surf = tifffile.imread(S.fetch(sh, path)).astype(np.float32)
        ground = tifffile.imread(S.fetch(ah, os.path.join(CACHE, os.path.basename(ah)))).astype(np.float32)
    except Exception as ex: print('  canopy tile failed', k, ex); return k, None
    finally:
        if os.path.exists(path): os.remove(path)     # 14 MB each: keep only what was taken from it
    h, w = surf.shape; f = h // ground.shape[0]
    top = surf[:ground.shape[0] * f, :ground.shape[1] * f].reshape(ground.shape[0], f, ground.shape[1], f).max(axis=(1, 3))
    c = top - ground; c[(ground < -500) | (top < -500) | ~np.isfinite(c)] = 0     # no data: nothing standing
    return k, np.clip(c, 0, 60)
if os.path.exists(CHM): chm = np.load(CHM).astype(np.float32)
else:
    done = 0
    with ThreadPoolExecutor(4) as ex:
        for k, c in ex.map(load_canopy, want):
            done += 1
            if c is not None: paste(chm, k, c)
            if done % 20 == 0: print('  canopy tiles %d of %d' % (done, len(want)))
    np.save(CHM, chm.astype(np.float16))
chm[built] = 0

# trees: canopy peaks over 3 m, the highest point within 3 m around (so at least 4 m apart)
pad = np.pad(chm, 1); m3 = chm.copy()
for dy in (0, 1, 2):
    for dx in (0, 1, 2): np.maximum(m3, pad[dy:dy + W, dx:dx + W], out=m3)
peak = (chm >= m3) & (chm > 3)
rr, cc = np.nonzero(peak)
tx, tz = cc * PX - HALF + PX / 2, rr * PX - HALF + PX / 2
td = rd[np.clip(np.round((tz + HALF) / RG).astype(int), 0, RW - 1), np.clip(np.round((tx + HALF) / RG).astype(int), 0, RW - 1)]
th = chm[rr, cc]
rng = np.random.default_rng(7)
keep = (td > 4) & ((td < TREE_ALL) | ((td < TREE_FAR) & (rng.random(len(td)) < 0.12)))
order = np.argsort(td[keep]); sel = np.nonzero(keep)[0][order][:TREE_CAP]
lum = photo[rr[sel], cc[sel]].astype(np.float32) @ np.array([0.3, 0.6, 0.1])
dark = (lum < np.percentile(lum, 35)).astype(np.uint8)           # the darkest third of crowns: spruce and fir
trees = b''.join(struct.pack('<hhBB', int(round(x * 2)), int(round(z * 2)), int(min(255, round(h * 4))), k)
                 for x, z, h, k in zip(tx[sel], tz[sel], th[sel], dark))
print('trees: %d canopy peaks in the square, kept %d (heights %.0f to %.0f m, median %.0f m; conifers %d)' % (len(th), len(sel), th[sel].min(), th[sel].max(), np.median(th[sel]), dark.sum()))

# forest: where more than half the ground around a terrain vertex is under trees over 3 m
cover = (chm > 3).astype(np.float32); ii = np.pad(cover.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
Wv = CELLS + 1; mask = bytearray(Wv * Wv); r = 4
for iz in range(Wv):
    pr = int(round((iz * CELL) / PX)); a0, a1 = max(0, pr - r), min(W, pr + r)
    for ix in range(Wv):
        pc = int(round((ix * CELL) / PX)); b0, b1 = max(0, pc - r), min(W, pc + r)
        if a1 > a0 and b1 > b0 and (ii[a1, b1] - ii[a0, b1] - ii[a1, b0] + ii[a0, b0]) / ((a1 - a0) * (b1 - b0)) > 0.5: mask[iz * Wv + ix] = 1
bits = bytearray((len(mask) + 7) // 8)
for i, v in enumerate(mask):
    if v: bits[i >> 3] |= 1 << (i & 7)
print('forest: %.1f km2 of %.1f' % (sum(mask) * CELL ** 2 / 1e6, SIZE ** 2 / 1e6))

b64 = lambda a: base64.b64encode(a).decode()
out = {
    'near': {'a': b64(np.array(near_a, np.float32).tobytes()), 'n': b64(np.array(near_n, np.uint16).tobytes()), 'm': b64(np.array(near_m, np.uint16).tobytes()),
             'v': b64(np.array(near_v, np.int16).tobytes()), 'i': b64(np.array(near_i, np.uint16).tobytes()), 'c': b64(bytes(near_c)), 'radius': NEAR},
    'far': far, 'trees': b64(trees), 'woods': b64(bytes(bits)),
    'credit': 'Aerial photo, buildings and trees: SWISSIMAGE, swissBUILDINGS3D, swissSURFACE3D © swisstopo.',
}
open(f'assets/{COURSE}_world.js', 'w').write(f'window.RIDE_COURSES.{COURSE}.world = ' + json.dumps(out, separators=(',', ':')) + ';\n')
print(f'wrote assets/{COURSE}_world.js', os.path.getsize(f'assets/{COURSE}_world.js') // 1024, 'KB')
