"""
Build a self-contained Leaflet HTML map of the multi-agency shared stops from
find_shared_stops.py, highlighting the multi-agency-ness: each shared geohash
cell is drawn as its actual cell rectangle, color-graded by how many agencies
share it (2 = amber up to 5+ = magenta), with the stops inside colored by
agency. Clicking a stop or cell lists the agencies sharing it. Aerial (Esri) +
OSM basemaps, a sidebar of the most-shared cells to fly between. No server —
just open the file.

  uv run scripts/map_shared_stops.py
  uv run scripts/map_shared_stops.py --min-agencies 3   # only the busier cells
"""

import argparse
import json
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"

PALETTE = [
    "#e6194B", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4", "#f032e6",
    "#bfef45", "#fabed4", "#469990", "#9A6324", "#800000", "#808000", "#000075",
    "#e6beff", "#ff8c00", "#1e90ff", "#dc143c", "#00ced1", "#8b4513",
]

GRADE = {2: "#ffd21f", 3: "#ff8c00", 4: "#ff3b30"}  # 5+ handled below


def cell_bounds(gh: str) -> list:
    """Decode a geohash to its [lat_lo, lon_lo, lat_hi, lon_hi] bounding box."""
    lat_lo, lat_hi = -90.0, 90.0
    lon_lo, lon_hi = -180.0, 180.0
    even = True
    for ch in gh:
        for bit in (16, 8, 4, 2, 1):
            if even:
                mid = (lon_lo + lon_hi) / 2
                if _BASE32.index(ch) & bit:
                    lon_lo = mid
                else:
                    lon_hi = mid
            else:
                mid = (lat_lo + lat_hi) / 2
                if _BASE32.index(ch) & bit:
                    lat_lo = mid
                else:
                    lat_hi = mid
            even = not even
    return [round(lat_lo, 7), round(lon_lo, 7), round(lat_hi, 7), round(lon_hi, 7)]


def latest_csv() -> Path:
    c = sorted(DATA_DIR.glob("shared_stops_*.csv"))
    if not c:
        raise SystemExit("No data/shared_stops_*.csv — run find_shared_stops.py first.")
    return c[-1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, help="shared_stops CSV (default: newest in data/)")
    ap.add_argument("--min-agencies", type=int, default=2, help="only cells shared by >= this")
    ap.add_argument("--out", type=Path, default=DATA_DIR / "shared_stops_map.html")
    args = ap.parse_args()

    src = args.input or latest_csv()
    df = pd.read_csv(src, dtype={"stop_id": str})
    df = df[df["n_agencies"] >= args.min_agencies]
    df["stop_name"] = df["stop_name"].fillna("")

    colors = {a: PALETTE[i % len(PALETTE)] for i, a in enumerate(sorted(df["agency"].unique()))}

    cells = []
    for gh, g in df.groupby("geohash", sort=False):
        cells.append(
            {
                "gh": gh,
                "na": int(g["n_agencies"].iloc[0]),
                "b": cell_bounds(gh),
                "label": g["stop_name"].iloc[0] or gh,
                "stops": [
                    {
                        "lat": round(float(r.stop_lat), 6),
                        "lon": round(float(r.stop_lon), 6),
                        "a": r.agency,
                        "n": r.stop_name,
                        "i": r.stop_id,
                        "c": colors[r.agency],
                    }
                    for r in g.itertuples()
                ],
            }
        )
    cells.sort(key=lambda c: (-c["na"], -len(c["stops"])))

    dist = df.drop_duplicates("geohash")["n_agencies"].value_counts().sort_index()
    breakdown = " · ".join(f"{k} agencies: {v:,}" for k, v in dist.items())

    html = (
        _TEMPLATE
        .replace("__CELLS__", json.dumps(cells, separators=(",", ":")))
        .replace("__BREAKDOWN__", breakdown)
        .replace("__N__", f"{len(cells):,}")
        .replace("__NSTOPS__", f"{len(df):,}")
        .replace("__SRC__", src.name)
    )
    args.out.write_text(html)
    print(f"{len(cells):,} shared cells ({len(df):,} stops) -> {args.out}")


_TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Multi-agency shared stops</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
 html,body{margin:0;height:100%;font:13px/1.4 system-ui,sans-serif}
 #wrap{display:flex;height:100%}
 #side{width:300px;overflow:auto;border-right:1px solid #ddd;background:#fafafa}
 #side h1{font-size:14px;margin:10px 12px 4px}
 #side .sub{color:#666;margin:0 12px 8px;font-size:12px}
 .row{padding:6px 12px;border-top:1px solid #eee;cursor:pointer}
 .row:hover{background:#eef}
 .row .na{display:inline-block;min-width:16px;text-align:center;border-radius:8px;
          color:#fff;font-weight:600;padding:0 5px;margin-right:6px}
 .row small{color:#666}
 #map{flex:1}
 .leaflet-popup-content{font:13px/1.4 system-ui}
 .leaflet-popup-content .dot{display:inline-block;width:9px;height:9px;border-radius:50%;
          border:1px solid #333;margin-right:5px}
</style></head>
<body><div id="wrap">
<div id="side"><h1>Multi-agency shared stops</h1>
<div class="sub">__N__ geohash cells / __NSTOPS__ stops from __SRC__<br>__BREAKDOWN__<br>
Cell color = how many agencies share it; dot color = agency. Click a cell or stop for the agency list.</div>
<div id="list"></div></div>
<div id="map"></div></div>
<script>
const CELLS = __CELLS__;
const grade = na => na >= 5 ? '#b1006e' : na === 4 ? '#ff3b30' : na === 3 ? '#ff8c00' : '#ffd21f';
const map = L.map('map', {preferCanvas: true});
const esri = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:22,maxNativeZoom:19,attribution:'Esri World Imagery'});
const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap'});
esri.addTo(map);
L.control.layers({'Aerial (Esri)':esri,'OpenStreetMap':osm}).addTo(map);

function agencyList(c){
  return c.stops.map(s=>`<span class="dot" style="background:${s.c}"></span>${s.a} — ${s.n} <small>(${s.i})</small>`).join('<br>');
}
const b=[];
CELLS.forEach(c=>{
  const col = grade(c.na);
  L.rectangle([[c.b[0],c.b[1]],[c.b[2],c.b[3]]],{color:col,weight:2,fillColor:col,fillOpacity:.15})
    .bindPopup(`<b>${c.na} agencies share this cell</b> <small>(${c.gh})</small><br>${agencyList(c)}`).addTo(map);
  c.stops.forEach(s=>{
    L.circleMarker([s.lat,s.lon],{radius:5,color:'#222',weight:1,fillColor:s.c,fillOpacity:.95})
      .bindPopup(`<b>${s.a}</b><br>${s.n} <small>(${s.i})</small><br><br>`+
                 `<b>${c.na} agencies share this cell:</b><br>${agencyList(c)}`).addTo(map);
    b.push([s.lat,s.lon]);
  });
});
map.fitBounds(b);
const list=document.getElementById('list');
CELLS.slice(0,300).forEach(c=>{
  const d=document.createElement('div');d.className='row';
  d.innerHTML=`<span class="na" style="background:${grade(c.na)}">${c.na}</span>${c.label}<br>`+
              `<small>${[...new Set(c.stops.map(s=>s.a))].join(' + ')}</small>`;
  d.onclick=()=>map.flyTo([(c.b[0]+c.b[2])/2,(c.b[1]+c.b[3])/2],19);
  list.appendChild(d);
});
if(CELLS.length>300){const d=document.createElement('div');d.className='sub';
  d.style.padding='8px 12px';d.textContent=`…plus ${(CELLS.length-300).toLocaleString()} more cells — pan/zoom the map.`;
  list.appendChild(d);}
</script></body></html>"""


if __name__ == "__main__":
    main()
