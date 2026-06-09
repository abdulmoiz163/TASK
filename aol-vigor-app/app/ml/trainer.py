import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import cross_val_score, StratifiedKFold
from sklearn.metrics import f1_score, accuracy_score, classification_report
import joblib


class VigorTrainer:

    def __init__(self, n_estimators=200, max_depth=10, random_state=42):
        self.model = None
        self.scaler = StandardScaler()
        self.label_map = None
        self.feature_importances = None
        self.mode = None
        self.metrics = {}
        self.n_estimators = n_estimators
        self.max_depth = max_depth

    def train_supervised(self, X, y):
        self.mode = "supervised"
        self.scaler.fit(X)
        X_scaled = self.scaler.transform(X)

        self.model = RandomForestClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )
        self.model.fit(X_scaled, y)

        cv = StratifiedKFold(n_splits=min(5, len(np.unique(y))), shuffle=True, random_state=42)
        if len(np.unique(y)) > 1 and len(y) >= 10:
            scores = cross_val_score(self.model, X_scaled, y, cv=cv, scoring="f1_weighted")
            self.metrics["cross_val_f1"] = float(np.mean(scores))
        else:
            self.metrics["cross_val_f1"] = None

        y_pred = self.model.predict(X_scaled)
        self.metrics["accuracy"] = float(accuracy_score(y, y_pred))
        self.metrics["f1_per_class"] = {}
        f1s = f1_score(y, y_pred, average=None)
        for i, f1 in enumerate(f1s):
            label = self.label_map.get(i, f"class_{i}") if self.label_map else f"class_{i}"
            self.metrics["f1_per_class"][label] = float(f1)

        if hasattr(self.model, "feature_importances_"):
            self.feature_importances = {
                X.columns[j]: float(self.model.feature_importances_[j])
                for j in range(len(X.columns))
            }

        return self.metrics

    def train_unsupervised(self, X, n_clusters=4):
        self.mode = "unsupervised"
        self.scaler.fit(X)
        X_scaled = self.scaler.transform(X)

        km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = km.fit_predict(X_scaled)

        if hasattr(X, 'columns') and "ndvi_mean" in X.columns:
            ndvi_idx = list(X.columns).index("ndvi_mean")
        else:
            ndvi_idx = 0
        centroids = km.cluster_centers_
        centroid_ndvi = centroids[:, ndvi_idx]
        order = np.argsort(centroid_ndvi)

        label_map = {old: new for new, old in enumerate(order)}
        remapped = np.array([label_map[l] for l in labels])

        self.label_map = {i: ["Low", "Medium", "High", "Very High"][i] for i in range(n_clusters)}
        self.model = km
        self.metrics["mode"] = "unsupervised"
        self.metrics["n_clusters"] = n_clusters
        self.metrics["inertia"] = float(km.inertia_)

        if hasattr(km, "cluster_centers_"):
            cols = X.columns if hasattr(X, 'columns') else [f"feat_{j}" for j in range(X.shape[1])]
            self.feature_importances = {
                cols[j]: float(abs(centroids[:, j]).mean())
                for j in range(X_scaled.shape[1])
            }

        return remapped, self.metrics

    def save(self, model_path, scaler_path):
        joblib.dump(self.model, str(model_path))
        joblib.dump(self.scaler, str(scaler_path))

    def load(self, model_path, scaler_path):
        self.model = joblib.load(str(model_path))
        self.scaler = joblib.load(str(scaler_path))
