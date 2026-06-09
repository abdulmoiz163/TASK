import pandas as pd
import numpy as np


FEATURE_COLUMNS = [
    "ndvi_mean", "ndvi_std", "ndvi_min", "ndvi_max", "ndvi_p10", "ndvi_p90",
    "gndvi_mean", "gndvi_std", "gndvi_min", "gndvi_max", "gndvi_p10", "gndvi_p90",
    "ndvi_gndvi_ratio",
    "dem_mean", "dem_std", "slope_mean", "aspect_mean",
    "r_mean", "g_mean", "b_mean", "r_std", "g_std", "b_std",
    "excess_green", "vari",
    "tile_row", "tile_col", "partial_tile",
]


def build_feature_matrix(csv_path):
    df = pd.read_csv(csv_path)
    available = [c for c in FEATURE_COLUMNS if c in df.columns]
    X = df[available].copy()
    X = X.replace([np.inf, -np.inf], np.nan)
    for col in X.columns:
        if X[col].isna().any():
            X[col] = X[col].fillna(X[col].median())
    return X, df, available
