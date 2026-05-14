#!/usr/bin/env python3
"""
GIS Tile Cutter — Desktop App
Loads R / G / NIR / DEM GeoTIFFs, lets user select an AOI,
and exports 3.5×3.5 km tiles (single-band or all-4-stacked).
"""

import sys
import os
import math
import json
import traceback
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.transform import from_bounds as transform_from_bounds
from rasterio.crs import CRS
from rasterio.warp import transform_bounds, reproject, Resampling
from shapely.geometry import box, Polygon, mapping
from pyproj import Transformer

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QLabel, QPushButton, QFileDialog, QComboBox,
    QGroupBox, QGridLayout, QLineEdit, QSpinBox, QDoubleSpinBox,
    QProgressBar, QStatusBar, QTabWidget, QTextEdit, QCheckBox,
    QScrollArea, QFrame, QSizePolicy, QMessageBox, QToolButton,
    QButtonGroup, QRadioButton
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRectF, QPointF, QTimer
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPixmap, QImage,
    QFont, QCursor, QPainterPath, QPolygonF
)


# ── Colour palette ────────────────────────────────────────────────────────────
C_BG        = "#1e1e2e"
C_SURFACE   = "#2a2a3e"
C_PANEL     = "#252535"
C_ACCENT    = "#7c6af7"
C_ACCENT2   = "#5ec4b0"
C_WARN      = "#f0a23a"
C_ERR       = "#e05c5c"
C_TEXT      = "#d4d4e8"
C_MUTED     = "#7878a0"
C_BORDER    = "#3a3a5a"
C_SEL       = "#7c6af740"
C_TILE_LINE = "#7c6af7"
C_TILE_FILL = "#7c6af718"
C_AOI_LINE  = "#5ec4b0"
C_AOI_FILL  = "#5ec4b028"


# ── Stylesheet ────────────────────────────────────────────────────────────────
STYLE = f"""
QMainWindow, QWidget {{
    background: {C_BG};
    color: {C_TEXT};
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}}
QGroupBox {{
    border: 1px solid {C_BORDER};
    border-radius: 8px;
    margin-top: 12px;
    padding: 8px;
    font-weight: 600;
    color: {C_TEXT};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {C_ACCENT};
}}
QPushButton {{
    background: {C_SURFACE};
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    padding: 6px 14px;
    color: {C_TEXT};
}}
QPushButton:hover {{ background: {C_ACCENT}; color: white; border-color: {C_ACCENT}; }}
QPushButton:pressed {{ background: #5a4ed4; }}
QPushButton:disabled {{ color: {C_MUTED}; }}
QPushButton#primary {{
    background: {C_ACCENT};
    color: white;
    border-color: {C_ACCENT};
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: #6a58e8; }}
QPushButton#danger {{ background: {C_ERR}; color: white; border-color: {C_ERR}; }}
QPushButton:checked {{
    background: {C_ACCENT};
    color: white;
    border-color: {C_ACCENT};
}}
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {{
    background: {C_SURFACE};
    border: 1px solid {C_BORDER};
    border-radius: 5px;
    padding: 4px 8px;
    color: {C_TEXT};
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {C_ACCENT};
}}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background: {C_SURFACE};
    border: 1px solid {C_BORDER};
    selection-background-color: {C_ACCENT};
}}
QProgressBar {{
    background: {C_SURFACE};
    border: 1px solid {C_BORDER};
    border-radius: 5px;
    height: 14px;
    text-align: center;
    color: {C_TEXT};
}}
QProgressBar::chunk {{ background: {C_ACCENT}; border-radius: 4px; }}
QTabWidget::pane {{
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    background: {C_PANEL};
}}
QTabBar::tab {{
    background: {C_SURFACE};
    border: 1px solid {C_BORDER};
    border-bottom: none;
    border-radius: 5px 5px 0 0;
    padding: 5px 14px;
    color: {C_MUTED};
}}
QTabBar::tab:selected {{ background: {C_PANEL}; color: {C_TEXT}; }}
QTextEdit {{
    background: {C_SURFACE};
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    color: {C_TEXT};
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
}}
QScrollBar:vertical {{
    background: {C_SURFACE};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {C_BORDER};
    border-radius: 4px;
    min-height: 20px;
}}
QCheckBox {{ color: {C_TEXT}; spacing: 6px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    background: {C_SURFACE};
}}
QCheckBox::indicator:checked {{
    background: {C_ACCENT};
    border-color: {C_ACCENT};
}}
QRadioButton {{ color: {C_TEXT}; spacing: 6px; }}
QRadioButton::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {C_BORDER};
    border-radius: 7px;
    background: {C_SURFACE};
}}
QRadioButton::indicator:checked {{
    background: {C_ACCENT};
    border-color: {C_ACCENT};
}}
QSplitter::handle {{ background: {C_BORDER}; }}
QLabel#section {{ color: {C_ACCENT}; font-weight: 600; font-size: 11px; text-transform: uppercase; }}
QLabel#coord {{ font-family: 'Consolas', monospace; color: {C_ACCENT2}; font-size: 11px; }}
"""


