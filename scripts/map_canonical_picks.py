"""
Inspect groupings + the suggested primary stop on a satellite map.

Reads a canonicalizer output CSV (cluster_id / is_canonical / score / features)
and renders a self-contained Leaflet HTML: every multi-agency grouping is drawn
as an outline around its member stops, with all original agency stops shown and
the one picked as the **suggested primary** highlighted — over Esri satellite
imagery. A sidebar lists the most-shared groupings; click to fly there. Popups
show why each pick was made (score, confidence, in_roadway, dist-to-road).

  uv run scripts/map_canonical_picks.py --input <canonicalizer_stops.csv>
  uv run scripts/map_canonical_picks.py --min-agencies 3        # only the pile-ups
  uv run scripts/map_canonical_picks.py --include-single-agency # also same-agency multi-stop groups

Default input: newest data/canonicalizer_stops_*.csv (falls back to the atlas copy).
"""

import argparse
import json
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import MultiPoint, MultiPolygon, Point, box
from shapely.ops import unary_union, voronoi_diagram
from shapely.strtree import STRtree

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
ATLAS_FALLBACK = Path.home() / "github/transit-amenity-atlas/data"

# Major-station cluster types to drop by default (handed to the operating agency,
# not the street-corner grouping work we're inspecting).
MAJOR_TYPES = {"STATION_COMPLEX", "AMBIGUOUS_LARGE"}
CA_ALBERS = "EPSG:3310"  # statewide equal-distance projection (meters)


def find_input() -> Path:
    for d in (DATA_DIR, ATLAS_FALLBACK):
        hits = sorted(d.glob("canonicalizer_stops_*.csv"))
        if hits:
            return hits[-1]
    raise SystemExit("No canonicalizer_stops_*.csv found (run the canonicalizer first).")


def stat(v):
    """JSON-safe stat scalar (NOT coordinates): NaN/inf -> None, round to 3."""
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 3)
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def coord(v):
    """Coordinate -> full stop-level precision (6 decimals ~ 0.1 m). Never 3."""
    return round(float(v), 6)


def _rings(geom):
    """(Multi)Polygon -> list of exterior rings as [[lat,lon]...]."""
    if geom is None or geom.is_empty:
        return []
    polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    return [[[round(y, 7), round(x, 7)] for x, y in p.exterior.coords] for p in polys]


def compute_zones(df_all: pd.DataFrame, render_ids: set, max_m: float) -> dict:
    """Voronoi grouping zones. Every point of space belongs to its nearest stop;
    a group's zone is the union of its members' Voronoi cells — CONNECTED within a
    group (adjacent members share cell edges) and DISJOINT between groups (cells
    share only borders, never overlap). Each cell is clipped to a max radius so an
    isolated stop doesn't sprawl into empty space. Returns {cluster_id: [rings]}.
    """
    g = gpd.GeoDataFrame(
        df_all, geometry=gpd.points_from_xy(df_all["stop_lon"], df_all["stop_lat"]),
        crs="EPSG:4326").to_crs(CA_ALBERS)
    xs, ys = g.geometry.x.to_numpy(), g.geometry.y.to_numpy()
    cid = df_all["cluster_id"].to_numpy()
    pts = [Point(x, y) for x, y in zip(xs, ys)]

    env = box(xs.min() - 1000, ys.min() - 1000, xs.max() + 1000, ys.max() + 1000)
    cells = list(voronoi_diagram(MultiPoint(pts), envelope=env).geoms)
    ctree = STRtree(cells)

    # Collect each group's full Voronoi cells + member points. We dissolve cells
    # per group, THEN clip to the member-buffer bound — so the shared edges with
    # neighboring groups stay the exact Voronoi edges (no per-stop clip slivers),
    # groups stay disjoint (their Voronoi parts never overlap), and the zone stays
    # connected (shared edges aren't eroded).
    by_cells: dict = {}
    by_pts: dict = {}
    for i in np.where(np.isin(cid, list(render_ids)))[0]:
        p, k = pts[i], cid[i]
        by_pts.setdefault(k, []).append(p)
        cell = next((cells[jc] for jc in ctree.query(p) if cells[jc].covers(p)), None)
        if cell is not None:
            by_cells.setdefault(k, []).append(cell)

    ids = list(by_pts)
    geoms = []
    for k in ids:
        bound = unary_union([p.buffer(max_m) for p in by_pts[k]])
        cl = by_cells.get(k)
        geoms.append(unary_union(cl).intersection(bound) if cl else bound)

    # Painter's pass: carve each zone out of the zones already placed, so the
    # rendered zones are STRICTLY disjoint (the later zone cedes the shared sliver)
    # while their borders still coincide. Connectivity-safe — only thin border
    # slivers from GEOS Voronoi edge precision are removed.
    gtree = STRtree(geoms)
    placed: list = []
    for i, z in enumerate(geoms):
        prior = [placed[j] for j in gtree.query(z)
                 if j < i and not placed[j].is_empty and placed[j].intersects(z)]
        placed.append(z.difference(unary_union(prior)) if prior else z)
    gs = gpd.GeoSeries(placed, crs=CA_ALBERS).to_crs("EPSG:4326")
    return {k: geom for k, geom in zip(ids, gs)}


