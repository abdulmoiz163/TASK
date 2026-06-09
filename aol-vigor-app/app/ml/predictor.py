import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import box, shape
import json

from app.ml.feature_builder import build_feature_matrix
from app.ml.trainer import VigorTrainer


class VigorPredictor:

    def __init__(self, trainer):
        self.trainer = trainer
        self.predictions = None

    def predict(self, csv_path):
        X, df, feature_cols = build_feature_matrix(csv_path)
        X_scaled = self.trainer.scaler.transform(X)

        if self.trainer.mode == "unsupervised":
            labels = self.trainer.model.predict(X_scaled)
            ndvi_idx = feature_cols.index("ndvi_mean") if "ndvi_mean" in feature_cols else 0
            centroids = self.trainer.model.cluster_centers_
            centroid_ndvi = centroids[:, ndvi_idx]
            order = np.argsort(centroid_ndvi)
            label_map = {old: new for new, old in enumerate(order)}
            labels = np.array([label_map[l] for l in labels])
            vigor_labels = ["Low", "Medium", "High", "Very High"]
            predicted_labels = [vigor_labels[l] if l < len(vigor_labels) else "Unknown" for l in labels]
        else:
            labels = self.trainer.model.predict(X_scaled)
            probs = self.trainer.model.predict_proba(X_scaled)
            vigor_scores = np.max(probs, axis=1)
            label_names = {i: n for i, n in self.trainer.label_map.items()} if self.trainer.label_map else {}
            predicted_labels = [label_names.get(l, f"Class_{l}") for l in labels]
            vigor_scores_list = vigor_scores.tolist()

        results = df[["tile_id", "tile_row", "tile_col"]].copy()
        results["vigor_class"] = labels
        results["vigor_label"] = predicted_labels

        if self.trainer.mode == "supervised":
            results["vigor_score"] = vigor_scores_list
        else:
            results["vigor_score"] = 1.0

        self.predictions = results

        return results

    def to_geojson(self, tile_geojson_path, predictions_path):
        preds = pd.read_csv(predictions_path)
        with open(tile_geojson_path) as f:
            grid = json.load(f)

        feat_map = {}
        for feat in grid.get("features", []):
            tid = feat["properties"].get("tile_id")
            if tid:
                feat_map[tid] = feat

        for _, row in preds.iterrows():
            tid = row.get("tile_id")
            if tid in feat_map:
                feat_map[tid]["properties"]["vigor_class"] = int(row.get("vigor_class", 0))
                feat_map[tid]["properties"]["vigor_label"] = str(row.get("vigor_label", "Unknown"))
                feat_map[tid]["properties"]["vigor_score"] = float(row.get("vigor_score", 0))
                feat_map[tid]["properties"]["ndvi_mean"] = float(row.get("ndvi_mean", 0))
                feat_map[tid]["properties"]["gndvi_mean"] = float(row.get("gndvi_mean", 0))

        return {
            "type": "FeatureCollection",
            "features": list(feat_map.values()),
        }
