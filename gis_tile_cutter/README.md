# GIS Tile Cutter

Desktop application to slice multi-band GeoTIFF rasters (R, G, NIR, DEM)
into 3.5 × 3.5 km tiles over a user-defined Area of Interest.

---

## Requirements

- Python 3.10+
- pip install -r requirements.txt

## Run

```bash
python main.py
```

---

## Workflow

1. **Load bands** — Browse and load each of your 4 GeoTIFF files (R, G, NIR, DEM) via the left panel.
2. **Preview** — Switch the preview band dropdown to see any band overlaid on the map canvas.
3. **Draw AOI** — Choose a drawing tool:
   - **▭ Rect** — click-drag a rectangle on the map
   - **⬠ Poly** — click polygon vertices, double-click to close
   - **✏ Free** — freehand draw any shape
   - **Manual coords** — type Min/Max X/Y directly in dataset CRS
   - **Load Shapefile/GeoJSON** — import an existing AOI polygon
4. **Tile preview** — The purple tile grid appears instantly as you adjust AOI or tile size.
5. **Set output** — Choose output folder and output mode:
   - *Single band per file* → `tile_r000_c001_R.tif`, `..._G.tif`, etc.
   - *All 4 bands stacked* → `tile_r000_c001_ALL4.tif` (band order: R, G, NIR, DEM)
   - *Both* → writes both formats
6. **Export** — Click ⚡ Export Tiles. Progress is shown live.

---

## Output structure

```
output_dir/
├── tile_r000_c000_R.tif
├── tile_r000_c000_G.tif
├── tile_r000_c000_NIR.tif
├── tile_r000_c000_DEM.tif
├── tile_r000_c000_ALL4.tif   ← if stacked mode
├── tile_r000_c001_R.tif
│   ...
└── tile_index.geojson         ← load in QGIS to see the grid
```

Each tile:
- Preserves the original CRS and geotransform
- Is LZW-compressed GeoTIFF
- Can be opened directly in QGIS, ArcGIS, or any rasterio/GDAL tool

---

## Notes

- **CRS**: Tiling is performed in the auto-detected UTM zone of your AOI centroid
  so tile dimensions are accurate in metres. Output tiles are written back in the
  original source CRS.
- **No data**: NoData values from source TIFFs are preserved in output tiles.
- **Pan/zoom**: Right-drag or middle-drag to pan; scroll wheel to zoom.
- **Cancel**: You can cancel an export mid-way — partial tiles are kept.