def write_gis(clusters: list, zone_geoms: dict, out_html: Path) -> None:
    """Write the rendered groupings as GIS layers next to the HTML: zone polygons
    and member stop points, each as FlatGeobuf (QGIS/ArcGIS) and GeoJSON."""
    stem = out_html.with_suffix("")
    zrows = []
    for c in clusters:
        g = zone_geoms.get(c["id"])
        if g is None or g.is_empty:
            continue
        zrows.append({
            "cluster_id": c["id"], "n_agencies": c["n_agencies"], "n_stops": c["n_stops"],
            "cluster_type": c["type"], "review": c["review"], "has_parent": c["has_parent"],
            "span_m": c["span"], "method": c["method"],
            "geometry": g if g.geom_type == "MultiPolygon" else MultiPolygon([g]),
        })
    srows = []
    for c in clusters:
        for m in c["members"]:
            srows.append({
                "cluster_id": c["id"], "agency": m["agency"], "feed": m["feed"],
                "stop_id": m["sid"], "stop_name": m["name"], "is_canonical": m["canon"],
                "in_roadway": m["in_road"], "dist_to_road_m": m["road"], "score": m["score"],
                "route_dirs": m["rdir"], "location_type": m["ltype"],
                "parent_station": m["parent"], "review": c["review"],
                "geometry": Point(m["lon"], m["lat"]),
            })
    for name, rows in (("zones", zrows), ("stops", srows)):
        gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
        for ext, drv in (("fgb", "FlatGeobuf"), ("geojson", "GeoJSON")):
            path = Path(f"{stem}_{name}.{ext}")
            gdf.to_file(path, driver=drv)
            print(f"  {name:5} {ext:8} -> {path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, help="canonicalizer output CSV")
    ap.add_argument("--output", type=Path, default=DATA_DIR / "canonical_picks_map.html")
    ap.add_argument("--min-agencies", type=int, default=2,
                    help="only groupings with >= this many distinct agencies (default 2)")
    ap.add_argument("--include-single-agency", action="store_true",
                    help="also include same-agency multi-stop groupings")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap number of groupings rendered (0 = all); most-shared first")
    ap.add_argument("--zone-max-m", type=float, default=25.0,
                    help="max Voronoi-cell radius (m); cells are disjoint with shared borders, "
                         "clipped to this so isolated stops don't sprawl")
    ap.add_argument("--include-stations", action="store_true",
                    help="include major-station / large-ambiguous clusters (excluded by default)")
    args = ap.parse_args()

    src = args.input or find_input()
    df = pd.read_csv(src, dtype={"stop_id": str, "stop_code": str}, low_memory=False)
    print(f"{len(df):,} stops / {df['cluster_id'].nunique():,} clusters from {src.name}")

    df = df.dropna(subset=["stop_lat", "stop_lon", "cluster_id"])

    # Agency count per group on the FULL membership, BEFORE the marker dedup below.
    # Otherwise a group whose agencies sit at one coordinate collapses to a single
    # record and wrongly drops out of the multi-agency view (the "439 hidden" bug).
    nag_full = df.groupby("cluster_id")["analysis_name"].nunique()
    size_full = df.groupby("cluster_id")["stop_id"].size()

    # Dedup exact-coincident points for MARKER display only (don't stack identical
    # markers); the full counts above are preserved.
    df["_rlat"] = df["stop_lat"].round(6)
    df["_rlon"] = df["stop_lon"].round(6)
    df["_has_name"] = df["analysis_name"].notna()
    before = len(df)
    df = (df.sort_values(["is_canonical", "_has_name"], ascending=False)
            .drop_duplicates(["cluster_id", "_rlat", "_rlon"], keep="first"))
    print(f"  deduped {before - len(df):,} coincident markers (membership counts preserved)")

    df["_nag"] = df["cluster_id"].map(nag_full)
    if args.include_single_agency:
        keep = df["cluster_id"].map(size_full) >= 2
    else:
        keep = df["_nag"] >= args.min_agencies
    sub = df[keep].copy()

    clusters = []
    for cid, g in sub.groupby("cluster_id"):
        canon_rows = g[g["is_canonical"] == True]  # noqa: E712
        has_pick = len(canon_rows) > 0
        canon = (canon_rows.iloc[0] if has_pick
                 else g.loc[g["score"].idxmax()] if g["score"].notna().any()
                 else g.iloc[0])
        ctype = canon.get("cluster_type")
        # parent/child structure present? (GTFS location_type 1/2 or a parent_station set)
        lt = pd.to_numeric(g["location_type"], errors="coerce") if "location_type" in g else None
        has_station = bool(lt.isin([1, 2]).any()) if lt is not None else False
        has_parent = bool(g["parent_station"].notna().any()) if "parent_station" in g else False
        # review-later bucket: large/ambiguous or station complexes, or no clear pick.
        # We don't pick a primary for these — a human resolves them.
        review = (ctype in MAJOR_TYPES) or (not has_pick)

        def row(r):
            ag = r.get("analysis_name")
            return {
                "lat": coord(r["stop_lat"]), "lon": coord(r["stop_lon"]),
                "agency": ag if pd.notna(ag) else "(unlabeled feed)", "feed": r.get("feed_name"),
                "name": r.get("stop_name"), "sid": r.get("stop_id"),
                "code": stat(r.get("stop_code")),
                "score": stat(r.get("score")), "conf": stat(r.get("confidence")),
                "road": stat(r.get("dist_to_road_meters")),
                "in_road": bool(r.get("in_roadway")) if pd.notna(r.get("in_roadway")) else None,
                "ltype": stat(r.get("location_type")),
                "parent": r.get("parent_station") if pd.notna(r.get("parent_station")) else None,
                "rdir": r.get("route_dirs") if pd.notna(r.get("route_dirs")) else None,
                "canon": bool(r["is_canonical"]),
            }

        members = [row(r) for _, r in g.iterrows()]
        clusters.append({
            "id": str(cid),
            "type": ctype,
            "method": canon.get("canonicalization_method"),
            "span": stat(canon.get("cluster_span_meters")),
            "n_agencies": int(nag_full.get(cid, g["analysis_name"].nunique())),
            "n_stops": int(size_full.get(cid, len(g))),
            "has_pick": has_pick and not review,
            "review": review,
            "has_parent": has_parent or has_station,
            "primary": {"lat": coord(canon["stop_lat"]), "lon": coord(canon["stop_lon"])},
            "members": members,
        })

    clusters.sort(key=lambda c: (c["n_agencies"], c["n_stops"], c["span"] or 0), reverse=True)
    if args.limit:
        clusters = clusters[:args.limit]

    # disjoint zones (capped at half the gap to the nearest other-group stop)
    render_ids = {c["id"] for c in clusters}
    zone_geoms = compute_zones(df, render_ids, args.zone_max_m)
    for c in clusters:
        g = zone_geoms.get(c["id"])
        c["hulls"] = _rings(g) if g is not None else []

    n_pts = sum(c["n_stops"] for c in clusters)
    n_review = sum(1 for c in clusters if c["review"])
    tag = "multi-agency groupings"
    print(f"  rendering {len(clusters):,} {tag} / {n_pts:,} stops "
          f"({n_review:,} flagged for review)")

    html = _HTML.replace("__DATA__", json.dumps(clusters, separators=(",", ":")))
    html = html.replace("__TITLE__", f"{len(clusters):,} {tag} · {n_review:,} to review · {src.name}")
    args.output.write_text(html)
    print(f"  HTML       -> {args.output}")
    write_gis(clusters, zone_geoms, args.output)


_HTML = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Groupings &amp; primary stop</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html,body{margin:0;height:100%;font:13px/1.4 system-ui,sans-serif}
  #map{position:absolute;left:320px;right:0;top:0;bottom:0}
  #side{position:absolute;left:0;top:0;bottom:0;width:320px;overflow:auto;
        background:#111;color:#ddd;box-sizing:border-box;padding:10px}
  #side h1{font-size:14px;margin:4px 0 2px}
  #side .sub{color:#888;font-size:11px;margin-bottom:8px}
  .leg{font-size:11px;color:#bbb;margin:6px 0;border-top:1px solid #333;padding-top:6px}
  .leg b{color:#fff}
  .dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:middle}
  .row{padding:5px 6px;border-bottom:1px solid #222;cursor:pointer}
  .row:hover{background:#1d1d1d}
  .row b{color:#fff}
  .row .m{color:#8bd;font-size:11px}
  .pill{display:inline-block;background:#333;border-radius:3px;padding:0 5px;margin-left:4px;font-size:10px;color:#ccc}
  .popup b{color:#000}
  .popup .k{color:#666;display:inline-block;min-width:74px}
  .primbadge{background:#ffd400;color:#000;font-weight:bold;border-radius:3px;padding:0 4px}
  .rvbadge{background:#ff8c00;color:#000;font-weight:bold;border-radius:3px;padding:0 4px}
  input{vertical-align:middle}
</style></head><body>
<div id="side">
  <h1>Groupings &amp; suggested primary</h1>
  <div class="sub">__TITLE__</div>
  <label><input type="checkbox" id="outlines" checked> outlines</label>
  &nbsp;<label><input type="checkbox" id="sat" checked> satellite</label>
  &nbsp;<label><input type="checkbox" id="spokes"> spokes</label>
  <div class="leg">
    <span class="dot" style="background:#ffd400;border:1px solid #000;width:14px;height:14px"></span> <b>suggested primary stop</b><br>
    <span class="dot" style="background:#4da3ff"></span> original agency stop<br>
    <span class="dot" style="background:#ff5b5b;border:1px solid #fff"></span> original stop in roadway (penalized)<br>
    <span style="display:inline-block;width:12px;height:10px;border:1.5px solid #ffd400;background:rgba(255,212,0,.12);vertical-align:middle;margin-right:5px"></span> grouping outline<br>
    <span style="display:inline-block;width:12px;height:10px;border:1.5px solid #ff8c00;background:rgba(255,140,0,.12);vertical-align:middle;margin-right:5px"></span> <b style="color:#ff8c00">⚑ review later</b> (large/ambiguous or no clear pick — human resolves)
  </div>
  <div class="leg">Top groupings (most agencies first):</div>
  <div id="list"></div>
</div>
<div id="map"></div>
<script>
const CL = __DATA__;
const map = L.map('map', {preferCanvas:true}).setView([36.8,-119.4], 6);
const sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  {maxZoom:21, maxNativeZoom:19, attribution:'Esri'}).addTo(map);
const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:19, attribution:'OSM'});
const hullLayer = L.layerGroup().addTo(map);
const spokeLayer = L.layerGroup().addTo(map);
const ptLayer = L.layerGroup().addTo(map);

function esc(s){return (s==null?'':(''+s)).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function popup(m, c){
  const f = (k,v)=> v==null?'':`<div><span class="k">${k}</span> ${esc(v)}</div>`;
  return `<div class="popup">
    ${(m.canon&&c.has_pick)?'<div class="primbadge">SUGGESTED PRIMARY</div>':''}
    ${c.review?('<div class="rvbadge">⚑ REVIEW LATER'+(c.has_parent?' — check parent/child structure':'')+'</div>'):''}
    <b>${esc(m.name)||'(no name)'}</b><br>
    ${f('agency', m.agency)}${f('feed', m.feed)}
    ${f('stop_id', m.sid)}${f('stop_code', m.code)}
    ${f('score', m.score)}${f('confidence', m.conf)}
    ${f('dist→road', m.road==null?null:m.road+' m')}
    ${m.in_road?'<div style="color:#b00">in roadway</div>':''}
    ${f('location_type', m.ltype)}${f('parent_station', m.parent)}
    ${f('route|dir', m.rdir)}
    <hr style="border:none;border-top:1px solid #ddd">
    <div class="k">grouping</div> ${esc(c.id)} · ${esc(c.type)}${c.has_parent?' · has parent/child':''}<br>
    ${c.n_agencies} agencies / ${c.n_stops} stops · span ${c.span==null?'?':c.span+' m'} · ${esc(c.method)}
  </div>`;
}
function draw(){
  hullLayer.clearLayers(); spokeLayer.clearLayers(); ptLayer.clearLayers();
  const showOutlines = document.getElementById('outlines').checked;
  const showSpokes = document.getElementById('spokes').checked;
  for(const c of CL){
    const col = c.review ? '#ff8c00' : (c.has_pick ? '#ffd400' : '#bbbbbb');
    if(showOutlines && c.hulls)
      for(const ring of c.hulls)
        L.polygon(ring, {color:col, weight:1.5, opacity:.9, fillColor:col, fillOpacity:.12}).addTo(hullLayer);
    const p = c.primary;
    for(const m of c.members){
      const isPrim = m.canon && c.has_pick;
      if(showSpokes && !isPrim)
        L.polyline([[p.lat,p.lon],[m.lat,m.lon]], {color:col,weight:1,opacity:.4}).addTo(spokeLayer);
      if(!isPrim)
        L.circleMarker([m.lat,m.lon], {radius:4, color: m.in_road?'#fff':'#1a4a7a',
          weight:1, fillColor: m.in_road?'#ff5b5b':'#4da3ff', fillOpacity:.95})
          .bindPopup(popup(m,c)).addTo(ptLayer);
    }
    if(c.has_pick)
      L.circleMarker([p.lat,p.lon], {radius:8, color:'#000', weight:2,
        fillColor:'#ffd400', fillOpacity:1})
        .bindPopup(popup(c.members.find(x=>x.canon)||c.members[0], c)).addTo(ptLayer);
  }
}
draw();
for(const id of ['outlines','spokes']) document.getElementById(id).onchange = draw;
document.getElementById('sat').onchange = e => {
  if(e.target.checked){ map.removeLayer(osm); sat.addTo(map); }
  else { map.removeLayer(sat); osm.addTo(map); }
};

const list = document.getElementById('list');
CL.slice(0,300).forEach(c=>{
  const d = document.createElement('div'); d.className='row';
  const names = [...new Set(c.members.map(m=>m.agency))].filter(n=>n&&n!=='(unlabeled feed)').slice(0,4).join(', ');
  d.innerHTML = `<b>${c.n_agencies} agencies</b><span class="pill">${esc(c.type||'')}</span>
    <span class="pill">${c.n_stops} stops</span>${c.review?'<span class="pill" style="background:#7a4a00;color:#fd9">⚑ review</span>':''}${c.has_parent?'<span class="pill" style="background:#245">parent/child</span>':''}
    <div class="m">${esc(names)}</div>`;
  d.onclick = ()=> map.setView([c.primary.lat,c.primary.lon], 19);
  list.appendChild(d);
});
</script></body></html>"""


if __name__ == "__main__":
    main()
