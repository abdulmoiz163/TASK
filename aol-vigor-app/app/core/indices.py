import numpy as np


def compute_ndvi(nir_band, red_band, nodata=-9999):
    nir = nir_band.astype(np.float32)
    red = red_band.astype(np.float32)
    mask = (nir == nodata) | (red == nodata) | ((nir + red) == 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = np.where(~mask, (nir - red) / (nir + red), nodata)
    return ndvi.astype(np.float32)


def compute_gndvi(nir_band, green_band, nodata=-9999):
    nir = nir_band.astype(np.float32)
    green = green_band.astype(np.float32)
    mask = (nir == nodata) | (green == nodata) | ((nir + green) == 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        gndvi = np.where(~mask, (nir - green) / (nir + green), nodata)
    return gndvi.astype(np.float32)


def normalize_uint16_to_uint8(arr, scale=255.0 / 65535.0):
    return np.clip(arr.astype(np.float32) * scale, 0, 255).astype(np.uint8)


def array_stats(arr, nodata=None):
    if nodata is not None:
        arr = arr.astype(np.float32)
        arr = arr[arr != nodata]
    if arr.size == 0:
        return {"mean": 0, "min": 0, "max": 0, "std": 0, "valid_px": 0}
    return {
        "mean": float(np.nanmean(arr)),
        "min": float(np.nanmin(arr)),
        "max": float(np.nanmax(arr)),
        "std": float(np.nanstd(arr)),
        "valid_px": int(arr.size),
    }


def percentile_stats(arr, nodata=None, percentiles=(10, 90)):
    if nodata is not None:
        arr = arr.astype(np.float32)
        arr = arr[arr != nodata]
    if arr.size == 0:
        return {f"p{p}": 0 for p in percentiles}
    vals = np.nanpercentile(arr, list(percentiles))
    return {f"p{p}": float(v) for p, v in zip(percentiles, vals)}
