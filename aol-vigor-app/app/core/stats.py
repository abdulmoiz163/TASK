import numpy as np
import pandas as pd

from app.core.indices import array_stats, percentile_stats
from app.core.raster_utils import compute_slope_aspect


def compute_tile_feature_vector(tile_data, tile_info, resolution):
    row = {
        "tile_id": tile_info["tile_id"],
        "tile_row": tile_info["row"],
        "tile_col": tile_info["col"],
        "partial_tile": 1 if tile_info["status"] == "partial" else 0,
    }

    ndvi = tile_data.get("ndvi")
    gndvi = tile_data.get("gndvi")
    dem = tile_data.get("dem")
    rgb = tile_data.get("rgb")

    if ndvi is not None:
        s = array_stats(ndvi, nodata=-9999)
        p = percentile_stats(ndvi, nodata=-9999, percentiles=(10, 90))
        row.update({
            "ndvi_mean": s["mean"], "ndvi_std": s["std"],
            "ndvi_min": s["min"], "ndvi_max": s["max"],
            "ndvi_p10": p["p10"], "ndvi_p90": p["p90"],
        })
    else:
        row.update({"ndvi_mean": 0, "ndvi_std": 0, "ndvi_min": 0, "ndvi_max": 0, "ndvi_p10": 0, "ndvi_p90": 0})

    if gndvi is not None:
        s = array_stats(gndvi, nodata=-9999)
        p = percentile_stats(gndvi, nodata=-9999, percentiles=(10, 90))
        row.update({
            "gndvi_mean": s["mean"], "gndvi_std": s["std"],
            "gndvi_min": s["min"], "gndvi_max": s["max"],
            "gndvi_p10": p["p10"], "gndvi_p90": p["p90"],
        })
    else:
        row.update({"gndvi_mean": 0, "gndvi_std": 0, "gndvi_min": 0, "gndvi_max": 0, "gndvi_p10": 0, "gndvi_p90": 0})

    ndvi_mean = row.get("ndvi_mean", 0) or 0.001
    gndvi_mean = row.get("gndvi_mean", 0) or 0.001
    row["ndvi_gndvi_ratio"] = ndvi_mean / gndvi_mean if abs(gndvi_mean) > 0.001 else 1.0

    if dem is not None:
        dem_f = dem.astype(float)
        mask = dem_f == -9999
        dem_valid = dem_f[~mask]
        s = array_stats(dem, nodata=-9999)
        row["dem_mean"] = s["mean"]
        row["dem_std"] = s["std"]

        if mask.all():
            row["slope_mean"] = 0
            row["aspect_mean"] = 0
        else:
            dem_clean = np.where(mask, np.nan, dem_f)
            with np.errstate(divide="ignore", invalid="ignore"):
                slope, aspect = compute_slope_aspect(
                    np.nan_to_num(dem_clean, nan=0), resolution)
                slope_valid = slope[~mask]
                aspect_valid = aspect[~mask]
                row["slope_mean"] = float(np.nanmean(slope_valid)) if slope_valid.size > 0 else 0
                row["aspect_mean"] = float(np.nanmean(aspect_valid)) if aspect_valid.size > 0 else 0
    else:
        row.update({"dem_mean": 0, "dem_std": 0, "slope_mean": 0, "aspect_mean": 0})

    if rgb is not None:
        rgb_f = rgb.astype(float)
        for i, name in enumerate(["r", "g", "b"]):
            band = rgb_f[i] if rgb_f.ndim == 3 else rgb_f
            row[f"{name}_mean"] = float(np.nanmean(band))
            row[f"{name}_std"] = float(np.nanstd(band))
        r_mean = row.get("r_mean", 0)
        g_mean = row.get("g_mean", 0)
        b_mean = row.get("b_mean", 0)
        row["excess_green"] = 2 * g_mean - r_mean - b_mean
        denom = g_mean + r_mean - b_mean + 1e-10
        row["vari"] = (g_mean - r_mean) / denom
    else:
        row.update({"r_mean": 0, "g_mean": 0, "b_mean": 0,
                     "r_std": 0, "g_std": 0, "b_std": 0,
                     "excess_green": 0, "vari": 0})

    return row


def compute_correlation_matrix(df):
    numeric = df.select_dtypes(include=[np.number])
    if numeric.empty:
        return {}
    corr = numeric.corr()
    cols = corr.columns.tolist()
    data = corr.values.tolist()
    return {
        "columns": cols,
        "data": data,
    }
