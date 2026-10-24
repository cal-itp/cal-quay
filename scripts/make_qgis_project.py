"""
Build data/shared_stops.qgz — a ready-styled QGIS project for the shared-stops
deliverable: Esri aerial + OSM basemaps, the geohash cells as polygons
color-graded by how many agencies share them (2 amber .. 5+ magenta), and the
stops categorized by agency on top.

Runs under QGIS's bundled Python (PyQGIS), not uv:

  QGIS_PREFIX_PATH=/Applications/QGIS-LTR.app/Contents/MacOS \
  PYTHONPATH=/Applications/QGIS-LTR.app/Contents/Resources/python \
  PROJ_LIB=/Applications/QGIS-LTR.app/Contents/Resources/proj \
  /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 scripts/make_qgis_project.py
"""

import csv
from collections import defaultdict
from pathlib import Path

from qgis.core import (
    QgsApplication, QgsCategorizedSymbolRenderer, QgsCoordinateReferenceSystem,
    QgsFeature, QgsField, QgsFillSymbol, QgsGeometry, QgsMarkerSymbol, QgsProject,
    QgsRasterLayer, QgsRectangle, QgsReferencedRectangle, QgsRendererCategory,
    QgsVectorFileWriter, QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"

PALETTE = [
    "#e6194B", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4", "#f032e6",
    "#bfef45", "#fabed4", "#469990", "#9A6324", "#800000", "#808000", "#000075",
    "#e6beff", "#ff8c00", "#1e90ff", "#dc143c", "#00ced1", "#8b4513",
]

GRADE = {2: "#ffd21f", 3: "#ff8c00", 4: "#ff3b30"}  # 5+ -> magenta below


def grade(na: int) -> str:
    return GRADE.get(na, "#b1006e")


def cell_bounds(gh: str) -> tuple:
    """Decode a geohash to (lat_lo, lon_lo, lat_hi, lon_hi)."""
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
    return lat_lo, lon_lo, lat_hi, lon_hi


def latest(pattern: str) -> Path:
    c = sorted(DATA_DIR.glob(pattern))
    if not c:
        raise SystemExit(f"No {pattern} in data/ — run find_shared_stops.py first.")
    return c[-1]


def build_cells_gpkg(src_csv: Path, out_gpkg: Path) -> None:
    cells = defaultdict(lambda: {"na": 0, "ns": 0, "agencies": set()})
    with open(src_csv) as f:
        for row in csv.DictReader(f):
            c = cells[row["geohash"]]
            c["na"] = int(row["n_agencies"])
            c["ns"] = int(row["n_stops"])
            c["agencies"].add(row["agency"])

    vl = QgsVectorLayer("Polygon?crs=EPSG:4326", "cells", "memory")
    pr = vl.dataProvider()
    pr.addAttributes([
        QgsField("geohash", QVariant.String),
        QgsField("n_agencies", QVariant.Int),
        QgsField("n_stops", QVariant.Int),
        QgsField("agencies", QVariant.String),
    ])
    vl.updateFields()
    feats = []
    for gh, c in cells.items():
        lat_lo, lon_lo, lat_hi, lon_hi = cell_bounds(gh)
        ft = QgsFeature(vl.fields())
        ft.setGeometry(QgsGeometry.fromRect(QgsRectangle(lon_lo, lat_lo, lon_hi, lat_hi)))
        ft.setAttributes([gh, c["na"], c["ns"], " + ".join(sorted(c["agencies"]))])
        feats.append(ft)
    pr.addFeatures(feats)

    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = "shared_cells"
    err = QgsVectorFileWriter.writeAsVectorFormatV3(
        vl, str(out_gpkg), QgsProject.instance().transformContext(), opts
    )
    if err[0] != QgsVectorFileWriter.NoError:
        raise SystemExit(f"writing {out_gpkg} failed: {err}")
    print(f"  {len(feats):,} cells -> {out_gpkg}")


def main() -> None:
    src_csv = latest("shared_stops_*.csv")
    stamp = src_csv.stem.replace("shared_stops_", "")
    stops_gpkg = DATA_DIR / f"shared_stops_{stamp}.gpkg"
    cells_gpkg = DATA_DIR / f"shared_cells_{stamp}.gpkg"
    out = DATA_DIR / "shared_stops.qgz"

    build_cells_gpkg(src_csv, cells_gpkg)

    project = QgsProject.instance()
    project.setTitle(f"Multi-agency shared stops ({stamp})")
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    root = project.layerTreeRoot()

    stops = QgsVectorLayer(f"{stops_gpkg}|layername=shared_stops", "Stops (by agency)", "ogr")
    cells = QgsVectorLayer(f"{cells_gpkg}|layername=shared_cells", "Shared cells (# agencies)", "ogr")
    esri = QgsRasterLayer(
        "type=xyz&url=https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Imagery/MapServer/tile/%7Bz%7D/%7By%7D/%7Bx%7D&zmax=19&zmin=0",
        "Esri World Imagery", "wms",
    )
    osm = QgsRasterLayer(
        "type=xyz&url=https://tile.openstreetmap.org/%7Bz%7D/%7Bx%7D/%7By%7D.png&zmax=19&zmin=0",
        "OpenStreetMap", "wms",
    )
    for lyr in (stops, cells, esri, osm):
        if not lyr.isValid():
            raise SystemExit(f"layer failed to load: {lyr.name()}")

    agencies = sorted({f["agency"] for f in stops.getFeatures()})
    cats = []
    for i, a in enumerate(agencies):
        sym = QgsMarkerSymbol.createSimple({
            "name": "circle", "color": PALETTE[i % len(PALETTE)],
            "outline_color": "#222222", "outline_width": "0.15", "size": "2.2",
        })
        cats.append(QgsRendererCategory(a, sym, a))
    stops.setRenderer(QgsCategorizedSymbolRenderer("agency", cats))

    na_values = sorted({f["n_agencies"] for f in cells.getFeatures()})
    cell_cats = []
    for na in na_values:
        col = grade(na)
        sym = QgsFillSymbol.createSimple({
            "color": col, "outline_color": col, "outline_width": "0.5",
        })
        sym.setOpacity(0.45)
        cell_cats.append(QgsRendererCategory(na, sym, f"{na} agencies"))
    cells.setRenderer(QgsCategorizedSymbolRenderer("n_agencies", cell_cats))

    # top-to-bottom: stops, cells, OSM (off), aerial
    for lyr in (stops, cells, osm, esri):
        project.addMapLayer(lyr, False)
        root.addLayer(lyr)
    root.findLayer(osm.id()).setItemVisibilityChecked(False)

    try:
        project.viewSettings().setDefaultViewExtent(
            QgsReferencedRectangle(stops.extent(), QgsCoordinateReferenceSystem("EPSG:4326"))
        )
    except AttributeError:
        pass

    if not project.write(str(out)):
        raise SystemExit(f"writing {out} failed")
    print(f"  project -> {out}")


if __name__ == "__main__":
    QgsApplication.setPrefixPath("/Applications/QGIS-LTR.app/Contents/MacOS", True)
    app = QgsApplication([], False)
    app.initQgis()
    try:
        main()
    finally:
        app.exitQgis()
