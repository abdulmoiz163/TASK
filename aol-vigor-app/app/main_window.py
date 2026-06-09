import os
import json
import html
import traceback
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import from_bounds
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QLabel, QPushButton, QFileDialog,
    QGroupBox, QGridLayout, QLineEdit, QDoubleSpinBox,
    QProgressBar, QStatusBar, QTabWidget, QTextEdit,
    QFrame, QSizePolicy, QMessageBox,
    QButtonGroup, QSpinBox, QCheckBox, QComboBox,
    QScrollArea, QListWidget, QListWidgetItem,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QSlider, QDialog, QDialogButtonBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPointF, QTimer
from PyQt6.QtGui import QPixmap, QImage, QFont, QColor, QBrush

from shapely.geometry import Polygon, box, shape
from shapely.ops import unary_union

from app.config import (
    APP_NAME, APP_VERSION,
    C_BG, C_SURFACE, C_PANEL, C_BORDER, C_TEXT, C_TEXT_SECONDARY,
    C_MUTED, C_ACCENT, C_ACCENT_LIGHT, C_SUCCESS, C_WARN, C_ERR,
    STYLE, VIGOR_COLORS, VIGOR_LABELS, BAND_CONFIG,
    DEFAULT_TILE_SIZE_M,
)
from app.core.session import create_session, get_session, cleanup_session
from app.core.raster_utils import (
    load_raster_meta, validate_geotiff, reproject_raster,
    clip_raster_to_aoi, get_resolution,
)
from app.core.indices import compute_ndvi, compute_gndvi, normalize_uint16_to_uint8
from app.core.grid import compute_tile_grid, generate_tile_geojson, extract_tiles_parallel
from app.core.stats import compute_tile_feature_vector, compute_correlation_matrix
from app.ml.feature_builder import build_feature_matrix, FEATURE_COLUMNS
from app.ml.trainer import VigorTrainer
from app.ml.predictor import VigorPredictor
from app.ui.map_canvas import MapCanvas


