import math
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
from shapely.geometry import box, mapping
from pyproj import Transformer
import rasterio
from rasterio.windows import from_bounds

from app.core.raster_utils import write_tile


def compute_tile_grid(aoi_geo, src_crs, tile_size_m=3.5):
    aoi_bounds = aoi_geo.bounds

    lon = (aoi_bounds[0] + aoi_bounds[2]) / 2
    lat = (aoi_bounds[1] + aoi_bounds[3]) / 2

    zone = int((lon + 180) / 6) + 1 if src_crs.is_geographic else 0
    hemi = 326 if lat >= 0 else 327
    metric_crs = rasterio.crs.CRS.from_epsg(hemi * 100 + zone) if src_crs.is_geographic else src_crs

    t_to_metric = Transformer.from_crs(src_crs, metric_crs, always_xy=True)
    t_from_metric = Transformer.from_crs(metric_crs, src_crs, always_xy=True)

    xs, ys = t_to_metric.transform(
        [aoi_bounds[0], aoi_bounds[2]],
        [aoi_bounds[1], aoi_bounds[3]]
    )
    m_minx, m_maxx = min(xs), max(xs)
    m_miny, m_maxy = min(ys), max(ys)

    cols = max(1, math.ceil((m_maxx - m_minx) / tile_size_m))
    rows = max(1, math.ceil((m_maxy - m_miny) / tile_size_m))

    tiles = []
    tile_geoms = []
    for r in range(rows):
        for c in range(cols):
            t_minx = m_minx + c * tile_size_m
            t_miny = m_miny + r * tile_size_m
            t_maxx = t_minx + tile_size_m
            t_maxy = t_miny + tile_size_m

            tile_metric = box(t_minx, t_miny, t_maxx, t_maxy)

            if not tile_metric.intersects(box(m_minx, m_miny, m_maxx, m_maxy)):
                continue

            xs2, ys2 = t_from_metric.transform(
                [t_minx, t_maxx], [t_miny, t_maxy])
            s_minx, s_maxx = min(xs2), max(xs2)
            s_miny, s_maxy = min(ys2), max(ys2)
            tile_src = box(s_minx, s_miny, s_maxx, s_maxy)

            if not aoi_geo.intersects(tile_src):
                continue

            inter = aoi_geo.intersection(tile_src)
            ratio = inter.area / tile_src.area if tile_src.area > 0 else 0
            status = "full" if ratio > 0.99 else ("partial" if ratio > 0 else "outside")

            tiles.append({
                "row": r,
                "col": c,
                "tile_id": f"tile_{r:04d}_{c:04d}",
                "bounds_metric": (t_minx, t_miny, t_maxx, t_maxy),
                "bounds_src": (s_minx, s_miny, s_maxx, s_maxy),
                "geometry_src": tile_src,
                "status": status,
                "overlap_ratio": ratio,
            })
            tile_geoms.append(tile_src)

    return tiles, metric_crs


def generate_tile_geojson(tiles, metric_crs):
    features = []
    for t in tiles:
        bounds = t["bounds_metric"]
        poly = box(*bounds)
        features.append({
            "type": "Feature",
            "geometry": mapping(poly),
            "properties": {
                "tile_id": t["tile_id"],
                "row": t["row"],
                "col": t["col"],
                "status": t["status"],
            }
        })
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": str(metric_crs)}},
        "features": features,
    }


def extract_tiles_parallel(raster_path, tiles, output_dir, band_type, band_config=None, nodata=None, max_workers=4):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    def _process_one(t):
        tile_id = t["tile_id"]
        bounds = t["bounds_src"]
        out_path = str(output_dir / f"{tile_id}.tif")
        try:
            with rasterio.open(str(raster_path)) as ds:
                win = from_bounds(bounds[0], bounds[1], bounds[2], bounds[3], ds.transform)
                win = win.intersection(rasterio.windows.Window(0, 0, ds.width, ds.height))
                if win.width < 1 or win.height < 1:
                    return (tile_id, None, "empty")
                data = ds.read(window=win)
                transform = ds.window_transform(win)
                profile = ds.profile.copy()
                profile.update({
                    "height": data.shape[1],
                    "width": data.shape[2],
                    "transform": transform,
                    "compress": "lzw",
                })
                if nodata is not None:
                    profile["nodata"] = nodata
                if band_type == "rgb" and data.shape[0] > 3:
                    data = data[:3]
                elif band_type in ("ndvi", "gndvi") and data.shape[0] == 1:
                    pass
                with rasterio.open(out_path, "w", **profile) as dst:
                    dst.write(data)
            return (tile_id, out_path, "ok")
        except Exception as e:
            return (tile_id, None, str(e))

    with ThreadPoolExecutor(max_workers=max_workers) as exe:
        futures = {exe.submit(_process_one, t): t for t in tiles}
        for f in as_completed(futures):
            results.append(f.result())

    return results
