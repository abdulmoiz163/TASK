from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPixmap, QImage, QCursor, QPolygonF
)
from shapely.geometry import Polygon

from app.config import (
    C_BG, C_BORDER, C_TEXT, C_TEXT_SECONDARY, C_MUTED,
    C_TILE_LINE, C_TILE_FILL, C_AOI_LINE, C_AOI_FILL,
    C_ACCENT, VIGOR_COLORS,
)


class MapCanvas(QWidget):
    aoi_changed = pyqtSignal(object)
    coord_moved = pyqtSignal(float, float)

    TOOL_NONE = "none"
    TOOL_PAN = "pan"
    TOOL_RECT = "rect"
    TOOL_POLY = "poly"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(500, 400)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setStyleSheet(f"background:{C_BG};")

        self.qimage = None
        self.raster_bounds = None
        self.raster_crs = None

        self.offset = QPointF(0, 0)
        self.scale = 1.0
        self.tool = self.TOOL_RECT
        self._pan_start = None
        self._pan_offset_start = None
        self._rect_start = None
        self._rect_cur = None
        self._poly_pts = []

        self.aoi_screen = []
        self.aoi_geo = None
        self.tile_polys_screen = []

        self.vigor_polys = []
        self.vigor_colors = []

        self.overlay_images = []
        self.overlay_alphas = []

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def load_image(self, qimage, bounds, crs):
        self.qimage = qimage
        self.raster_bounds = bounds
        self.raster_crs = crs
        self.aoi_screen = []
        self.aoi_geo = None
        self.tile_polys_screen = []
        self.vigor_polys = []
        self._fit_view()
        self.update()

    def _fit_view(self):
        if self.qimage is None:
            return
        w, h = self.width(), self.height()
        iw, ih = self.qimage.width(), self.qimage.height()
        self.scale = min(w / iw, h / ih) * 0.95
        self.offset = QPointF(
            (w - iw * self.scale) / 2,
            (h - ih * self.scale) / 2
        )

    def resizeEvent(self, e):
        self._fit_view()
        self._rebuild_tile_overlay()
        self._rebuild_vigor_overlay()
        super().resizeEvent(e)

    def _screen_to_geo(self, pt):
        if self.qimage is None or self.raster_bounds is None:
            return None, None
        iw, ih = self.qimage.width(), self.qimage.height()
        ix = (pt.x() - self.offset.x()) / self.scale
        iy = (pt.y() - self.offset.y()) / self.scale
        left, bottom, right, top = self.raster_bounds
        gx = left + (ix / iw) * (right - left)
        gy = top - (iy / ih) * (top - bottom)
        return gx, gy

    def _geo_to_screen(self, gx, gy):
        if self.qimage is None or self.raster_bounds is None:
            return QPointF(0, 0)
        iw, ih = self.qimage.width(), self.qimage.height()
        left, bottom, right, top = self.raster_bounds
        ix = ((gx - left) / (right - left)) * iw
        iy = ((top - gy) / (top - bottom)) * ih
        return QPointF(
            self.offset.x() + ix * self.scale,
            self.offset.y() + iy * self.scale
        )

    def _screen_pts_to_geo(self, pts):
        coords = [self._screen_to_geo(p) for p in pts]
        if any(c[0] is None for c in coords):
            return None
        return Polygon(coords)

    def set_tile_grid(self, tile_geo_polys):
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

    def set_vigor_overlay(self, geo_polys, class_values):
        self._vigor_geo = geo_polys
        self._vigor_classes = class_values
        self._rebuild_vigor_overlay()
        self.update()

    def _rebuild_vigor_overlay(self):
        if not hasattr(self, '_vigor_geo'):
            return
        self.vigor_polys = []
        self.vigor_colors = []
        for poly, cls in zip(self._vigor_geo, self._vigor_classes):
            pts = [self._geo_to_screen(x, y) for x, y in poly.exterior.coords]
            self.vigor_polys.append(pts)
            color = VIGOR_COLORS.get(cls, "#999999")
            self.vigor_colors.append(color)

    def clear_vigor(self):
        self.vigor_polys = []
        self.vigor_colors = []
        if hasattr(self, '_vigor_geo'):
            del self._vigor_geo
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(C_BG))

        if self.qimage is None:
            p.setPen(QColor(C_MUTED))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Load GeoTIFF files to begin")
            return

        iw = self.qimage.width() * self.scale
        ih = self.qimage.height() * self.scale
        p.drawPixmap(int(self.offset.x()), int(self.offset.y()),
                     int(iw), int(ih), self.qimage)

        if self.vigor_polys:
            for pts, color in zip(self.vigor_polys, self.vigor_colors):
                c = QColor(color)
                c.setAlpha(120)
                p.setPen(QPen(QColor(color), 1.0))
                p.setBrush(QBrush(c))
                p.drawPolygon(QPolygonF(pts))

        if self.tile_polys_screen:
            p.setPen(QPen(QColor(C_TILE_LINE), 1.0, Qt.PenStyle.SolidLine))
            p.setBrush(QBrush(QColor(C_TILE_FILL)))
            for pts in self.tile_polys_screen:
                p.drawPolygon(QPolygonF(pts))

        if self.aoi_screen:
            p.setPen(QPen(QColor(C_AOI_LINE), 2.0))
            p.setBrush(QBrush(QColor(C_AOI_FILL)))
            p.drawPolygon(QPolygonF(self.aoi_screen))

        self._draw_in_progress(p)

    def _draw_in_progress(self, p):
        pen = QPen(QColor(C_AOI_LINE), 1.5, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(QBrush(QColor(C_AOI_FILL)))
        if self.tool == self.TOOL_RECT and self._rect_start and self._rect_cur:
            r = QRectF(self._rect_start, self._rect_cur).normalized()
            p.drawRect(r)
        elif self.tool == self.TOOL_POLY and self._poly_pts:
            if len(self._poly_pts) > 1:
                p.drawPolyline(QPolygonF(self._poly_pts))
            p.setBrush(QBrush(QColor(C_AOI_LINE)))
            for pt in self._poly_pts:
                p.drawEllipse(pt, 4, 4)

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
            self._rect_cur = pos
        elif self.tool == self.TOOL_POLY:
            self._poly_pts.append(QPointF(pos))

    def mouseMoveEvent(self, e):
        pos = e.position()
        gx, gy = self._screen_to_geo(QPointF(pos))
        if gx is not None:
            self.coord_moved.emit(gx, gy)
        if self._pan_start is not None:
            delta = pos - self._pan_start
            self.offset = self._pan_offset_start + delta
            self._rebuild_tile_overlay()
            self._rebuild_vigor_overlay()
            self.update()
            return
        if self.tool == self.TOOL_RECT and self._rect_start:
            self._rect_cur = pos
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
            self._rect_cur = None

    def mouseDoubleClickEvent(self, e):
        if self.tool == self.TOOL_POLY and len(self._poly_pts) >= 3:
            self._commit_aoi(self._poly_pts)
            self._poly_pts = []

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self._poly_pts = []
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
        self.offset = pos + (self.offset - pos) * factor
        self.scale *= factor
        self._rebuild_tile_overlay()
        self._rebuild_vigor_overlay()
        self.update()

    def _commit_aoi(self, pts):
        self.aoi_screen = [QPointF(p) for p in pts]
        self.aoi_geo = self._screen_pts_to_geo(pts)
        self.update()
        if self.aoi_geo:
            self.aoi_changed.emit(self.aoi_geo)

    def reset_view(self):
        self._fit_view()
        self.update()
