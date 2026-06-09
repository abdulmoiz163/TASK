import traceback
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.mask import mask as rio_mask
from rasterio.warp import reproject, Resampling, calculate_default_transform
from shapely.geometry import Polygon, mapping
import geopandas as gpd


def load_raster_meta(path):
    path = str(path)
    with rasterio.open(path) as ds:
        return {
            "path": path,
            "crs": ds.crs,
            "bounds": ds.bounds,
            "width": ds.width,
            "height": ds.height,
            "resolution": ds.res,
            "count": ds.count,
            "nodata": ds.nodata,
            "dtype": str(ds.dtypes[0]),
        }


def validate_geotiff(path):
    try:
        with rasterio.open(str(path)) as ds:
            if ds.crs is None:
                return False, "No CRS found"
            if ds.transform.is_identity:
                return False, "No geotransform (identity)"
            if not ds.crs.is_projected:
                return False, f"CRS {ds.crs} is not projected (must be in metres)"
            return True, None
    except Exception as e:
        return False, str(e)


def reproject_raster(src_path, dst_path, target_crs):
    with rasterio.open(str(src_path)) as src:
        transform, width, height = calculate_default_transform(
            src.crs, target_crs, src.width, src.height, *src.bounds)
        kwargs = src.profile.copy()
        kwargs.update({
            "crs": target_crs,
            "transform": transform,
            "width": width,
            "height": height,
            "compress": "lzw",
        })
        with rasterio.open(str(dst_path), "w", **kwargs) as dst:
            for i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, i),
                    destination=rasterio.band(dst, i),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=target_crs,
                    resampling=Resampling.bilinear,
                )
    return dst_path


def clip_raster_to_aoi(src_path, aoi_geo, out_path, nodata=None):
    with rasterio.open(str(src_path)) as ds:
        if nodata is None:
            nodata = ds.nodata if ds.nodata is not None else 0
        out_image, out_transform = rio_mask(
            ds, [mapping(aoi_geo)], crop=True, all_touched=False,
            nodata=nodata, filled=True
        )
        out_meta = ds.profile.copy()
        out_meta.update({
            "driver": "GTiff",
            "height": out_image.shape[1],
            "width": out_image.shape[2],
            "transform": out_transform,
            "nodata": nodata,
            "compress": "lzw",
        })
        with rasterio.open(str(out_path), "w", **out_meta) as dst:
            dst.write(out_image)
    return out_path


def read_tile_window(src_path, bounds):
    with rasterio.open(str(src_path)) as ds:
        win = from_bounds(bounds[0], bounds[1], bounds[2], bounds[3], ds.transform)
        win = win.intersection(rasterio.windows.Window(0, 0, ds.width, ds.height))
        if win.width < 1 or win.height < 1:
            return None
        data = ds.read(window=win)
        transform = ds.window_transform(win)
        return {
            "data": data,
            "transform": transform,
            "width": win.width,
            "height": win.height,
            "crs": ds.crs,
            "nodata": ds.nodata,
        }


def write_tile(data, transform, crs, out_path, nodata=None, dtype=None):
    if data.ndim == 2:
        count = 1
        data = data[np.newaxis, :, :]
    else:
        count = data.shape[0]

    if dtype is None:
        dtype = data.dtype.name

    profile = {
        "driver": "GTiff",
        "height": data.shape[1],
        "width": data.shape[2],
        "count": count,
        "dtype": dtype,
        "crs": crs,
        "transform": transform,
        "compress": "lzw",
    }
    if nodata is not None:
        profile["nodata"] = nodata

    with rasterio.open(str(out_path), "w", **profile) as dst:
        dst.write(data)
    return out_path


def resample_to_match(src_path, ref_path, out_path, resampling=Resampling.bilinear):
    with rasterio.open(str(ref_path)) as ref:
        ref_crs = ref.crs
        ref_transform = ref.transform
        ref_width = ref.width
        ref_height = ref.height

    with rasterio.open(str(src_path)) as src:
        kwargs = src.profile.copy()
        kwargs.update({
            "crs": ref_crs,
            "transform": ref_transform,
            "width": ref_width,
            "height": ref_height,
            "compress": "lzw",
        })
        with rasterio.open(str(out_path), "w", **kwargs) as dst:
            for i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, i),
                    destination=rasterio.band(dst, i),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=ref_transform,
                    dst_crs=ref_crs,
                    resampling=resampling,
                )
    return out_path


def get_resolution(path):
    with rasterio.open(str(path)) as ds:
        return ds.res


def compute_slope_aspect(dem_array, resolution):
    dy, dx = np.gradient(dem_array.astype(float))
    angle = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))
    aspect = np.degrees(np.arctan2(-dy, dx)) % 360
    return angle, aspect
