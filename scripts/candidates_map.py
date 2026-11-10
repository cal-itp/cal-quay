"""
The PRIMARY grouping inspection map: data/grouping_candidates_map.html
(+ data/evans_case_map.html, the 18th & Castro worked example).

Every multi-agency grouping candidate rendered per GROUP over satellite
imagery: stop dots + their GTFS route shapes colored by sub-group (same fill
= stays together), dot RING colored by agency, travel-direction arrows,
Voronoi∩buffer zone outlines, nearest-OSM-street evidence (dashed, labeled),
complexity-tier + agency filters. Published copy:
https://storage.googleapis.com/calitp-publish-data-analysis/cal-quay/grouping_candidates_map.html

Inputs (produced by the pipeline; run in this order first):
  pull_stops.py -> cluster_stops.py -> pull_shapes.py -> detect_splits.py
  - data/canonicalizer_stops_statewide.csv  groups + feed urls
  - newest data/stops_<YYYY_MM>.csv         route_dirs per stop
  - data/split_pairs.csv                    heading verdicts (flags + splits)
  - data/route_shapes.csv                   route shapes (optional extras:
    data/stop_shapes.csv, data/route_shapes_backfill.csv)
  - data/roads_near_stops.fgb               auto-downloaded if absent

  uv run scripts/candidates_map.py
"""

import json
import math
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import MultiPoint, box, shape as shp_shape
from shapely.ops import unary_union, voronoi_diagram
from shapely import STRtree

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cluster_stops as cs  # noqa: E402

OSM_CLIP_M = 200.0
SHAPE_CLIP_M = 300.0
ZONE_R_M = 12.0


def latest_stops() -> Path:
    hits = sorted((REPO / "data").glob("stops_[0-9]*.csv"))
    if not hits:
        raise SystemExit("No data/stops_<YYYY_MM>.csv — run pull_stops.py first.")
    return hits[-1]


df = pd.read_csv(REPO / "data" / "canonicalizer_stops_statewide.csv",
                 low_memory=False, dtype={"stop_id": str})
pairs_path = REPO / "data" / "split_pairs.csv"
pairs = (pd.read_csv(pairs_path, dtype=str) if pairs_path.exists()
         else pd.DataFrame(columns=["cluster_id", "a_agency", "a_stop",
                                    "b_agency", "b_stop", "verdict", "coverage"]))
stops9 = pd.read_csv(latest_stops(), low_memory=False, dtype=str)


def _shape_rows(fname):
    p = REPO / "data" / fname
    if not p.exists():
        return
    t = pd.read_csv(p, dtype=str)
    t["direction_id"] = t["direction_id"].astype(float).astype(int)
    yield from t.itertuples()


def _label(r):
    lab = r.route_short_name if isinstance(r.route_short_name, str) and r.route_short_name else r.route_id
    return f"{lab} dir{r.direction_id}" if r.direction_id >= 0 else str(lab)


STOP_SHAPES = {}
for r in _shape_rows("stop_shapes.csv"):
    STOP_SHAPES.setdefault((r.base64_url, r.stop_id), []).append(
        (_label(r), shp_shape(json.loads(r.shape_geojson))))

BF_IX = {}
# historical backfill first so active-version shapes overwrite overlapping keys
for fname in ("route_shapes_backfill.csv", "route_shapes.csv"):
    for r in _shape_rows(fname):
        BF_IX[(r.base64_url, r.route_id, r.direction_id)] = (
            _label(r), shp_shape(json.loads(r.shape_geojson)))
if not STOP_SHAPES and not BF_IX:
    raise SystemExit("No shape data — run scripts/pull_shapes.py first.")

print("loading roads...")
cs.ensure_roads()   # downloads the trimmed statewide file if nothing local
roads = pd.concat(
    [gpd.read_file(f, engine="pyogrio").to_crs("EPSG:3310")
     for f in cs.DRIVE_FGBS if f.exists()], ignore_index=True)