class RasterLoadThread(QThread):
    done = pyqtSignal(object, object, object, int, int, str)
    error = pyqtSignal(str)
    progress = pyqtSignal(int)

    def __init__(self, path, is_rgb=False):
        super().__init__()
        self.path = path
        self.is_rgb = is_rgb

    def run(self):
        try:
            self.progress.emit(10)
            with rasterio.open(str(self.path)) as ds:
                crs = ds.crs
                bounds = ds.bounds
                w, h = ds.width, ds.height
                max_dim = 1024
                scale = min(max_dim / w, max_dim / h, 1.0)
                ow = max(int(w * scale), 1)
                oh = max(int(h * scale), 1)

                if self.is_rgb:
                    count = min(ds.count, 3)
                    data = ds.read(list(range(1, count + 1)),
                                   out_shape=(count, oh, ow),
                                   resampling=rasterio.enums.Resampling.average)
                else:
                    data = ds.read(1, out_shape=(oh, ow),
                                   resampling=rasterio.enums.Resampling.average)

            self.progress.emit(60)
            if self.is_rgb:
                rgb = np.zeros((3, oh, ow), dtype=np.float32)
                for i in range(min(ds.count if hasattr(ds, 'count') else 3, 3)):
                    band = data[i].astype(float) if data.ndim == 3 else data.astype(float)
                    valid = band[~np.isnan(band)]
                    if valid.size > 0:
                        lo, hi = np.nanpercentile(band, 2), np.nanpercentile(band, 98)
                        if lo == hi: hi = lo + 1
                        rgb[i] = np.clip((band - lo) / (hi - lo), 0, 1)
                rgba = (np.clip(np.transpose(rgb, (1, 2, 0)), 0, 1) * 255).astype(np.uint8)
                alpha = np.full((oh, ow, 1), 255, dtype=np.uint8)
                rgba = np.concatenate([rgba, alpha], axis=2)
            else:
                data_f = data.astype(float)
                valid = data_f[~np.isnan(data_f)]
                lo, hi = np.nanpercentile(data_f, 2), np.nanpercentile(data_f, 98) if valid.size > 0 else (0, 1)
                if lo == hi: hi = lo + 1
                normed = np.clip((data_f - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
                normed[np.isnan(data_f)] = 0
                rgba = np.zeros((oh, ow, 4), dtype=np.uint8)
                rgba[..., 0] = normed
                rgba[..., 1] = (normed * 0.85).astype(np.uint8)
                rgba[..., 2] = (normed * 0.65).astype(np.uint8)
                rgba[..., 3] = 255

            self.progress.emit(80)
            img = QImage(rgba.tobytes(), ow, oh, ow * 4, QImage.Format.Format_RGBA8888)
            pix = QPixmap.fromImage(img)
            self.progress.emit(100)
            self.done.emit(pix, bounds, crs, w, h, self.path)
        except Exception as ex:
            self.error.emit(traceback.format_exc())


class ProcessingWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(str, object)
    error = pyqtSignal(str)
    log = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._cancelled = False
        self.work_fn = None

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self.work_fn:
            try:
                self.work_fn()
            except Exception as e:
                if not self._cancelled:
                    self.error.emit(traceback.format_exc())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  v{APP_VERSION}")
        self.resize(1500, 950)

        self.session = None
        self.rgb_path = None
        self.ms_path = None
        self.dem_path = None
        self.shapefile_path = None

        self.raster_crs = None
        self.aoi_geo = None
        self.clipped_rasters = {}
        self.tiles = []
        self.tile_geometries = []
        self.features_done = False
        self.feature_vectors = None
        self.ml_model = None
        self.ml_predictions = None
        self.vigor_geojson = None

        self._load_thread = None
        self._worker = ProcessingWorker()
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.log.connect(self.log_msg)

        self._build_ui()
        self.setStyleSheet(STYLE)
        self.status("Ready")
        self._update_step_status()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left = QWidget()
        left.setFixedWidth(380)
        left.setStyleSheet(f"background:{C_SURFACE}; border-right: 1px solid {C_BORDER};")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)

        header = QWidget()
        header.setStyleSheet(f"background:{C_ACCENT}; padding:16px;")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(16, 12, 16, 12)
        title = QLabel("AOL Crop Vigor Analyzer")
        title.setStyleSheet("font-size:17px;font-weight:700;color:white;")
        hl.addWidget(title)
        sub = QLabel("Step-by-step analysis pipeline")
        sub.setStyleSheet("font-size:11px;color:rgba(255,255,255,0.8);")
        hl.addWidget(sub)
        lv.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_widget = QWidget()
        sv = QVBoxLayout(scroll_widget)
        sv.setContentsMargins(12, 12, 12, 12)
        sv.setSpacing(6)

        self.step_labels = []
        self.step_buttons = []
        self.step_status = []

        steps = [
            ("Step 1: Data Ingestion", "Load GeoTIFFs + Shapefile"),
            ("Step 2: AOI Extraction", "Clip rasters to AOI boundary"),
            ("Step 3: Grid Tiling", "Generate 3.5m tile grid"),
            ("Step 4: Feature Extraction", "Compute NDVI, GNDVI, DEM, RGB"),
            ("Step 5: Download Tiles", "Export tiles to output folder"),
            ("Step 6: Compute Statistics", "Feature vectors + correlation"),
            ("Step 7: ML Vigor Analysis", "Train model + predict vigor"),
        ]

        for i, (step_name, step_desc) in enumerate(steps):
            sg = QGroupBox()
            sg.setStyleSheet(f"""
                QGroupBox{{border:1px solid {C_BORDER};border-radius:4px;margin:0;padding:8px;
                background:{C_SURFACE};}}
            """)
            sg_v = QVBoxLayout(sg)
            sg_v.setSpacing(2)
            sg_v.setContentsMargins(10, 8, 10, 8)

            header_row = QHBoxLayout()
            lbl = QLabel(step_name)
            lbl.setObjectName("step")
            header_row.addWidget(lbl)
            header_row.addStretch()

            status_lbl = QLabel("⏳")
            status_lbl.setFixedWidth(20)
            header_row.addWidget(status_lbl)
            self.step_status.append(status_lbl)

            sg_v.addLayout(header_row)

            desc = QLabel(step_desc)
            desc.setStyleSheet(f"color:{C_TEXT_SECONDARY};font-size:11px;")
            sg_v.addWidget(desc)

            btn = QPushButton(f"Open Step {i+1}")
            btn.setFixedHeight(28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, s=i: self._open_step(s))
            sg_v.addWidget(btn)
            self.step_buttons.append(btn)
            self.step_labels.append(lbl)

            sv.addWidget(sg)

        sv.addStretch()
        scroll.setWidget(scroll_widget)
        lv.addWidget(scroll)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 8, 8, 8)
        rv.setSpacing(4)

        self.tabs = QTabWidget()
        map_tab = QWidget()
        map_v = QVBoxLayout(map_tab)
        map_v.setContentsMargins(0, 0, 0, 0)
        map_v.setSpacing(4)

        tb = QHBoxLayout()
        fit_btn = QPushButton("Fit view")
        fit_btn.clicked.connect(lambda: self.canvas.reset_view())
        tb.addWidget(fit_btn)
        self.coord_lbl = QLabel("X: —   Y: —")
        self.coord_lbl.setObjectName("coord")
        tb.addWidget(self.coord_lbl)
        tb.addStretch()
        self.load_pbar = QProgressBar()
        self.load_pbar.setFixedWidth(120)
        self.load_pbar.setFixedHeight(14)
        self.load_pbar.setVisible(False)
        tb.addWidget(self.load_pbar)
        map_v.addLayout(tb)

        self.canvas = MapCanvas()
        self.canvas.aoi_changed.connect(self._on_aoi_changed)
        self.canvas.coord_moved.connect(self._on_coord_moved)
        map_v.addWidget(self.canvas)
        self.tabs.addTab(map_tab, "Map")

        log_tab = QWidget()
        log_v = QVBoxLayout(log_tab)
        log_v.setContentsMargins(4, 4, 4, 4)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        log_v.addWidget(self.log)
        self.tabs.addTab(log_tab, "Log")

        step_tab = QWidget()
        self.step_panel = QVBoxLayout(step_tab)
        self.step_panel.setContentsMargins(8, 8, 8, 8)
        self._build_step_panels()
        self.tabs.addTab(step_tab, "Active Step")

        rv.addWidget(self.tabs)
        prog_row = QHBoxLayout()
        self.export_pbar = QProgressBar()
        self.export_pbar.setVisible(False)
        prog_row.addWidget(self.export_pbar)
        self.export_lbl = QLabel("")
        self.export_lbl.setObjectName("coord")
        prog_row.addWidget(self.export_lbl)
        rv.addLayout(prog_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter)
        self.setStatusBar(QStatusBar())
        self._current_step = 0
        self._open_step(0)

    def _build_step_panels(self):
        self.panels = {}
        steps_data = [
            self._build_step1_panel,
            self._build_step2_panel,
            self._build_step3_panel,
            self._build_step4_panel,
            self._build_step5_panel,
            self._build_step6_panel,
            self._build_step7_panel,
        ]
        for fn in steps_data:
            panel = fn()
            panel.setVisible(False)
            self.step_panel.addWidget(panel)

    def _clear_step_panel(self):
        for i in range(self.step_panel.count()):
            w = self.step_panel.itemAt(i).widget()
            if w:
                w.setVisible(False)

    def _open_step(self, idx):
        self._current_step = idx
        self._clear_step_panel()
        w = self.step_panel.itemAt(idx).widget()
        if w:
            w.setVisible(True)
        self.tabs.setCurrentIndex(2)
        self._update_step_status()

    def _update_step_status(self):
        pass

    def status(self, msg):
        self.statusBar().showMessage(msg)

    def log_msg(self, msg, colour=C_TEXT, switch_tab=False):
        safe = html.escape(str(msg))
        self.log.append(f'<span style="color:{colour};">{safe}</span>')

    # ── Step 1: Data Ingestion ──
    def _build_step1_panel(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(8)

        g = QGroupBox("Upload GeoTIFF Files")
        gv = QVBoxLayout(g)
        gv.setSpacing(4)

        for key, label, required in [
            ("rgb", "RGB Raster (3-band)", True),
            ("multispectral", "Multispectral (R,G,NIR)", True),
            ("dem", "DEM Raster (elevation)", True),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(f"<b>{label}</b>")
            lbl.setFixedWidth(180)
            edit = QLineEdit()
            edit.setPlaceholderText("not loaded")
            edit.setReadOnly(True)
            btn = QPushButton("Browse")
            btn.clicked.connect(lambda _, k=key: self._browse_raster(k))
            row.addWidget(lbl)
            row.addWidget(edit)
            row.addWidget(btn)
            gv.addLayout(row)
            setattr(self, f"_{key}_edit", edit)

        l.addWidget(g)

        sg = QGroupBox("Shapefile (AOI)")
        sgv = QVBoxLayout(sg)
        row2 = QHBoxLayout()
        self._shp_edit = QLineEdit()
        self._shp_edit.setPlaceholderText("not loaded")
        self._shp_edit.setReadOnly(True)
        btn2 = QPushButton("Browse Shapefile")
        btn2.clicked.connect(self._browse_shapefile)
        row2.addWidget(self._shp_edit)
        row2.addWidget(btn2)
        sgv.addLayout(row2)
        l.addWidget(sg)

        self._val_info = QLabel("")
        self._val_info.setWordWrap(True)
        self._val_info.setStyleSheet(f"color:{C_TEXT_SECONDARY};font-size:11px;")
        l.addWidget(self._val_info)

        btn = QPushButton("Validate & Create Session")
        btn.setObjectName("primary")
        btn.clicked.connect(self._validate_and_create_session)
        l.addWidget(btn)

        l.addStretch()
        return w

    def _browse_raster(self, key):
        path, _ = QFileDialog.getOpenFileName(
            self, f"Select {key} raster", "",
            "GeoTIFF (*.tif *.tiff);;All files (*)")
        if not path:
            return
        setattr(self, f"_{key}_path", path)
        getattr(self, f"_{key}_edit").setText(Path(path).name)
        self.log_msg(f"Loaded {key}: {Path(path).name}")
        if key == "rgb":
            self._load_raster_preview(path, is_rgb=True)

    def _browse_shapefile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Shapefile (.shp)", "",
            "Shapefile (*.shp);;GeoJSON (*.geojson *.json);;All (*)")
        if path:
            self._shp_path = path
            self._shp_edit.setText(Path(path).name)
            self.log_msg(f"Loaded shapefile: {Path(path).name}")

    def _validate_and_create_session(self):
        paths = {}
        for key in ["rgb", "multispectral", "dem"]:
            p = getattr(self, f"_{key}_path", None)
            if not p or not os.path.exists(p):
                QMessageBox.warning(self, "Missing file", f"Please load {key} raster")
                return
            paths[key] = p

        shp_path = getattr(self, "_shp_path", None)
        if not shp_path or not os.path.exists(shp_path):
            QMessageBox.warning(self, "Missing file", "Please load a shapefile")
            return

        self.log_msg("Validating files...")
        warnings = []
        metas = {}
        for key, path in paths.items():
            valid, err = validate_geotiff(path)
            if not valid:
                QMessageBox.critical(self, f"Invalid {key}", f"{Path(path).name}: {err}")
                return
            metas[key] = load_raster_meta(path)
            epsg = metas[key]["crs"].to_epsg()
            self.log_msg(f"  {key}: {Path(path).name} | EPSG:{epsg} | {metas[key]['width']}x{metas[key]['height']}")

        target_crs = metas["multispectral"]["crs"]
        for key in ["rgb", "dem"]:
            if metas[key]["crs"] != target_crs:
                warnings.append(f"{key} CRS differs from multispectral, will reproject")
                self.log_msg(f"  Warning: reprojecting {key} to match multispectral CRS", C_WARN)

        try:
            import geopandas as gpd
            gdf = gpd.read_file(str(shp_path))
            if gdf.crs and gdf.crs != target_crs:
                gdf = gdf.to_crs(target_crs)
                warnings.append("Shapefile reprojected to match raster CRS")
            aoi = unary_union(gdf.geometry.tolist())
            if aoi.geom_type == "MultiPolygon":
                aoi = max(aoi.geoms, key=lambda p: p.area)
        except Exception as e:
            QMessageBox.critical(self, "Shapefile error", str(e))
            return

        session = create_session()
        self.session = session
        self.raster_crs = target_crs
        self.aoi_geo = aoi
        self.ms_path = paths["multispectral"]
        self.rgb_path = paths["rgb"]
        self.dem_path = paths["dem"]

        import shutil
        for key, path in paths.items():
            dst = session["dir"] / "inputs" / f"{key}.tif"
            shutil.copy2(path, str(dst))
            session["rasters"][key] = str(dst)
        shp_dir = session["dir"] / "inputs" / "shapefile"
        shp_dir.mkdir(exist_ok=True)
        shutil.copy2(str(shp_path), str(shp_dir / Path(shp_path).name))
        session["shapefile"] = str(shp_dir / Path(shp_path).name)

        self._val_info.setText(
            f"Session: {session['id']} | CRS: EPSG:{target_crs.to_epsg()}\n"
            f"AOI features: {len(gdf)} | {' | '.join(warnings[:3])}"
        )
        self._val_info.setStyleSheet(f"color:{C_SUCCESS if not warnings else C_WARN};font-size:11px;")
        self.log_msg(f"Session {session['id']} created with {len(gdf)} AOI features", C_SUCCESS)
        self.log_msg(f"CRS: EPSG:{target_crs.to_epsg()}")
        for w in warnings:
            self.log_msg(f"Warning: {w}", C_WARN)

        self._open_step(1)

    # ── Step 2: AOI Extraction ──
    def _build_step2_panel(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(8)
        lbl = QLabel("Clip all rasters to the AOI boundary polygon")
        lbl.setStyleSheet(f"font-weight:600;color:{C_TEXT};")
        l.addWidget(lbl)
        info = QLabel("The shapefile boundary will be used to clip each raster.\n"
                       "Pixels outside the AOI will be set to nodata.")
        info.setStyleSheet(f"color:{C_TEXT_SECONDARY};font-size:11px;")
        info.setWordWrap(True)
        l.addWidget(info)
        self._aol_info = QLabel("")
        self._aol_info.setWordWrap(True)
        self._aol_info.setStyleSheet(f"color:{C_TEXT_SECONDARY};font-size:11px;")
        l.addWidget(self._aol_info)
        btn = QPushButton("Extract AOI")
        btn.setObjectName("primary")
        btn.clicked.connect(self._extract_aoi)
        l.addWidget(btn)
        l.addStretch()
        return w

    def _extract_aoi(self):
        if not self.session or not self.aoi_geo:
            QMessageBox.warning(self, "No session", "Complete Step 1 first")
            return
        session = self.session
        out_dir = session["dir"] / "aol_extracted"
        out_dir.mkdir(parents=True, exist_ok=True)

        self.log_msg("Extracting AOI from rasters...")
        clipped = {}
        for key in ["rgb", "multispectral", "dem"]:
            src = session["rasters"].get(key)
            if not src:
                continue
            dst = str(out_dir / f"{key}_clipped.tif")
            nodata = 0 if key == "rgb" else -9999
            try:
                clip_raster_to_aoi(src, self.aoi_geo, dst, nodata=nodata)
                clipped[key] = dst
                meta = load_raster_meta(dst)
                self.log_msg(f"  {key}: {meta['width']}x{meta['height']}")
            except Exception as e:
                self.log_msg(f"  Error clipping {key}: {e}", C_ERR)

        self.clipped_rasters = clipped

        aoi_geojson_path = str(out_dir / "aoi_boundary.geojson")
        import json, geopandas as gpd
        gdf = gpd.GeoDataFrame({"id": [0]}, geometry=[self.aoi_geo], crs=self.raster_crs)
        gdf.to_file(aoi_geojson_path, driver="GeoJSON")
        self.log_msg(f"AOI boundary saved: aoi_boundary.geojson")

        bounds = self.aoi_geo.bounds
        self._aol_info.setText(
            f"AOI extent: "
            f"X [{bounds[0]:.2f}, {bounds[2]:.2f}]  "
            f"Y [{bounds[1]:.2f}, {bounds[3]:.2f}]\n"
            f"Clipped: {', '.join(clipped.keys())}"
        )
        self.log_msg("AOI extraction complete", C_SUCCESS)
        self._open_step(2)

    # ── Step 3: Grid Tiling ──
    def _build_step3_panel(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(8)
        lbl = QLabel("Generate 3.5 × 3.5 m tile grid")
        lbl.setStyleSheet(f"font-weight:600;color:{C_TEXT};")
        l.addWidget(lbl)

        row = QHBoxLayout()
        row.addWidget(QLabel("Tile size (m):"))
        self._tile_size_spin = QDoubleSpinBox()
        self._tile_size_spin.setRange(0.5, 50)
        self._tile_size_spin.setValue(DEFAULT_TILE_SIZE_M)
        self._tile_size_spin.setSingleStep(0.5)
        row.addWidget(self._tile_size_spin)
        l.addLayout(row)

        self._tile_info = QLabel("")
        self._tile_info.setWordWrap(True)
        self._tile_info.setStyleSheet(f"color:{C_TEXT_SECONDARY};font-size:11px;")
        l.addWidget(self._tile_info)

        btn = QPushButton("Generate Grid")
        btn.setObjectName("primary")
        btn.clicked.connect(self._generate_grid)
        l.addWidget(btn)
        l.addStretch()
        return w

    def _generate_grid(self):
        if not self.clipped_rasters:
            QMessageBox.warning(self, "No clipped rasters", "Complete Step 2 first")
            return
        ms_path = self.clipped_rasters.get("multispectral")
        if not ms_path:
            QMessageBox.warning(self, "Missing clipped raster")
            return

        tile_m = self._tile_size_spin.value()
        self.tiles, metric_crs = compute_tile_grid(self.aoi_geo, self.raster_crs, tile_m)
        self.tile_geometries = [t["geometry_src"] for t in self.tiles]

        session = self.session
        geojson = generate_tile_geojson(self.tiles, metric_crs)
        grid_path = session["dir"] / "tiles" / "tile_grid.geojson"
        with open(str(grid_path), "w") as f:
            json.dump(geojson, f, indent=2)
        self.canvas.set_tile_grid(self.tile_geometries)

        full = sum(1 for t in self.tiles if t["status"] == "full")
        partial = sum(1 for t in self.tiles if t["status"] == "partial")
        self._tile_info.setText(
            f"Total tiles: {len(self.tiles)}  |  Full: {full}  |  Partial: {partial}\n"
            f"Grid: {tile_m}m × {tile_m}m  |  CRS: {metric_crs}"
        )
        self.log_msg(f"Grid generated: {len(self.tiles)} tiles ({full} full, {partial} partial)", C_SUCCESS)
        self._open_step(3)

    # ── Step 4: Feature Extraction ──
    def _build_step4_panel(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(8)
        lbl = QLabel("Extract NDVI, GNDVI, DEM, RGB features")
        lbl.setStyleSheet(f"font-weight:600;color:{C_TEXT};")
        l.addWidget(lbl)

        self._feat_info = QLabel("")
        self._feat_info.setWordWrap(True)
        self._feat_info.setStyleSheet(f"color:{C_TEXT_SECONDARY};font-size:11px;")
        l.addWidget(self._feat_info)

        btn = QPushButton("Extract Features")
        btn.setObjectName("primary")
        btn.clicked.connect(self._extract_features)
        l.addWidget(btn)
        l.addStretch()
        return w

    def _extract_features(self):
        if not self.tiles or not self.clipped_rasters:
            QMessageBox.warning(self, "No tiles", "Generate grid first")
            return

        session = self.session
        feat_dir = session["dir"] / "features"
        self.log_msg("Extracting features for all tiles...")

        def _work():
            total = len(self.tiles)
            ms_path = self.clipped_rasters.get("multispectral")
            dem_path = self.clipped_rasters.get("dem")
            rgb_path = self.clipped_rasters.get("rgb")
            all_stats = []
            res = get_resolution(ms_path) if ms_path else 0.05

            for i, t in enumerate(self.tiles):
                if self._worker._cancelled:
                    return
                self._worker.progress.emit(i + 1, total, f"Tile {i+1}/{total}")
                tile_id = t["tile_id"]
                bounds = t["bounds_src"]
                dem_data = None
                rgb_data = None

                with rasterio.open(str(ms_path)) as ds:
                    win = from_bounds(
                        bounds[0], bounds[1], bounds[2], bounds[3], ds.transform)
                    win = win.intersection(rasterio.windows.Window(0, 0, ds.width, ds.height))
                    ms_data = ds.read(window=win)
                    ms_transform = ds.window_transform(win)

                red = ms_data[BAND_CONFIG["red_index"] - 1].astype(np.float32)
                green = ms_data[BAND_CONFIG["green_index"] - 1].astype(np.float32)
                nir = ms_data[BAND_CONFIG["nir_index"] - 1].astype(np.float32) if ms_data.shape[0] >= BAND_CONFIG["nir_index"] else red

                ndvi = compute_ndvi(nir, red)
                gndvi = compute_gndvi(nir, green)

                from app.core.raster_utils import write_tile
                for arr, name, nodata_val in [
                    (ndvi, "ndvi", -9999), (gndvi, "gndvi", -9999)]:
                    out = str(feat_dir / name / f"{tile_id}.tif")
                    write_tile(arr, ms_transform, self.raster_crs, out, nodata=nodata_val, dtype="float32")

                if dem_path:
                    with rasterio.open(str(dem_path)) as dd:
                        win2 = from_bounds(
                            bounds[0], bounds[1], bounds[2], bounds[3], dd.transform)
                        win2 = win2.intersection(rasterio.windows.Window(0, 0, dd.width, dd.height))
                        if win2.width > 0 and win2.height > 0:
                            dem_data = dd.read(1, window=win2)
                            dem_transform = dd.window_transform(win2)
                            out = str(feat_dir / "dem" / f"{tile_id}.tif")
                            write_tile(dem_data, dem_transform, self.raster_crs, out, nodata=-9999)

                if rgb_path:
                    with rasterio.open(str(rgb_path)) as rd:
                        win3 = from_bounds(
                            bounds[0], bounds[1], bounds[2], bounds[3], rd.transform)
                        win3 = win3.intersection(rasterio.windows.Window(0, 0, rd.width, rd.height))
                        if win3.width > 0 and win3.height > 0:
                            rgb_data = rd.read(list(range(1, min(rd.count, 3) + 1)), window=win3)
                            rgb_transform = rd.window_transform(win3)
                            if rgb_data.dtype == np.uint16:
                                rgb_data = normalize_uint16_to_uint8(rgb_data)
                            out = str(feat_dir / "rgb" / f"{tile_id}.tif")
                            write_tile(rgb_data, rgb_transform, self.raster_crs, out)

                tile_data = {"ndvi": ndvi, "gndvi": gndvi}
                if dem_data is not None:
                    tile_data["dem"] = dem_data
                if rgb_data is not None:
                    tile_data["rgb"] = rgb_data

                fv = compute_tile_feature_vector(tile_data, t, res)
                all_stats.append(fv)

            df = pd.DataFrame(all_stats)
            df.to_csv(str(session["dir"] / "features" / "tile_stats.csv"), index=False)
            json_path = str(session["dir"] / "features" / "feature_vectors.json")
            with open(json_path, "w") as f:
                json.dump(all_stats, f, indent=2, default=float)

            self.features_done = True
            self._worker.finished.emit("Features extracted", {"count": len(all_stats)})

        self._worker.work_fn = _work
        self._worker.start()

    def _on_worker_finished(self, msg, data):
        self.export_pbar.setVisible(False)
        self.log_msg(str(msg), C_SUCCESS)
        count = data.get("count", 0) if isinstance(data, dict) else 0
        self._feat_info.setText(f"Features extracted for {count} tiles\nSaved to features/ folder")
        self.status(str(msg))

    def _on_worker_error(self, err):
        self.export_pbar.setVisible(False)
        self.log_msg("Error: " + err[-300:], C_ERR)

    # ── Step 5: Download ──
    def _build_step5_panel(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(8)
        lbl = QLabel("Download tiles to output folder")
        lbl.setStyleSheet(f"font-weight:600;color:{C_TEXT};")
        l.addWidget(lbl)

        row = QHBoxLayout()
        self._out_dir_edit = QLineEdit()
        self._out_dir_edit.setPlaceholderText("Choose output folder...")
        row.addWidget(self._out_dir_edit)
        btn = QPushButton("Browse")
        btn.clicked.connect(self._browse_output)
        row.addWidget(btn)
        l.addLayout(row)

        self._download_info = QLabel("")
        self._download_info.setWordWrap(True)
        self._download_info.setStyleSheet(f"color:{C_TEXT_SECONDARY};font-size:11px;")
        l.addWidget(self._download_info)

        btn2 = QPushButton("Download Tiles")
        btn2.setObjectName("primary")
        btn2.clicked.connect(self._download_tiles)
        l.addWidget(btn2)
        l.addStretch()
        return w

    def _browse_output(self):
        d = QFileDialog.getExistingDirectory(self, "Select output folder")
        if d:
            self._out_dir_edit.setText(d)

    def _download_tiles(self):
        out_dir = self._out_dir_edit.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "No output", "Choose an output folder first")
            return
        session = self.session
        feat_dir = session["dir"] / "features"
        out = Path(out_dir)

        folders = [
            ("ndvi_tiles", feat_dir / "ndvi"),
            ("gndvi_tiles", feat_dir / "gndvi"),
            ("dem_tiles", feat_dir / "dem"),
            ("rgb_tiles", feat_dir / "rgb"),
        ]

        count = 0
        for name, src in folders:
            if src.exists():
                dst = out / name
                dst.mkdir(parents=True, exist_ok=True)
                for f in src.glob("*.tif"):
                    shutil.copy2(str(f), str(dst / f.name))
                    count += 1

        shp_src = session["dir"] / "aol_extracted"
        if shp_src.exists():
            dst = out / "shapefiles"
            dst.mkdir(parents=True, exist_ok=True)
            for f in shp_src.glob("*.geojson"):
                shutil.copy2(str(f), str(dst / f.name))

        stats_dst = out / "stats"
        stats_dst.mkdir(parents=True, exist_ok=True)
        for f in (session["dir"] / "features").glob("*.json"):
            shutil.copy2(str(f), str(stats_dst / f.name))
        for f in (session["dir"] / "features").glob("*.csv"):
            shutil.copy2(str(f), str(stats_dst / f.name))

        self._download_info.setText(f"Downloaded {count} tiles to:\n{out_dir}")
        self.log_msg(f"Downloaded {count} tiles to {out_dir}", C_SUCCESS)

    # ── Step 6: Compute Statistics ──
    def _build_step6_panel(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(8)
        lbl = QLabel("Compute feature vectors and correlation matrix")
        lbl.setStyleSheet(f"font-weight:600;color:{C_TEXT};")
        l.addWidget(lbl)

        self._stats_info = QLabel("")
        self._stats_info.setWordWrap(True)
        self._stats_info.setStyleSheet(f"color:{C_TEXT_SECONDARY};font-size:11px;")
        l.addWidget(self._stats_info)

        btn = QPushButton("Compute Statistics & Save CSV")
        btn.setObjectName("primary")
        btn.clicked.connect(self._compute_stats)
        l.addWidget(btn)
        l.addStretch()
        return w

    def _compute_stats(self):
        session = self.session
        json_path = session["dir"] / "features" / "feature_vectors.json"
        if not json_path.exists():
            QMessageBox.warning(self, "No features", "Extract features first (Step 4)")
            return

        with open(str(json_path)) as f:
            all_stats = json.load(f)
        df = pd.DataFrame(all_stats)
        csv_path = str(session["dir"] / "ml" / "feature_vectors.csv")
        df.to_csv(csv_path, index=False)

        corr = compute_correlation_matrix(df)
        corr_path = str(session["dir"] / "ml" / "correlation_matrix.json")
        with open(corr_path, "w") as f:
            json.dump(corr, f, indent=2, default=float)

        shape = df.shape
        self._stats_info.setText(
            f"Feature vectors: {shape[0]} tiles × {shape[1]} features\n"
            f"Saved: feature_vectors.csv\n"
            f"Correlation matrix: {len(corr.get('columns', []))} features"
        )
        self.log_msg(f"Statistics computed: {shape[0]} tiles × {shape[1]} features", C_SUCCESS)

    # ── Step 7: ML Vigor Analysis ──
    def _build_step7_panel(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(8)
        lbl = QLabel("Train ML model & predict crop vigor")
        lbl.setStyleSheet(f"font-weight:600;color:{C_TEXT};")
        l.addWidget(lbl)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Training mode:"))
        self._ml_mode = QComboBox()
        self._ml_mode.addItems(["Unsupervised (K-Means)", "Supervised (Random Forest)"])
        mode_row.addWidget(self._ml_mode)
        l.addLayout(mode_row)

        self._ml_info = QLabel("")
        self._ml_info.setWordWrap(True)
        self._ml_info.setStyleSheet(f"color:{C_TEXT_SECONDARY};font-size:11px;")
        l.addWidget(self._ml_info)

        train_btn = QPushButton("Train Model")
        train_btn.setObjectName("primary")
        train_btn.clicked.connect(self._train_model)
        l.addWidget(train_btn)

        predict_btn = QPushButton("Run Prediction")
        predict_btn.setObjectName("success")
        predict_btn.clicked.connect(self._run_prediction)
        l.addWidget(predict_btn)

        self._vigor_info = QLabel("")
        self._vigor_info.setWordWrap(True)
        self._vigor_info.setStyleSheet(f"color:{C_TEXT_SECONDARY};font-size:11px;")
        l.addWidget(self._vigor_info)

        l.addStretch()
        return w

    def _train_model(self):
        session = self.session
        csv_path = session["dir"] / "ml" / "feature_vectors.csv"
        if not csv_path.exists():
            QMessageBox.warning(self, "No data", "Compute statistics first (Step 6)")
            return

        X, df, feature_cols = build_feature_matrix(str(csv_path))
        if X.shape[0] < 4:
            QMessageBox.warning(self, "Too few tiles", f"Need at least 4 tiles, got {X.shape[0]}")
            return

        trainer = VigorTrainer()
        is_supervised = self._ml_mode.currentIndex() == 1

        if is_supervised:
            labels_path = session["dir"] / "inputs" / "labeled_tiles.csv"
            if labels_path.exists():
                labels_df = pd.read_csv(str(labels_path))
                merged = df.merge(labels_df, on="tile_id", how="inner")
                y = merged["vigor_class"].values
                trainer.label_map = {i: str(i) for i in sorted(y.unique())}
                metrics = trainer.train_supervised(X.loc[merged.index], y)
                self._ml_info.setText(
                    f"Supervised RF: accuracy={metrics.get('accuracy', 0):.3f}\n"
                    f"Cross-val F1: {metrics.get('cross_val_f1', 'N/A')}"
                )
            else:
                QMessageBox.warning(self, "No labels", "For supervised mode, provide labeled_tiles.csv in inputs/")
                return
        else:
            labels, metrics = trainer.train_unsupervised(X)
            self._ml_info.setText(
                f"Unsupervised K-Means: {metrics.get('n_clusters', 4)} clusters\n"
                f"Inertia: {metrics.get('inertia', 0):.1f}"
            )

        trainer.save(
            session["dir"] / "ml" / "vigor_model.joblib",
            session["dir"] / "ml" / "scaler.joblib",
        )
        self.ml_model = trainer
        self.log_msg(f"Model trained ({'supervised' if is_supervised else 'unsupervised'})", C_SUCCESS, switch_tab=True)

    def _run_prediction(self):
        if not self.ml_model:
            QMessageBox.warning(self, "No model", "Train a model first")
            return

        session = self.session
        csv_path = session["dir"] / "ml" / "feature_vectors.csv"
        predictor = VigorPredictor(self.ml_model)
        preds = predictor.predict(str(csv_path))
        preds_path = str(session["dir"] / "ml" / "predictions.csv")
        preds.to_csv(preds_path, index=False)

        grid_path = session["dir"] / "tiles" / "tile_grid.geojson"
        vigor_geojson = predictor.to_geojson(str(grid_path), preds_path)
        vg_path = str(session["dir"] / "ml" / "vigor_map.geojson")
        with open(vg_path, "w") as f:
            json.dump(vigor_geojson, f, indent=2)

        geo_polys = []
        class_vals = []
        for feat in vigor_geojson.get("features", []):
            coords = feat["geometry"]["coordinates"][0]
            poly = Polygon(coords)
            geo_polys.append(poly)
            class_vals.append(feat["properties"].get("vigor_class", 0))

        self.canvas.set_vigor_overlay(geo_polys, class_vals)

        counts = {}
        for v in class_vals:
            label = VIGOR_LABELS.get(v, f"Class {v}")
            counts[label] = counts.get(label, 0) + 1

        info = "Vigor class distribution:\n" + "\n".join(f"  {k}: {v}" for k, v in sorted(counts.items()))
        self._vigor_info.setText(info)
        self.log_msg(f"Prediction complete: {len(preds)} tiles classified", C_SUCCESS)
        self.tabs.setCurrentIndex(0)

    # ── Shared helpers ──
    def _load_raster_preview(self, path, is_rgb=False):
        self.load_pbar.setVisible(True)
        self.load_pbar.setValue(0)
        self._load_thread = RasterLoadThread(path, is_rgb=is_rgb)
        self._load_thread.progress.connect(self.load_pbar.setValue)
        self._load_thread.done.connect(self._on_preview_loaded)
        self._load_thread.error.connect(lambda e: (
            self.log_msg("Preview error: " + e.splitlines()[-1][:100], C_ERR),
            self.load_pbar.setVisible(False)
        ))
        self._load_thread.start()

    def _on_preview_loaded(self, pixmap, bounds, crs, w, h, path):
        self.canvas.load_image(pixmap, bounds, crs)
        self.raster_crs = crs
        self.load_pbar.setVisible(False)

    def _on_aoi_changed(self, poly):
        self.aoi_geo = poly

    def _on_coord_moved(self, gx, gy):
        self.coord_lbl.setText(f"X: {gx:.4f}   Y: {gy:.4f}")