# ── Map canvas widget ─────────────────────────────────────────────────────────
class MapCanvas(QWidget):
    """
    Displays a raster overview and lets the user:
      • Pan  (right-drag / middle-drag)
      • Zoom (scroll wheel)
      • Draw a rectangle AOI
      • Draw a free polygon AOI
      • Draw any free shape (freehand)
    Emits aoi_changed(polygon_in_geo_coords) when selection updates.
    """
    aoi_changed = pyqtSignal(object)   # Shapely Polygon in dataset CRS
    coord_moved = pyqtSignal(float, float)  # lon, lat under cursor

    TOOL_NONE  = "none"
    TOOL_PAN   = "pan"
    TOOL_RECT  = "rect"
    TOOL_POLY  = "poly"
    TOOL_FREE  = "free"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(500, 400)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

        # raster state
        self.overview: QPixmap | None = None  # rendered overview
        self.raster_bounds = None   # (left, bottom, right, top) in dataset CRS
        self.raster_crs    = None
        self.dataset_width = 0
        self.dataset_height = 0

        # view state
        self.offset  = QPointF(0, 0)  # pan offset in screen px
        self.scale   = 1.0            # zoom scale

        # interaction
        self.tool = self.TOOL_RECT
        self._pan_start = None
        self._pan_offset_start = None

        # AOI drawing state
        self._rect_start: QPointF | None = None
        self._rect_cur:   QPointF | None = None
        self._poly_pts:   list[QPointF]  = []
        self._free_pts:   list[QPointF]  = []
        self._dragging_free = False

        # committed AOI (screen coords for rendering, geo for output)
        self.aoi_screen: list[QPointF] = []
        self.aoi_geo:    Polygon | None = None

        # tile grid overlay
        self.tile_polys_screen: list[list[QPointF]] = []

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ── raster loading ────────────────────────────────────────────────────────
    def load_overview(self, pixmap: QPixmap, bounds, crs):
        """Feed a pre-rendered overview pixmap + geographic bounds."""
        self.overview = pixmap
        self.raster_bounds = bounds  # (left, bottom, right, top)
        self.raster_crs = crs
        self.aoi_screen = []
        self.aoi_geo = None
        self.tile_polys_screen = []
        self._fit_view()
        self.update()

    def _fit_view(self):
        if self.overview is None:
            return
        w, h = self.width(), self.height()
        iw, ih = self.overview.width(), self.overview.height()
        self.scale = min(w / iw, h / ih) * 0.95
        self.offset = QPointF(
            (w - iw * self.scale) / 2,
            (h - ih * self.scale) / 2
        )

    def resizeEvent(self, e):
        self._fit_view()
        self._rebuild_tile_overlay()
        super().resizeEvent(e)

    # ── coordinate helpers ────────────────────────────────────────────────────
    def _screen_to_geo(self, pt: QPointF):
        """Screen px → geo coords in raster CRS."""
        if self.overview is None or self.raster_bounds is None:
            return None, None
        iw, ih = self.overview.width(), self.overview.height()
        ix = (pt.x() - self.offset.x()) / self.scale
        iy = (pt.y() - self.offset.y()) / self.scale
        left, bottom, right, top = self.raster_bounds
        gx = left + (ix / iw) * (right - left)
        gy = top  - (iy / ih) * (top - bottom)
        return gx, gy

    def _geo_to_screen(self, gx, gy) -> QPointF:
        if self.overview is None or self.raster_bounds is None:
            return QPointF(0, 0)
        iw, ih = self.overview.width(), self.overview.height()
        left, bottom, right, top = self.raster_bounds
        ix = ((gx - left) / (right - left)) * iw
        iy = ((top - gy) / (top - bottom)) * ih
        return QPointF(self.offset.x() + ix * self.scale,
                       self.offset.y() + iy * self.scale)

    def _screen_pts_to_geo(self, pts: list[QPointF]) -> Polygon | None:
        coords = [self._screen_to_geo(p) for p in pts]
        if any(c[0] is None for c in coords):
            return None
        return Polygon(coords)

    # ── tile overlay ─────────────────────────────────────────────────────────
    def set_tile_grid(self, tile_geo_polys: list[Polygon]):
        """Receive tile polygons in raster CRS and convert to screen."""
        self._tile_geo = tile_geo_polys
        self._rebuild_tile_overlay()
        self.update()

    def _rebuild_tile_overlay(self):
        if not hasattr(self, '_tile_geo'):
            return
        self.tile_polys_screen = []
        for poly in self._tile_geo:
            pts = [self._geo_to_screen(x, y) for x, y in poly.exterior.coords]
            self.tile_polys_screen.append(pts)

    def clear_tiles(self):
        self.tile_polys_screen = []
        if hasattr(self, '_tile_geo'):
            del self._tile_geo
        self.update()

    # ── painting ──────────────────────────────────────────────────────────────
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # background
        p.fillRect(self.rect(), QColor(C_BG))

        if self.overview is None:
            p.setPen(QColor(C_MUTED))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Load a GeoTIFF to begin\n\n"
                       "File → Load Band...")
            return

        # raster overview
        iw = self.overview.width()  * self.scale
        ih = self.overview.height() * self.scale
        p.drawPixmap(int(self.offset.x()), int(self.offset.y()),
                     int(iw), int(ih), self.overview)

        # tile grid
        if self.tile_polys_screen:
            p.setPen(QPen(QColor(C_TILE_LINE), 1.0, Qt.PenStyle.SolidLine))
            p.setBrush(QBrush(QColor(C_TILE_FILL)))
            for pts in self.tile_polys_screen:
                poly = QPolygonF(pts)
                p.drawPolygon(poly)

        # committed AOI
        if self.aoi_screen:
            p.setPen(QPen(QColor(C_AOI_LINE), 2.0))
            p.setBrush(QBrush(QColor(C_AOI_FILL)))
            p.drawPolygon(QPolygonF(self.aoi_screen))

        # in-progress drawing
        self._draw_in_progress(p)

    def _draw_in_progress(self, p: QPainter):
        pen = QPen(QColor(C_AOI_LINE), 1.5, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(QBrush(QColor(C_AOI_FILL)))

        if self.tool == self.TOOL_RECT and self._rect_start and self._rect_cur:
            r = QRectF(self._rect_start, self._rect_cur).normalized()
            p.drawRect(r)

        elif self.tool == self.TOOL_POLY and self._poly_pts:
            if len(self._poly_pts) > 1:
                poly = QPolygonF(self._poly_pts)
                p.drawPolyline(poly)
            # dots
            p.setBrush(QBrush(QColor(C_AOI_LINE)))
            for pt in self._poly_pts:
                p.drawEllipse(pt, 4, 4)

        elif self.tool == self.TOOL_FREE and self._free_pts and len(self._free_pts) > 1:
            poly = QPolygonF(self._free_pts)
            p.drawPolyline(poly)

    # ── mouse events ─────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        pos = e.position()
        btn = e.button()

        if btn == Qt.MouseButton.MiddleButton or (
                btn == Qt.MouseButton.RightButton and self.tool != self.TOOL_POLY):
            self._pan_start = pos
            self._pan_offset_start = QPointF(self.offset)
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            return

        if btn != Qt.MouseButton.LeftButton:
            return

        if self.tool == self.TOOL_RECT:
            self._rect_start = pos
            self._rect_cur   = pos

        elif self.tool == self.TOOL_POLY:
            self._poly_pts.append(QPointF(pos))

        elif self.tool == self.TOOL_FREE:
            self._free_pts = [QPointF(pos)]
            self._dragging_free = True

    def mouseMoveEvent(self, e):
        pos = e.position()

        # emit coord
        gx, gy = self._screen_to_geo(QPointF(pos))
        if gx is not None:
            self.coord_moved.emit(gx, gy)

        # pan
        if self._pan_start is not None:
            delta = pos - self._pan_start
            self.offset = self._pan_offset_start + delta
            self._rebuild_tile_overlay()
            self.update()
            return

        if self.tool == self.TOOL_RECT and self._rect_start:
            self._rect_cur = pos
            self.update()

        elif self.tool == self.TOOL_FREE and self._dragging_free:
            self._free_pts.append(QPointF(pos))
            self.update()

    def mouseReleaseEvent(self, e):
        pos = e.position()
        btn = e.button()

        if self._pan_start is not None and (
                btn == Qt.MouseButton.MiddleButton or btn == Qt.MouseButton.RightButton):
            self._pan_start = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            return

        if btn != Qt.MouseButton.LeftButton:
            return

        if self.tool == self.TOOL_RECT and self._rect_start:
            r = QRectF(self._rect_start, QPointF(pos)).normalized()
            pts = [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]
            self._commit_aoi(pts)
            self._rect_start = None
            self._rect_cur   = None

        elif self.tool == self.TOOL_FREE and self._dragging_free:
            self._dragging_free = False
            if len(self._free_pts) > 3:
                self._commit_aoi(self._free_pts)
            self._free_pts = []

    def mouseDoubleClickEvent(self, e):
        if self.tool == self.TOOL_POLY and len(self._poly_pts) >= 3:
            self._commit_aoi(self._poly_pts)
            self._poly_pts = []

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self._poly_pts = []
            self._free_pts = []
            self._rect_start = None
            self.update()
        elif e.key() == Qt.Key.Key_Return and self.tool == self.TOOL_POLY:
            if len(self._poly_pts) >= 3:
                self._commit_aoi(self._poly_pts)
                self._poly_pts = []

    def wheelEvent(self, e):
        delta = e.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        pos = e.position()
        # zoom around cursor
        self.offset = pos + (self.offset - pos) * factor
        self.scale *= factor
        self._rebuild_tile_overlay()
        self.update()

    def _commit_aoi(self, pts: list[QPointF]):
        self.aoi_screen = [QPointF(p) for p in pts]
        self.aoi_geo = self._screen_pts_to_geo(pts)
        self.update()
        if self.aoi_geo:
            self.aoi_changed.emit(self.aoi_geo)

    def reset_view(self):
        self._fit_view()
        self.update()


# ── Band loader thread ────────────────────────────────────────────────────────
class BandLoader(QThread):
    done     = pyqtSignal(QPixmap, object, object, int, int, str)  # pixmap, bounds, crs, w, h, path
    error    = pyqtSignal(str)
    progress = pyqtSignal(int)

    def __init__(self, path, band_index=1):
        super().__init__()
        self.path = path
        self.band_index = band_index

    def run(self):
        try:
            self.progress.emit(10)
            with rasterio.open(self.path) as ds:
                crs    = ds.crs
                left, bottom, right, top = ds.bounds
                w, h   = ds.width, ds.height

                # build overview — downsample to max 1024 px
                max_dim = 1024
                scale   = min(max_dim / w, max_dim / h, 1.0)
                ow = max(int(w * scale), 1)
                oh = max(int(h * scale), 1)

                self.progress.emit(30)
                data = ds.read(
                    self.band_index,
                    out_shape=(oh, ow),
                    resampling=Resampling.average
                )
                nodata = ds.nodata

            self.progress.emit(60)
            # normalise to 0-255
            if nodata is not None:
                mask = data == nodata
                data = data.astype(float)
                data[mask] = np.nan
            else:
                data = data.astype(float)

            valid = data[~np.isnan(data)]
            if valid.size == 0:
                raise ValueError("Band contains no valid data")
            lo, hi = np.nanpercentile(data, 2), np.nanpercentile(data, 98)
            if lo == hi:
                hi = lo + 1
            normed = np.clip((data - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
            normed[np.isnan(data)] = 0

            self.progress.emit(80)
            # colorise with a warm colormap for visual appeal
            rgba = np.zeros((oh, ow, 4), dtype=np.uint8)
            rgba[..., 0] = normed
            rgba[..., 1] = (normed * 0.85).astype(np.uint8)
            rgba[..., 2] = (normed * 0.65).astype(np.uint8)
            rgba[..., 3] = 255

            img = QImage(rgba.tobytes(), ow, oh, ow * 4, QImage.Format.Format_RGBA8888)
            pix = QPixmap.fromImage(img)

            self.progress.emit(100)
            self.done.emit(pix, (left, bottom, right, top), crs, w, h, self.path)

        except Exception as ex:
            self.error.emit(traceback.format_exc())


# ── Tiling worker ─────────────────────────────────────────────────────────────
class TilingWorker(QThread):
    progress  = pyqtSignal(int, int, str)   # current, total, msg
    tile_done = pyqtSignal(str)             # path of written tile
    finished  = pyqtSignal(int, str)        # n_tiles, output_dir
    error     = pyqtSignal(str)

    def __init__(self, band_paths: dict, aoi_geo: Polygon,
                 tile_km: float, output_dir: str,
                 output_mode: str,   # "single" | "all4" | "both"
                 out_crs_epsg: int | None = None):
        super().__init__()
        self.band_paths    = band_paths       # {"R": path, "G": path, ...}
        self.aoi_geo       = aoi_geo
        self.tile_km       = tile_km
        self.output_dir    = output_dir
        self.output_mode   = output_mode
        self.out_crs_epsg  = out_crs_epsg
        self._cancelled    = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            out = Path(self.output_dir)
            out.mkdir(parents=True, exist_ok=True)

            # open first band to get CRS/bounds
            first_path = next(iter(self.band_paths.values()))
            with rasterio.open(first_path) as ref:
                src_crs = ref.crs
                src_bounds = ref.bounds

            # convert AOI to src_crs if needed (it already is — drawn on canvas)
            aoi = self.aoi_geo
            aoi_bounds = aoi.bounds  # (minx, miny, maxx, maxy)

            # determine metric CRS for tiling (UTM or given EPSG)
            if self.out_crs_epsg:
                metric_crs = CRS.from_epsg(self.out_crs_epsg)
            else:
                # auto-pick UTM zone from centroid
                cx = (aoi_bounds[0] + aoi_bounds[2]) / 2
                cy = (aoi_bounds[1] + aoi_bounds[3]) / 2
                # transform centroid to WGS84 to get lon
                if not src_crs.is_geographic:
                    t = Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
                    lon, lat = t.transform(cx, cy)
                else:
                    lon, lat = cx, cy
                zone = int((lon + 180) / 6) + 1
                hemi = 326 if lat >= 0 else 327
                metric_crs = CRS.from_epsg(hemi * 100 + zone)

            # transform AOI bounds → metric
            t_src_metric = Transformer.from_crs(src_crs, metric_crs, always_xy=True)
            t_metric_src = Transformer.from_crs(metric_crs, src_crs, always_xy=True)

            xs, ys = t_src_metric.transform(
                [aoi_bounds[0], aoi_bounds[2]],
                [aoi_bounds[1], aoi_bounds[3]]
            )
            m_minx, m_maxx = min(xs), max(xs)
            m_miny, m_maxy = min(ys), max(ys)

            tile_m = self.tile_km * 1000.0

            cols = math.ceil((m_maxx - m_minx) / tile_m)
            rows = math.ceil((m_maxy - m_miny) / tile_m)
            total_tiles = rows * cols
            if total_tiles > 2000:
                self.error.emit(
                    f"Too many tiles ({total_tiles}). Reduce AOI or increase tile size.")
                return

            written = 0
            tile_index = []

            band_names = list(self.band_paths.keys())

            for r in range(rows):
                for c in range(cols):
                    if self._cancelled:
                        return

                    t_minx = m_minx + c * tile_m
                    t_miny = m_miny + r * tile_m
                    t_maxx = t_minx + tile_m
                    t_maxy = t_miny + tile_m

                    # back to src CRS
                    xs2, ys2 = t_metric_src.transform(
                        [t_minx, t_maxx], [t_miny, t_maxy])
                    s_minx, s_maxx = min(xs2), max(xs2)
                    s_miny, s_maxy = min(ys2), max(ys2)

                    tile_box = box(s_minx, s_miny, s_maxx, s_maxy)
                    if not aoi.intersects(tile_box):
                        continue

                    written += 1
                    label = f"r{r:03d}_c{c:03d}"
                    msg   = f"Writing tile {label} ({written}/{total_tiles})"
                    self.progress.emit(written, total_tiles, msg)

                    tile_index.append({
                        "type": "Feature",
                        "geometry": mapping(tile_box),
                        "properties": {"tile": label, "row": r, "col": c}
                    })

                    if self.output_mode in ("single", "both"):
                        for bname, bpath in self.band_paths.items():
                            self._write_tile(bpath, 1, s_minx, s_miny, s_maxx, s_maxy,
                                             out / f"tile_{label}_{bname}.tif",
                                             src_crs, band_label=bname)

                    if self.output_mode in ("all4", "both"):
                        self._write_multi(self.band_paths, s_minx, s_miny,
                                          s_maxx, s_maxy,
                                          out / f"tile_{label}_ALL4.tif",
                                          src_crs, band_names)

            # write tile index GeoJSON
            geojson = {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": str(src_crs)}},
                "features": tile_index
            }
            with open(out / "tile_index.geojson", "w") as f:
                json.dump(geojson, f, indent=2)

            self.finished.emit(written, str(out))

        except Exception:
            self.error.emit(traceback.format_exc())

    def _write_tile(self, src_path, band_idx, minx, miny, maxx, maxy,
                    out_path, crs, band_label=""):
        with rasterio.open(src_path) as ds:
            win = from_bounds(minx, miny, maxx, maxy, ds.transform)
            win = win.intersection(
                rasterio.windows.Window(0, 0, ds.width, ds.height))
            if win.width < 1 or win.height < 1:
                return
            data = ds.read(band_idx, window=win)
            transform = ds.window_transform(win)
            profile = ds.profile.copy()
            profile.update({
                "driver": "GTiff",
                "count": 1,
                "width":  data.shape[1],
                "height": data.shape[0],
                "transform": transform,
                "compress": "lzw",
            })
            with rasterio.open(out_path, "w", **profile) as dst:
                dst.write(data, 1)
        self.tile_done.emit(str(out_path))

    def _write_multi(self, band_paths, minx, miny, maxx, maxy,
                     out_path, crs, band_names):
        arrays, transform_ref, profile_ref = [], None, None
        for bname in band_names:
            bpath = band_paths.get(bname)
            if not bpath:
                continue
            with rasterio.open(bpath) as ds:
                win = from_bounds(minx, miny, maxx, maxy, ds.transform)
                win = win.intersection(
                    rasterio.windows.Window(0, 0, ds.width, ds.height))
                if win.width < 1 or win.height < 1:
                    arrays.append(None)
                    continue
                data = ds.read(1, window=win)
                arrays.append(data)
                if transform_ref is None:
                    transform_ref = ds.window_transform(win)
                    profile_ref   = ds.profile.copy()
        if not any(a is not None for a in arrays):
            return
        h = max(a.shape[0] for a in arrays if a is not None)
        w = max(a.shape[1] for a in arrays if a is not None)
        cleaned = []
        for a in arrays:
            if a is None:
                cleaned.append(np.zeros((h, w), dtype=np.float32))
            else:
                cleaned.append(a)
        profile_ref.update({
            "driver": "GTiff",
            "count":  len(cleaned),
            "width":  w,
            "height": h,
            "transform": transform_ref,
            "compress": "lzw",
        })
        with rasterio.open(out_path, "w", **profile_ref) as dst:
            for i, arr in enumerate(cleaned, 1):
                dst.write(arr, i)
            dst.update_tags(BAND_NAMES=",".join(band_names))
        self.tile_done.emit(str(out_path))


# ── Tile grid calculator (preview only) ───────────────────────────────────────
def compute_tile_polys(aoi_geo: Polygon, tile_km: float,
                        src_crs) -> list[Polygon]:
    """Return tile box polygons in src_crs for overlay."""
    aoi_bounds = aoi_geo.bounds
    cx = (aoi_bounds[0] + aoi_bounds[2]) / 2
    cy = (aoi_bounds[1] + aoi_bounds[3]) / 2

    if not src_crs.is_geographic:
        t = Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
        lon, lat = t.transform(cx, cy)
    else:
        lon, lat = cx, cy

    zone = int((lon + 180) / 6) + 1
    hemi = 326 if lat >= 0 else 327
    metric_crs = CRS.from_epsg(hemi * 100 + zone)

    t_fwd = Transformer.from_crs(src_crs, metric_crs, always_xy=True)
    t_inv = Transformer.from_crs(metric_crs, src_crs, always_xy=True)

    xs, ys = t_fwd.transform(
        [aoi_bounds[0], aoi_bounds[2]],
        [aoi_bounds[1], aoi_bounds[3]]
    )
    m_minx, m_maxx = min(xs), max(xs)
    m_miny, m_maxy = min(ys), max(ys)
    tile_m = tile_km * 1000.0

    cols = math.ceil((m_maxx - m_minx) / tile_m)
    rows = math.ceil((m_maxy - m_miny) / tile_m)

    polys = []
    for r in range(rows):
        for c in range(cols):
            t_minx = m_minx + c * tile_m
            t_miny = m_miny + r * tile_m
            t_maxx = t_minx + tile_m
            t_maxy = t_miny + tile_m
            xs2, ys2 = t_inv.transform(
                [t_minx, t_maxx], [t_miny, t_maxy])
            polys.append(box(min(xs2), min(ys2), max(xs2), max(ys2)))
    return polys


# ── Main window ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GIS Tile Cutter  v1.0")
        self.resize(1380, 820)

        self.band_paths: dict[str, str] = {}   # {"R": path, ...}
        self.raster_crs  = None
        self.aoi_geo     = None
        self.tile_polys  = []
        self._loader: BandLoader | None  = None
        self._worker: TilingWorker | None = None

        self._build_ui()
        self.setStyleSheet(STYLE)
        self.status("Ready — load your GeoTIFF bands to begin.")

    # ── UI construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── left panel ────────────────────────────────────────────────────────
        left = QWidget()
        left.setFixedWidth(320)
        left.setStyleSheet(f"background:{C_PANEL};")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(12, 12, 12, 12)
        lv.setSpacing(10)

        # logo / title
        title = QLabel("GIS Tile Cutter")
        title.setStyleSheet(f"font-size:16px;font-weight:700;color:{C_TEXT};")
        lv.addWidget(title)
        sub = QLabel("GeoTIFF → 3.5 km tiles")
        sub.setStyleSheet(f"font-size:11px;color:{C_MUTED};margin-bottom:4px;")
        lv.addWidget(sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{C_BORDER};")
        lv.addWidget(sep)

        # Bands section
        bg = QGroupBox("Input bands")
        bg_v = QVBoxLayout(bg)
        bg_v.setSpacing(6)
        self.band_widgets = {}
        for bname, colour in [("R","#e05c5c"), ("G","#5ec4b0"),
                               ("NIR","#7c6af7"), ("DEM","#f0a23a")]:
            row = QHBoxLayout()
            lbl = QLabel(f"<b style='color:{colour}'>{bname}</b>")
            lbl.setFixedWidth(36)
            edit = QLineEdit()
            edit.setPlaceholderText("not loaded")
            edit.setReadOnly(True)
            btn = QPushButton("Browse")
            btn.setFixedWidth(60)
            btn.clicked.connect(lambda _, b=bname: self._browse_band(b))
            row.addWidget(lbl)
            row.addWidget(edit)
            row.addWidget(btn)
            bg_v.addLayout(row)
            self.band_widgets[bname] = edit

        load_all_btn = QPushButton("Load All from Folder")
        load_all_btn.clicked.connect(self._load_all_bands)
        bg_v.addWidget(load_all_btn)

        self.crs_label = QLabel("CRS: —")
        self.crs_label.setObjectName("coord")
        self.crs_label.setWordWrap(True)
        bg_v.addWidget(self.crs_label)
        lv.addWidget(bg)

        # Preview band selector
        pb_row = QHBoxLayout()
        pb_row.addWidget(QLabel("Preview band:"))
        self.preview_band_combo = QComboBox()
        self.preview_band_combo.addItems(["R", "G", "NIR", "DEM"])
        self.preview_band_combo.currentTextChanged.connect(self._refresh_preview)
        pb_row.addWidget(self.preview_band_combo)
        lv.addLayout(pb_row)

        # AOI section
        ag = QGroupBox("Area of Interest (AOI)")
        ag_v = QVBoxLayout(ag)
        ag_v.setSpacing(6)

        tool_lbl = QLabel("Drawing tool:")
        tool_lbl.setObjectName("section")
        ag_v.addWidget(tool_lbl)

        tool_row = QHBoxLayout()
        tool_row.setSpacing(4)
        self.tool_btns = {}
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        for tid, icon, tip in [
            (MapCanvas.TOOL_RECT,  "Rect",   "Drag to draw a rectangle AOI"),
            (MapCanvas.TOOL_POLY,  "Poly",   "Click vertices, double-click or press Enter to close"),
            (MapCanvas.TOOL_FREE,  "Free",   "Freehand draw an AOI")
        ]:
            b = QPushButton(icon)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setFixedWidth(64)
            b.clicked.connect(lambda _, t=tid: self._set_tool(t))
            self._tool_group.addButton(b)
            tool_row.addWidget(b)
            self.tool_btns[tid] = b
        ag_v.addLayout(tool_row)

        # manual coord entry
        coord_lbl = QLabel("Or enter coords (dataset CRS):")
        coord_lbl.setObjectName("section")
        ag_v.addWidget(coord_lbl)

        for attr, ph in [("_aoi_minx","Min X"), ("_aoi_miny","Min Y"),
                         ("_aoi_maxx","Max X"), ("_aoi_maxy","Max Y")]:
            row = QHBoxLayout()
            row.addWidget(QLabel(ph + ":"))
            e = QLineEdit()
            e.setPlaceholderText(ph)
            row.addWidget(e)
            setattr(self, attr, e)
            ag_v.addLayout(row)

        apply_coord_btn = QPushButton("Apply coordinates")
        apply_coord_btn.clicked.connect(self._apply_manual_coords)
        ag_v.addWidget(apply_coord_btn)

        # shapefile load
        shp_btn = QPushButton("Load Shapefile / GeoJSON AOI")
        shp_btn.clicked.connect(self._load_aoi_file)
        ag_v.addWidget(shp_btn)

        clear_aoi_btn = QPushButton("Clear AOI")
        clear_aoi_btn.setObjectName("danger")
        clear_aoi_btn.clicked.connect(self._clear_aoi)
        ag_v.addWidget(clear_aoi_btn)

        lv.addWidget(ag)

        # Tiling settings
        tg = QGroupBox("Tile settings")
        tg_grid = QGridLayout(tg)
        tg_grid.setSpacing(6)

        tg_grid.addWidget(QLabel("Tile size (km):"), 0, 0)
        self.tile_size_spin = QDoubleSpinBox()
        self.tile_size_spin.setRange(0.1, 100.0)
        self.tile_size_spin.setValue(3.5)
        self.tile_size_spin.setSingleStep(0.5)
        self.tile_size_spin.valueChanged.connect(self._update_tile_preview)
        tg_grid.addWidget(self.tile_size_spin, 0, 1)

        tg_grid.addWidget(QLabel("Output:"), 1, 0)
        self.out_mode_combo = QComboBox()
        self.out_mode_combo.addItems([
            "Single band per file",
            "All 4 bands stacked",
            "Both (single + stacked)"
        ])
        tg_grid.addWidget(self.out_mode_combo, 1, 1)

        tg_grid.addWidget(QLabel("Output dir:"), 2, 0)
        self.out_dir_edit = QLineEdit()
        self.out_dir_edit.setPlaceholderText("Choose folder…")
        tg_grid.addWidget(self.out_dir_edit, 2, 1)
        browse_out_btn = QPushButton("…")
        browse_out_btn.setFixedWidth(30)
        browse_out_btn.clicked.connect(self._browse_output)
        tg_grid.addWidget(browse_out_btn, 2, 2)

        lv.addWidget(tg)

        # tile count label
        self.tile_count_lbl = QLabel("Tiles: —")
        self.tile_count_lbl.setObjectName("coord")
        lv.addWidget(self.tile_count_lbl)

        # Run button
        self.run_btn = QPushButton("Export Tiles")
        self.run_btn.setObjectName("primary")
        self.run_btn.setFixedHeight(38)
        self.run_btn.clicked.connect(self._run_tiling)
        lv.addWidget(self.run_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel_tiling)
        lv.addWidget(self.cancel_btn)

        lv.addStretch()

        # ── right panel (tabs) ────────────────────────────────────────────────
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 8, 8, 8)
        rv.setSpacing(6)

        self.tabs = QTabWidget()
        rv.addWidget(self.tabs)

        # Map tab
        map_tab = QWidget()
        map_v = QVBoxLayout(map_tab)
        map_v.setContentsMargins(0, 0, 0, 0)
        map_v.setSpacing(4)

        # toolbar strip
        tb = QHBoxLayout()
        fit_btn = QPushButton("⊞ Fit view")
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
        self.tabs.addTab(map_tab, "Map view")

        # Log tab
        log_tab = QWidget()
        log_v = QVBoxLayout(log_tab)
        log_v.setContentsMargins(4, 4, 4, 4)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        log_v.addWidget(self.log)
        self.tabs.addTab(log_tab, "Log")

        # Progress strip at bottom of right panel
        prog_row = QHBoxLayout()
        self.export_pbar = QProgressBar()
        self.export_pbar.setVisible(False)
        prog_row.addWidget(self.export_pbar)
        self.export_lbl = QLabel("")
        self.export_lbl.setObjectName("coord")
        prog_row.addWidget(self.export_lbl)
        rv.addLayout(prog_row)

        # splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter)

        # status bar
        self.setStatusBar(QStatusBar())
        self._set_tool(MapCanvas.TOOL_RECT)

    # ── helpers ───────────────────────────────────────────────────────────────
    def status(self, msg):
        self.statusBar().showMessage(msg)

    def log_msg(self, msg, colour=C_TEXT, switch_tab=False):
        self.log.append(f'<span style="color:{colour};">{msg}</span>')
        if switch_tab:
            self.tabs.setCurrentIndex(1)

    # ── band loading ──────────────────────────────────────────────────────────
    def _browse_band(self, bname):
        path, _ = QFileDialog.getOpenFileName(
            self, f"Select {bname} band GeoTIFF",
            "", "GeoTIFF (*.tif *.tiff);;All files (*)")
        if not path:
            return
        self.band_paths[bname] = path
        self.band_widgets[bname].setText(Path(path).name)
        self.log_msg(f"Loaded {bname}: {path}", C_ACCENT2)
        if bname == self.preview_band_combo.currentText():
            self._load_preview(path)

    def _load_all_bands(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder with band GeoTIFFs")
        if not folder:
            return
        found = 0
        for fname in os.listdir(folder):
            low = fname.lower()
            if not (low.endswith(".tif") or low.endswith(".tiff")):
                continue
            fpath = os.path.join(folder, fname)
            for bname, pattern in [("R", "r"), ("G", "g"), ("NIR", "nir"), ("DEM", "dem")]:
                if pattern in low and bname not in self.band_paths:
                    self.band_paths[bname] = fpath
                    self.band_widgets[bname].setText(fname)
                    found += 1
                    self.log_msg(f"Loaded {bname}: {fname}", C_ACCENT2)
                    break
        if found == 0:
            self.log_msg("No matching band files found in folder", C_WARN)
        # auto-preview first loaded band
        for bname in ["R", "G", "NIR", "DEM"]:
            if bname in self.band_paths:
                self.preview_band_combo.setCurrentText(bname)
                self._load_preview(self.band_paths[bname])
                break

    def _refresh_preview(self, bname):
        if bname in self.band_paths:
            self._load_preview(self.band_paths[bname])

    def _load_preview(self, path):
        self.load_pbar.setVisible(True)
        self.load_pbar.setValue(0)
        self._loader = BandLoader(path)
        self._loader.progress.connect(self.load_pbar.setValue)
        self._loader.done.connect(self._on_band_loaded)
        self._loader.error.connect(lambda e: (
            self.log_msg("Load error: " + e.splitlines()[-1], C_ERR),
            self.load_pbar.setVisible(False)
        ))
        self._loader.start()

    def _on_band_loaded(self, pixmap, bounds, crs, w, h, path):
        self.raster_crs = crs
        self.canvas.load_overview(pixmap, bounds, crs)
        self.load_pbar.setVisible(False)
        epsg = crs.to_epsg()
        crs_str = f"EPSG:{epsg}" if epsg else crs.to_string()[:40]
        self.crs_label.setText(f"CRS: {crs_str}")
        self.log_msg(
            f"Preview: {Path(path).name}  |  {w}x{h} px  |  CRS: {crs_str}",
            C_ACCENT2)
        self.status(f"Loaded overview -- {w}x{h}  CRS:{crs_str}")
        if self.aoi_geo:
            self._update_tile_preview()

    # ── tool selection ────────────────────────────────────────────────────────
    def _set_tool(self, tool):
        self.canvas.tool = tool
        self.tool_btns[tool].setChecked(True)
        tips = {MapCanvas.TOOL_RECT: "Drag on the map to draw a rectangular AOI",
                MapCanvas.TOOL_POLY: "Click to place vertices, double-click or press Enter to close the polygon",
                MapCanvas.TOOL_FREE: "Click and drag to freehand-draw an AOI"}
        self.status(tips.get(tool, ""))

    # ── AOI handling ──────────────────────────────────────────────────────────
    def _on_aoi_changed(self, poly: Polygon):
        self.aoi_geo = poly
        b = poly.bounds
        self._aoi_minx.setText(f"{b[0]:.6f}")
        self._aoi_miny.setText(f"{b[1]:.6f}")
        self._aoi_maxx.setText(f"{b[2]:.6f}")
        self._aoi_maxy.setText(f"{b[3]:.6f}")
        self._update_tile_preview()

    def _apply_manual_coords(self):
        try:
            minx = float(self._aoi_minx.text())
            miny = float(self._aoi_miny.text())
            maxx = float(self._aoi_maxx.text())
            maxy = float(self._aoi_maxy.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid", "Enter numeric coordinates.")
            return
        poly = box(minx, miny, maxx, maxy)
        # draw on canvas
        if self.raster_crs:
            tl = self.canvas._geo_to_screen(minx, maxy)
            tr = self.canvas._geo_to_screen(maxx, maxy)
            br = self.canvas._geo_to_screen(maxx, miny)
            bl = self.canvas._geo_to_screen(minx, miny)
            self.canvas.aoi_screen = [tl, tr, br, bl]
            self.canvas.aoi_geo    = poly
            self.canvas.update()
        self.aoi_geo = poly
        self._update_tile_preview()

    def _load_aoi_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load AOI",
            "", "Vector files (*.shp *.geojson *.json);;All (*)")
        if not path:
            return
        try:
            import fiona
            with fiona.open(path) as src:
                feats = list(src)
            if not feats:
                raise ValueError("No features found")
            from shapely.geometry import shape
            geoms = [shape(f["geometry"]) for f in feats]
            from shapely.ops import unary_union
            poly = unary_union(geoms)
            if poly.geom_type not in ("Polygon", "MultiPolygon"):
                raise ValueError("Only polygon AOIs are supported")
            if poly.geom_type == "MultiPolygon":
                poly = max(poly.geoms, key=lambda p: p.area)
            b = poly.bounds
            self.aoi_geo = poly
            self._aoi_minx.setText(f"{b[0]:.6f}")
            self._aoi_miny.setText(f"{b[1]:.6f}")
            self._aoi_maxx.setText(f"{b[2]:.6f}")
            self._aoi_maxy.setText(f"{b[3]:.6f}")
            # update canvas
            pts = [self.canvas._geo_to_screen(x, y)
                   for x, y in self.aoi_geo.exterior.coords]
            self.canvas.aoi_screen = pts
            self.canvas.aoi_geo    = self.aoi_geo
            self.canvas.update()
            self._update_tile_preview()
            self.log_msg(f"AOI loaded from: {Path(path).name}", C_ACCENT2)
        except Exception as ex:
            self.log_msg(f"AOI load error: {ex}", C_ERR)

    def _clear_aoi(self):
        self.aoi_geo = None
        self.canvas.aoi_screen = []
        self.canvas.aoi_geo = None
        self.canvas.clear_tiles()
        for e in [self._aoi_minx, self._aoi_miny, self._aoi_maxx, self._aoi_maxy]:
            e.clear()
        self.tile_count_lbl.setText("Tiles: —")
        self.canvas.update()

    def _on_coord_moved(self, gx, gy):
        self.coord_lbl.setText(f"X: {gx:.4f}   Y: {gy:.4f}")

    # ── tile preview ──────────────────────────────────────────────────────────
    def _update_tile_preview(self):
        if self.aoi_geo is None or self.raster_crs is None:
            return
        try:
            km = self.tile_size_spin.value()
            polys = compute_tile_polys(self.aoi_geo, km, self.raster_crs)
            self.tile_polys = polys
            self.canvas.set_tile_grid(polys)
            aoi_b = self.aoi_geo.bounds
            nx = math.ceil((aoi_b[2] - aoi_b[0]) * 111) if self.raster_crs.is_geographic else 1
            ny = math.ceil((aoi_b[3] - aoi_b[1]) * 111) if self.raster_crs.is_geographic else 1
            self.tile_count_lbl.setText(
                f"Tiles: {len(polys)}  ({km} km, grid over AOI)")
        except Exception as ex:
            self.log_msg(f"Tile preview error: {ex}", C_WARN)

    # ── output dir ────────────────────────────────────────────────────────────
    def _browse_output(self):
        d = QFileDialog.getExistingDirectory(self, "Select output folder")
        if d:
            self.out_dir_edit.setText(d)

    # ── tiling run ────────────────────────────────────────────────────────────
    def _run_tiling(self):
        if not self.band_paths:
            QMessageBox.warning(self, "No bands", "Load at least one band first.")
            return
        if self.aoi_geo is None:
            QMessageBox.warning(self, "No AOI", "Define an Area of Interest first.")
            return
        out_dir = self.out_dir_edit.text().strip()
        if not out_dir:
            QMessageBox.warning(self, "No output", "Choose an output folder.")
            return

        mode_map = {
            0: "single",
            1: "all4",
            2: "both"
        }
        mode = mode_map[self.out_mode_combo.currentIndex()]

        self.run_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.export_pbar.setVisible(True)
        self.export_pbar.setValue(0)
        self.export_lbl.setText("Starting…")
        self.log_msg("--- Export started ---", C_ACCENT)

        self._worker = TilingWorker(
            band_paths  = self.band_paths,
            aoi_geo     = self.aoi_geo,
            tile_km     = self.tile_size_spin.value(),
            output_dir  = out_dir,
            output_mode = mode,
        )
        self._worker.progress.connect(self._on_tile_progress)
        self._worker.tile_done.connect(lambda p: self.log_msg(f"  + {Path(p).name}", C_ACCENT2))
        self._worker.finished.connect(self._on_tiling_done)
        self._worker.error.connect(self._on_tiling_error)
        self._worker.start()

    def _on_tile_progress(self, cur, total, msg):
        pct = int(cur / max(total, 1) * 100)
        self.export_pbar.setValue(pct)
        self.export_lbl.setText(msg)
        self.status(msg)

    def _on_tiling_done(self, n, out_dir):
        self.export_pbar.setValue(100)
        self.export_lbl.setText(f"Done — {n} tiles written")
        self.run_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.log_msg(f"Done -- exported {n} tiles to {out_dir}", C_ACCENT2, switch_tab=True)
        self.log_msg(f"   tile_index.geojson written", C_MUTED)
        self.status(f"Done — {n} tiles in {out_dir}")
        QMessageBox.information(self, "Export complete",
            f"Exported {n} tiles to:\n{out_dir}\n\nA tile_index.geojson was also written.")

    def _on_tiling_error(self, err):
        self.run_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.export_pbar.setVisible(False)
        self.log_msg("Error:\n" + err, C_ERR, switch_tab=True)
        self.status("Export failed — see log")
        QMessageBox.critical(self, "Export error", err[:500])

    def _cancel_tiling(self):
        if self._worker:
            self._worker.cancel()
        self.cancel_btn.setVisible(False)
        self.run_btn.setEnabled(True)
        self.export_pbar.setVisible(False)
        self.log_msg("Cancelled by user", C_WARN, switch_tab=True)
        self.status("Cancelled")


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("GIS Tile Cutter")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