_s9 = stops9.set_index(["analysis_name", "stop_id"]).sort_index()


def stop_feed_routes(agency, sid):
    try:
        rows = _s9.loc[[(agency, str(sid))]]
    except KeyError:
        return None, [], ""
    row = rows.iloc[0]
    url = row["base64_url"]
    shapes = STOP_SHAPES.get((url, str(sid)), [])
    if shapes:
        return url, shapes, ", ".join(sorted({lab for lab, _ in shapes}))
    rds = set()
    if isinstance(row.get("route_dirs"), str) and row["route_dirs"]:
        for tok in row["route_dirs"].split(";"):
            if "|" in tok:
                rt, d = tok.rsplit("|", 1)
                rds.add((rt, int(d)))
    if isinstance(row.get("route_ids"), str) and row["route_ids"]:
        known = {rt for rt, _ in rds}
        for rt in row["route_ids"].split(";"):
            if rt and rt not in known:
                rds |= {(rt, d) for d in (-1, 0, 1) if (url, rt, d) in BF_IX}
    shapes = [BF_IX[(url, rt, d)] for rt, d in sorted(rds) if (url, rt, d) in BF_IX]
    if shapes:
        return url, shapes, ", ".join(sorted({lab for lab, _ in shapes})) + " (backfilled)"
    toks = []
    if isinstance(row.get("route_dirs"), str) and row["route_dirs"]:
        toks = row["route_dirs"].split(";")
    elif isinstance(row.get("route_ids"), str) and row["route_ids"]:
        toks = row["route_ids"].split(";")
    return url, [], ", ".join(sorted(t for t in toks if t)) + (" (no shape found)" if toks else "")


def to_latlon_segs(geom3310=None, geom4326=None):
    g = geom4326
    if g is None:
        g = gpd.GeoSeries([geom3310], crs="EPSG:3310").to_crs("EPSG:4326").iloc[0]
    if g.is_empty:
        return []
    geoms = g.geoms if g.geom_type.startswith("Multi") else [g]
    return [[[round(y, 6), round(x, 6)] for x, y in gg.coords]
            for gg in geoms if gg.geom_type == "LineString"]


def poly_rings(geom3310):
    g = gpd.GeoSeries([geom3310], crs="EPSG:3310").to_crs("EPSG:4326").iloc[0]
    if g.is_empty:
        return []
    polys = g.geoms if g.geom_type == "MultiPolygon" else [g]
    out = []
    for p in polys:
        if p.geom_type != "Polygon":
            continue
        entry = [[[round(y, 6), round(x, 6)] for x, y in p.exterior.coords]]
        for hole in p.interiors:   # dropping holes broke the disjointness guarantee
            entry.append([[round(y, 6), round(x, 6)] for x, y in hole.coords])
        out.append(entry)
    return out


CARDS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def shapes_for(agency, sid, pt4326):
    url, shapes, text = stop_feed_routes(agency, sid)
    pt3310 = gpd.GeoSeries([pt4326], crs="EPSG:4326").to_crs("EPSG:3310").iloc[0]
    buf4326 = gpd.GeoSeries([pt3310.buffer(SHAPE_CLIP_M)], crs="EPSG:3310").to_crs("EPSG:4326").iloc[0]
    out, labels = [], []
    for label, line in shapes:
        # physical heading at the stop (dir0/dir1 are arbitrary; N/S/E/W is truth)
        l3310 = gpd.GeoSeries([line], crs="EPSG:4326").to_crs("EPSG:3310").iloc[0]
        if l3310.distance(pt3310) <= 30:
            s = l3310.project(pt3310)
            # endpoint guard: at loop turnarounds / shape ends the local chord
            # degenerates and would fabricate a 0-degree "north" heading
            if 10.0 <= s <= l3310.length - 10.0:
                a = l3310.interpolate(s - 10)
                b = l3310.interpolate(s + 10)
                if not a.equals(b):
                    hdg = math.degrees(math.atan2(b.x - a.x, b.y - a.y)) % 360
                    label = f"{label} →{CARDS[int(((hdg + 22.5) % 360) // 45)]}"
        labels.append(label)
        clipped = line.intersection(buf4326)
        for seg in to_latlon_segs(geom4326=clipped):
            out.append({"label": label, "coords": seg})
    if labels:
        text = ", ".join(sorted(set(labels)))
    return out, text


