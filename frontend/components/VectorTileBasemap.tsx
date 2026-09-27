/**
 * VectorTileBasemap
 *
 * Drop-in replacement for `<TileLayer>` when the basemap needs selective
 * layer visibility (e.g. hiding POI icons while keeping street labels).
 *
 * Renders OpenFreeMap vector tiles via the official `@maplibre/maplibre-gl-leaflet`
 * binding, which mounts a MapLibre GL canvas inside the Leaflet container
 * without disturbing Leaflet's own rendering for vector layers like
 * `<CircleMarker>` and `<Polyline>`.
 *
 * Selection of `positron` from OpenFreeMap is deliberate: per the
 * maintainers' README, Positron ships with POI layers removed already
 * ("Positron, as a special clean looking style, has POIs removed and some
 * highway labels set to show at higher zooms only"). Network panels,
 * river/water polygons, road outlines, and street/city labels are kept.
 *
 * Dark theme is achieved via the CSS filter pipeline applied to the
 * `MapContainer` (invert + hue-rotate + brightness), which composes onto
 * this canvas. No reactive dark-mode toggle inside this component.
 */

import { useEffect } from "react";
import L from "leaflet";
import { useMap } from "react-leaflet";
import "@maplibre/maplibre-gl-leaflet";
import "maplibre-gl/dist/maplibre-gl.css";

export const OPENFREEMAP_POSITRON_STYLE_URL = "https://tiles.openfreemap.org/styles/positron";

export interface VectorTileBasemapProps {
  /** OpenFreeMap style URL. Defaults to `positron` (POIs already removed). */
  styleUrl?: string;
  /** Additional MapLibre GL options applied to the inner Map instance. */
  maplibreOptions?: Omit<Parameters<typeof L.maplibreGL>[0], "style">;
}

/**
 * Attaches a `L.MaplibreGL` layer to the parent Leaflet map, pointing at
 * the given OpenFreeMap style URL. The MapLibre canvas is rendered into
 * the Leaflet container and composes with the Leaflet vector overlay
 * pane (where CircleMarker / Polyline live).
 *
 * Must be rendered as a descendant of `<MapContainer>`.
 */
export function VectorTileBasemap({
  styleUrl = OPENFREEMAP_POSITRON_STYLE_URL,
  maplibreOptions,
}: VectorTileBasemapProps = {}) {
  const map = useMap();

  useEffect(() => {
    // Construct the MapLibre layer once per styleUrl change.
    const layer = L.maplibreGL({
      style: styleUrl,
      ...maplibreOptions,
    });
    layer.addTo(map);

    return () => {
      // Detach the layer on unmount or style change. Stopping the inner
      // MapLibre map prevents canvas/WebGL resources from leaking.
      const inner = layer.getMaplibreMap();
      inner?.remove();
      map.removeLayer(layer);
    };
  }, [map, styleUrl, maplibreOptions]);

  return null;
}

export default VectorTileBasemap;
