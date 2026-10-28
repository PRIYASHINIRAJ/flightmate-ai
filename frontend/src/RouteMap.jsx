import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// OpenStreetMap's own tiles: free, no API key, attribution required.
const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

// Lucide icon paths for activity pins (Leaflet pins are plain HTML).
const TYPE_ICON_PATHS = {
  sight: ["M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z", "M15 13a3 3 0 1 1-6 0a3 3 0 1 1 6 0"],
  food: ["M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2", "M7 2v20", "M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"],
  culture: ["M3 22h18", "M6 18v-7", "M10 18v-7", "M14 18v-7", "M18 18v-7", "M12 2 20 7H4z"],
  shopping: ["M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z", "M3 6h18", "M16 10a4 4 0 0 1-8 0"],
  nature: ["m17 14 3 3.3a1 1 0 0 1-.7 1.7H4.7a1 1 0 0 1-.7-1.7L7 14h-.3a1 1 0 0 1-.7-1.7L9 9h-.2A1 1 0 0 1 8 7.3L12 3l4 4.3a1 1 0 0 1-.8 1.7H15l3 3.3a1 1 0 0 1-.7 1.7H17Z", "M12 22v-3"],
  nightlife: ["M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"],
  relax: ["M10 2v2", "M14 2v2", "M16 8a1 1 0 0 1 1 1v8a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V9a1 1 0 0 1 1-1h14a4 4 0 1 1 0 8h-1", "M6 2v2"],
  transport: ["M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.4 2.9A3.7 3.7 0 0 0 2 12v4c0 .6.4 1 1 1h2", "M9 17h6", "M9 17a2 2 0 1 1-4 0a2 2 0 1 1 4 0", "M19 17a2 2 0 1 1-4 0a2 2 0 1 1 4 0"],
};

function pinHtml(number, type) {
  const paths = TYPE_ICON_PATHS[type];

  if (!paths) {
    return `<span>${Number(number)}</span>`;
  }

  const svg = paths.map((d) => `<path d="${d}"/>`).join("");

  return (
    `<span class="type-pin type-${type}">` +
    `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" ` +
    `stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${svg}</svg>` +
    `<b>${Number(number)}</b></span>`
  );
}

// Pins joined in order. `stops` are {id, number, lat, lng, label, type?}:
// with a type the pin shows that activity's icon, otherwise its number.
// `center` ({lat, lng}) is used when there are no stops.
function RouteMap({ stops, center, focusId, onSelect, className }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markersRef = useRef({});
  const onSelectRef = useRef(onSelect);

  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  // Rebuild the map only when the pins themselves change.
  const stopsKey = JSON.stringify(
    stops.map((stop) => [
      stop.id, stop.number, stop.lat, stop.lng, stop.label, stop.type || null,
    ]),
  );
  const centerKey = center ? `${center.lat},${center.lng}` : "";

  useEffect(() => {
    const pins = JSON.parse(stopsKey);
    const map = L.map(containerRef.current, { scrollWheelZoom: false });

    L.tileLayer(TILE_URL, { attribution: TILE_ATTRIBUTION, maxZoom: 19 }).addTo(map);

    if (pins.length) {
      const points = pins.map(([, , lat, lng]) => [lat, lng]);

      if (points.length > 1) {
        L.polyline(points, {
          color: "#5b8f1d",
          weight: 3,
          opacity: 0.9,
          dashArray: "6 8",
        }).addTo(map);
      }

      for (const [id, number, lat, lng, label, type] of pins) {
        // Text node, so place names from the AI can't inject HTML.
        const tooltip = document.createElement("span");
        tooltip.textContent = label;

        markersRef.current[id] = L.marker([lat, lng], {
          icon: L.divIcon({
            className: "day-pin",
            html: pinHtml(number, type),
            iconSize: type ? [42, 42] : [34, 34],
            iconAnchor: type ? [21, 21] : [17, 17],
          }),
        })
          .bindTooltip(tooltip, { direction: "top", offset: [0, -18] })
          .on("click", () => onSelectRef.current?.(id))
          .addTo(map);
      }

      map.fitBounds(points, { padding: [48, 48], maxZoom: 15 });
    } else if (centerKey) {
      const [lat, lng] = centerKey.split(",").map(Number);
      map.setView([lat, lng], 11);
    } else {
      map.setView([0, 0], 2);
    }

    // Keep tiles filling the box when the layout changes size.
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(containerRef.current);

    mapRef.current = map;

    return () => {
      observer.disconnect();
      map.remove();
      mapRef.current = null;
      markersRef.current = {};
    };
  }, [stopsKey, centerKey]);

  // Fly to a pin when it's picked outside the map (e.g. from a card).
  useEffect(() => {
    const marker = markersRef.current[focusId];

    if (marker && mapRef.current) {
      mapRef.current.flyTo(marker.getLatLng(), 15, { duration: 0.8 });
      marker.openTooltip();
    }
  }, [focusId]);

  return <div ref={containerRef} className={className} />;
}

export default RouteMap;