def street_at(pt3310, max_d=15.0):
    idxs = roads.sindex.query(pt3310.buffer(max_d))
    if len(idxs) == 0:
        return None
    d, i = min((roads.geometry.iloc[i].distance(pt3310), i) for i in idxs)
    return None if d > max_d else roads.geometry.iloc[i].intersection(pt3310.buffer(OSM_CLIP_M))


def subgroup_zones(cid, members, subs):
    """PROPOSED outlines: one zone per proposed sub-group (local Voronoi cells of
    that sub-group's members ∩ its convex hull + 12 m). Disjoint by construction
    (all cells come from one diagram over the whole neighborhood)."""
    mem = df[df.cluster_id == cid]
    pad = 0.0015
    nb = df[df.stop_lat.between(mem.stop_lat.min() - pad, mem.stop_lat.max() + pad)
            & df.stop_lon.between(mem.stop_lon.min() - pad, mem.stop_lon.max() + pad)]
    nbp = gpd.GeoDataFrame(nb, geometry=gpd.points_from_xy(nb.stop_lon, nb.stop_lat),
                           crs="EPSG:4326").to_crs("EPSG:3310")
    mpts = gpd.GeoSeries(gpd.points_from_xy([m["ll"][1] for m in members],
                                            [m["ll"][0] for m in members]),
                         crs="EPSG:4326").to_crs("EPSG:3310")
    cells, tree = None, None
    upts = list(dict.fromkeys((round(pp.x, 3), round(pp.y, 3)) for pp in nbp.geometry))
    if len(upts) >= 2:   # the Voronoi split is what keeps zones disjoint — run it
        from shapely.geometry import Point as _P
        env = box(*nbp.total_bounds).buffer(300)
        cells = list(voronoi_diagram(MultiPoint([_P(x, y) for x, y in upts]), envelope=env).geoms)
        tree = STRtree(cells)
    out = []
    for s in sorted(set(subs)):
        pts = [mpts.iloc[k] for k in range(len(members)) if subs[k] == s]
        hull = unary_union([pp.buffer(ZONE_R_M) for pp in pts])  # hugs the dots
        zone = hull
        if cells is not None:
            mine = []
            for p in pts:
                cell = next((cells[j] for j in tree.query(p) if cells[j].covers(p)), None)
                if cell is not None:
                    mine.append(cell)
            if mine:
                zone = unary_union(mine).intersection(hull)
        out.append({"sub": s, "rings": poly_rings(zone)})
    return out


def propose_split(members, kitty_pairs):
    """Run the real partition with kitty pairs as cannot-links -> sub-group index per member."""
    n = len(members)
    pos = [(m["ll"][0], m["ll"][1]) for m in members]
    cannot = np.zeros((n, n), dtype=bool)
    dist = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            la1, lo1 = pos[i]; la2, lo2 = pos[j]
            dx = math.radians(lo2 - lo1) * math.cos(math.radians(la1)) * cs.EARTH_R
            dy = math.radians(la2 - la1) * cs.EARTH_R
            dist[i, j] = dist[j, i] = math.hypot(dx, dy)
    ix = {}
    for k, m in enumerate(members):
        ix.setdefault((m["ag"], m["sid"]), []).append(k)
    for a, b in kitty_pairs:
        # (ag, stop_id) is not unique: constrain every matching record pair,
        # still guarding near-coincident rows (pipeline MIN_SEP rule)
        for i in ix.get(a, []):
            for j in ix.get(b, []):
                if i != j and dist[i, j] > cs.MIN_SEP_M:
                    cannot[i, j] = cannot[j, i] = True
    labels = cs.partition_compatible(cannot, dist, pos)
    uniq = {l: k for k, l in enumerate(dict.fromkeys(labels))}
    return [uniq[l] for l in labels]


def member_bundle(row, pt3310=None, with_street=True):
    pt4326 = gpd.points_from_xy([row.stop_lon], [row.stop_lat])[0]
    if pt3310 is None:
        pt3310 = gpd.GeoSeries([pt4326], crs="EPSG:4326").to_crs("EPSG:3310").iloc[0]
    seg = street_at(pt3310) if with_street else None
    shapes, rtext = shapes_for(row.analysis_name, str(row.stop_id), pt4326)
    return {"ll": [round(float(row.stop_lat), 6), round(float(row.stop_lon), 6)],
            "ag": row.analysis_name, "sid": str(row.stop_id), "nm": row.stop_name,
            "routes": rtext, "shapes": shapes,
            "street": to_latlon_segs(geom3310=seg) if seg is not None else []}


HEAD = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
 body{margin:0;font:13px system-ui} #map{position:absolute;top:0;bottom:0;right:0;left:360px}
 #side{position:absolute;top:0;bottom:0;left:0;width:360px;overflow:auto;background:#111;color:#ddd;padding:10px;box-sizing:border-box}
 h1{font-size:14px;margin:4px 0} .sub{color:#999;font-size:11px;margin-bottom:8px}
 .row{padding:5px 6px;border-bottom:1px solid #222;cursor:pointer} .row:hover{background:#1d1d1d}
 .row b{color:#fff} .m{color:#8bd;font-size:11px}
 .pill{display:inline-block;background:#333;border-radius:3px;padding:0 5px;margin-left:4px;font-size:10px}
 .note{background:#1a2a1a;border:1px solid #2a4;border-radius:4px;padding:8px;font-size:12px;margin:8px 0;color:#cec}
 .sw{display:inline-block;width:18px;height:4px;vertical-align:middle;margin-right:5px}
 .arr{pointer-events:none} label{font-size:12px}
</style></head><body>"""

SAT = ("L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/"
       "MapServer/tile/{z}/{y}/{x}',{maxZoom:21,maxNativeZoom:19,attribution:'Esri'})")

ARROW_JS = """
function addArrows(latlngs, color, layer, near){
  // one arrow every ~70 m of LINE LENGTH (vertex-based spacing fails on
  // straight simplified lines, which have almost no vertices)
  const n = latlngs.length; if (n < 2) return;
  const mx = Math.cos(latlngs[0][0]*Math.PI/180)*111320, my = 110540;
  const cum = [0];
  for (let i = 1; i < n; i++) {
    const dx = (latlngs[i][1]-latlngs[i-1][1])*mx, dy = (latlngs[i][0]-latlngs[i-1][0])*my;
    cum.push(cum[i-1] + Math.hypot(dx, dy));
  }
  const total = cum[n-1]; if (total < 8) return;
  for (let t = Math.min(35, total/2); t < total; t += 70) {
    let i = 1; while (i < n-1 && cum[i] < t) i++;
    const f = (t - cum[i-1]) / Math.max(cum[i]-cum[i-1], 1e-9);
    const lat = latlngs[i-1][0] + f*(latlngs[i][0]-latlngs[i-1][0]);
    const lon = latlngs[i-1][1] + f*(latlngs[i][1]-latlngs[i-1][1]);
    const dx = (latlngs[i][1]-latlngs[i-1][1])*mx, dy = (latlngs[i][0]-latlngs[i-1][0])*my;
    const brg = Math.atan2(dx, dy)*180/Math.PI;
    L.marker([lat, lon], {interactive:false, icon:L.divIcon({className:'arr',
      iconSize:[16,16], html:`<div style="transform:rotate(${brg-90}deg);color:${color};font-size:15px;text-shadow:0 0 3px #000">➤</div>`})}).addTo(layer);
  }
}
"""

OSM_COL = "#ffffff"
LEGEND = f"""<div class="sub">
  <b>dot fill + outline + route shapes = PROPOSED group</b> (same fill = stays together);
  <b>dot RING = agency</b>. Arrows = travel direction; route labels show physical
  heading (&rarr;N/S/E/W) at the stop.<br>
  <span class="sw" style="background:{OSM_COL};border:1px solid #666"></span>nearest OSM street centerline (split-detector evidence, dashed)<br>
  <span class="dot" style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#e77;border:2px solid #fff;margin-right:5px;vertical-align:middle"></span>nearby ungrouped stop — agency fill, white ring
 </div>"""

# ------------------------------------------------- build per-GROUP structures
kp = {}        # constraint-grade: CONFIRM/across verdicts with FULL shape coverage
kp_any = {}    # any adjudicated pair: keeps the group marked for review
for r in pairs.itertuples():
    pair = ((r.a_agency, r.a_stop), (r.b_agency, r.b_stop))
    kp_any.setdefault(r.cluster_id, []).append(pair)
    v = str(getattr(r, "verdict", "") or "")
    full = str(getattr(r, "coverage", "full") or "full") == "full"
    if full and v.startswith("CONFIRM"):   # across-street is review-only
        kp.setdefault(r.cluster_id, []).append(pair)

# ALL grouping candidates: every multi-agency group, plus any kitty-flagged group
cand_cids = sorted(set(df[df.n_agencies >= 2].cluster_id) | set(kp_any))
print(f"{len(cand_cids):,} candidate groups ({len(kp)} with kitty-corner flags)")


def _cidhash(cid):
    h = 0
    for ch in cid:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h


groups = []
for cid in cand_cids:
    plist = kp.get(cid, [])
    mem_rows = df[df.cluster_id == cid]
    pts3310 = gpd.GeoSeries(
        gpd.points_from_xy(mem_rows.stop_lon, mem_rows.stop_lat),
        crs="EPSG:4326").to_crs("EPSG:3310")
    members = [member_bundle(r, pt3310=pts3310.iloc[i], with_street=cid in kp_any)
               for i, r in enumerate(mem_rows.itertuples())]
    # members often share routes: draw each (label, segment) once per group
    seen_segs = set()
    for m in members:
        kept = []
        for sh in m["shapes"]:
            key = (sh["label"], tuple(sh["coords"][0]), tuple(sh["coords"][-1]), len(sh["coords"]))
            if key not in seen_segs:
                seen_segs.add(key)
                kept.append(sh)
        m["shapes"] = kept
    subs = propose_split(members, plist) if plist else [0] * len(members)
    base = _cidhash(cid)
    for m, s in zip(members, subs):
        m["sub"] = s
        m["ci"] = (base + s) % 6
    bnd = pts3310.total_bounds
    g = {"cid": cid, "zones": subgroup_zones(cid, members, subs),
         "nag": int(mem_rows.analysis_name.nunique()),
         "n": len(members), "k": len(set(subs)),
         "span": round(float(math.hypot(bnd[2] - bnd[0], bnd[3] - bnd[1])), 1),
         "flag": cid in kp_any, "members": members,
         "ll": [round(mem_rows.stop_lat.mean(), 6), round(mem_rows.stop_lon.mean(), 6)]}
    for z in g["zones"]:
        z["ci"] = (base + z["sub"]) % 6
    pad = 0.0010   # ~110 m: nearby stops NOT in any drawn candidate group, for context
    near = df[df.stop_lat.between(mem_rows.stop_lat.min() - pad, mem_rows.stop_lat.max() + pad)
              & df.stop_lon.between(mem_rows.stop_lon.min() - pad, mem_rows.stop_lon.max() + pad)
              & (df.cluster_id != cid) & (df.n_agencies < 2)]
    g["ctx"] = [{"ll": [round(float(r.stop_lat), 6), round(float(r.stop_lon), 6)],
                 "nm": r.stop_name, "ag": r.analysis_name, "sid": str(r.stop_id),
                 "cid": r.cluster_id} for r in near.itertuples()]
    groups.append(g)
    if len(groups) % 500 == 0:
        print(f"  {len(groups):,} groups built...")
print(f"{len(groups):,} groups")

PAL = ['#00e5ff', '#ffb300', '#7cfc00', '#ff7ad9', '#b39dff', '#ffe97f']

n_flag = sum(1 for g in groups if g["flag"])
html2 = HEAD + f"""
<div id="side">
 <h1>Stop-grouping candidates</h1>
 <div class="sub">All {len(groups):,} multi-agency grouping candidates. {n_flag} carry a
 kitty-corner split proposal (dot colors split within the outline); the rest are drawn as
 proposed as-is. Route labels show the physical heading at the stop (→N/S/E/W) — dir0/dir1
 are arbitrary per feed.</div>
 {LEGEND}
 <label><input type="checkbox" id="monly"> multi-agency only</label>
 <div style="margin-top:6px"><label>show
   <select id="cx" style="background:#222;color:#ddd;border:1px solid #444">
     <option value="all">all groups</option>
     <option value="busy">busy &mdash; &ge;3 agencies or &ge;6 stops</option>
     <option value="complex">complex &mdash; &ge;4 agencies, &ge;10 stops or &ge;60 m span</option>
     <option value="splits">&#9873; proposed splits only</option>
   </select></label></div>
 <div style="margin-top:6px"><label>agency
   <select id="ag" style="background:#222;color:#ddd;border:1px solid #444;max-width:320px">
     <option value="">all agencies</option>
   </select></label></div>
 <div class="sub" id="count"></div>
 <div id="list"></div>
</div>
<div id="map"></div><script>
const G = {json.dumps(groups)};
const PAL = {json.dumps(PAL)};
const map = L.map('map', {{preferCanvas:true}}).setView([36.8,-119.4], 6);
{SAT}.addTo(map);
{ARROW_JS}
const layer = L.layerGroup().addTo(map);
function esc(s){{return (''+s).replace(/[&<>]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c]));}}
function agColor(ag){{ let h=0; for(const ch of (ag||'')) h=(h*31+ch.charCodeAt(0))>>>0;
  return `hsl(${{h%360}},72%,62%)`; }}
const TIERS = {{all: g=>true, busy: g=>g.flag||g.nag>=3||g.n>=6,
  complex: g=>g.flag||g.nag>=4||g.n>=10||(g.span||0)>=60, splits: g=>g.flag}};
function shown(){{ const m=document.getElementById('monly').checked;
  const t=TIERS[document.getElementById('cx').value];
  const a=document.getElementById('ag').value;
  return G.filter(g=>(!m||g.nag>=2)&&t(g)&&(!a||g.ags.includes(a))); }}
function draw(){{
  layer.clearLayers();
  const close = map.getZoom() >= 15;
  const b0 = map.getBounds();   // fixed ~450 m margin: % padding shrinks to nothing at high zoom
  const vb = L.latLngBounds([b0.getSouth()-0.004, b0.getWest()-0.005],
                            [b0.getNorth()+0.004, b0.getEast()+0.005]);
  for (const g of shown()) {{
    if (close && !vb.contains(L.latLng(g.ll))) continue;   // viewport culling
    if (!close) {{
      L.circleMarker(g.ll, {{radius:4, color:'#000', weight:1,
          fillColor: g.flag ? '#ff3333' : '#ffd400', fillOpacity:.9}})
        .bindTooltip(`group ${{g.cid}}: ${{g.n}} stops` + (g.flag?` → ${{g.k}} proposed`:'')).addTo(layer);
      continue;
    }}
    for (const z of g.zones)
      for (const ring of z.rings)
        L.polygon(ring, {{color:PAL[z.ci], weight:2.5,
                          fillColor:PAL[z.ci], fillOpacity:.10}})
          .bindTooltip(g.flag ? `proposed group ${{z.sub+1}} of ${{g.k}} (splitting today's ${{g.cid}})`
                              : `group ${{g.cid}} (proposed as-is)`).addTo(layer);
    for (const m of g.members) {{
      const col = PAL[m.ci];
      const popup = `<b>${{esc(m.nm)}}</b><br>${{esc(m.ag)}} · stop_id ${{m.sid}}<br>
        routes: ${{esc(m.routes)||'(unknown)'}}<br>
        group ${{esc(g.cid)}}: ${{g.n}} stops` +
        (g.flag ? ` → <b>proposed sub-group ${{m.sub+1}} of ${{g.k}}</b>` : ' (proposed as-is)');
      for (const seg of m.street)
        L.polyline(seg, {{color:'{OSM_COL}', weight:2, opacity:.55, dashArray:'6 6'}}).bindPopup(popup).addTo(layer);
      for (const sh of m.shapes) {{
        L.polyline(sh.coords, {{color:col, weight:4, opacity:.9}})
          .bindTooltip(`${{m.sid}} route ${{sh.label}}`).bindPopup(popup).addTo(layer);
        addArrows(sh.coords, col, layer, m.ll);
      }}
      L.circleMarker(m.ll, {{radius:7, color:agColor(m.ag), weight:3.5, fillColor:col, fillOpacity:1}})
        .bindPopup(popup).addTo(layer);
    }}
    for (const c of g.ctx)
      L.circleMarker(c.ll, {{radius:6, color:'#fff', weight:2, fillColor:agColor(c.ag), fillOpacity:.95}})
        .bindPopup(`<b>${{esc(c.nm)}}</b><br>${{esc(c.ag)}} · stop_id ${{c.sid}}<br>
          <i>not in this group</i> — its own group: ${{esc(c.cid)}}`)
        .bindTooltip(`${{esc(c.ag)}} — not grouped with these`).addTo(layer);
  }}
  const csn = shown();
  document.getElementById('count').textContent =
    csn.length.toLocaleString() + ' groups shown' + (close ? '' : ' — zoom in (or click a row) for detail');
  const list = document.getElementById('list'); list.innerHTML='';
  csn.slice().sort((x,y)=> (y.flag-x.flag) || (y.nag-x.nag) || (y.n-x.n) || (y.span-x.span))
     .slice(0,400).forEach(g=>{{
    const d = document.createElement('div'); d.className='row';
    d.innerHTML = `<b>${{g.n}} stops${{g.flag?` → ${{g.k}}`:''}}</b>
      <span class="pill">${{g.nag}} ag</span><span class="pill">${{g.span}} m</span>${{g.flag?'<span class="pill" style="background:#611;color:#faa">split?</span>':''}}
      <div class="m">${{esc(g.members[0].nm)}}</div>`;
    d.onclick = ()=> map.setView(g.ll, 19);
    list.appendChild(d);
  }});
}}
for(const g of G) g.ags = [...new Set(g.members.map(m=>m.ag))];
const AGC = {{}};
for(const g of G) for(const a of g.ags) AGC[a]=(AGC[a]||0)+1;
const agSel = document.getElementById('ag');
for(const a of Object.keys(AGC).sort((x,y)=>x.localeCompare(y))){{
  const o=document.createElement('option'); o.value=a;
  o.textContent=`${{a}} (${{AGC[a].toLocaleString()}})`; agSel.appendChild(o);
}}
for(const [k,fn] of Object.entries(TIERS))
  document.querySelector(`#cx option[value="${{k}}"]`).textContent +=
    ` (${{G.filter(fn).length.toLocaleString()}})`;
document.getElementById('monly').onchange = draw;
document.getElementById('cx').onchange = draw;
agSel.onchange = ()=>{{
  draw();
  if(agSel.value){{
    const cs = shown();
    if(cs.length) map.fitBounds(L.latLngBounds(cs.map(g=>g.ll)).pad(0.2));
  }}
}};
map.on('zoomend', draw);
map.on('moveend', draw);
draw();
</script></body></html>"""
(REPO / "data" / "grouping_candidates_map.html").write_text(html2)
print("wrote data/grouping_candidates_map.html")

# ---------------------------------------------------------------- Evan's map
evan_groups = []
for cid in ("1442_r0", "1442_r1", "1442_r2"):
    mem_rows = df[df.cluster_id == cid]
    members = [member_bundle(r) for r in mem_rows.itertuples()]
    if cid == "1442_r2":   # crossed-name pair as the cannot-link
        subs = propose_split(members, [
            (("City and County of San Francisco", "13326"),
             ("City and County of San Francisco", "14314"))])
    else:
        subs = [0] * len(members)
    for m, s in zip(members, subs):
        m["sub"] = s
    evan_groups.append({"cid": cid, "zones": subgroup_zones(cid, members, subs),
                        "members": members, "k": len(set(subs))})

lat0 = float(df[df.cluster_id == "1442_r2"].stop_lat.mean())
lon0 = float(df[df.cluster_id == "1442_r2"].stop_lon.mean())
html1 = HEAD + f"""
<div id="side">
 <h1>Evan's case — 18th St &amp; Castro St, SF</h1>
 <div class="sub">benchmark "should NOT match": Muni 13326 vs 14314</div>
 <div class="note"><b>Today 13326 + 14314 are one group</b> (1442_r2, 8.2 m apart). The two
 colored outlines are the <b>proposed</b> registry stops after the split — crossed names +
 route shapes say they board on different streets. Blue outlines = neighboring groups
 (inbound/outbound pairs that already separated), unchanged.</div>
 {LEGEND}
</div>
<div id="map"></div><script>
const G = {json.dumps(evan_groups)};
const PAL = {json.dumps(PAL)};
const map = L.map('map').setView([{lat0},{lon0}], 19);
{SAT}.addTo(map);
{ARROW_JS}
for (const g of G) {{
  for (const z of g.zones) {{
    const zc = g.cid === '1442_r2' ? PAL[z.sub % PAL.length] : '#4da3ff';
    for (const ring of z.rings)
      L.polygon(ring, {{color:zc, weight:2.5, fillColor:zc, fillOpacity:.10}})
        .bindTooltip(g.cid === '1442_r2'
          ? `proposed group ${{z.sub+1}} of ${{g.k}} (splitting ${{g.cid}})`
          : `group ${{g.cid}} (unchanged)`).addTo(map);
  }}
  for (const m of g.members) {{
    const col = g.cid === '1442_r2' ? PAL[m.sub % PAL.length] : '#4da3ff';
    const popup = `<b>${{m.nm}}</b><br>stop_id ${{m.sid}}<br>routes: ${{m.routes}}<br>group ${{g.cid}}`;
    for (const seg of m.street)
      L.polyline(seg, {{color:'{OSM_COL}', weight:2, opacity:.55, dashArray:'6 6'}}).addTo(map);
    for (const sh of m.shapes) {{
      L.polyline(sh.coords, {{color:col, weight:4, opacity:.9}})
        .bindTooltip(`${{m.sid}} route ${{sh.label}}`).addTo(map);
      addArrows(sh.coords, col, map, m.ll);
    }}
    L.circleMarker(m.ll, {{radius:8, color:'#000', weight:1.5, fillColor:col, fillOpacity:1}})
      .bindPopup(popup)
      .bindTooltip(m.nm, {{permanent: g.cid==='1442_r2', direction:'top', offset:[0,-8], opacity:.85}})
      .addTo(map);
  }}
}}
</script></body></html>"""
(REPO / "data" / "evans_case_map.html").write_text(html1)
print("wrote data/evans_case_map.html")
