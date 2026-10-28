export function formatPrice(flight) {
  return flight.currency === "MYR"
    ? `RM${flight.price}`
    : `${flight.price} ${flight.currency}`;
}

export function formatDuration(minutes) {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;

  return hours ? `${hours}h${rest ? ` ${rest}m` : ""}` : `${rest}m`;
}

// "2026-11-10" -> "Tue 10 Nov"
export function formatDate(isoDate, options = {}) {
  return new Date(`${isoDate}T00:00:00`).toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    ...options,
  });
}

export function formatStops(flight) {
  if (flight.stops === 0) return "Direct";

  // Layover airports are the route minus the first and last airport.
  const via = flight.route.slice(1, -1).join(", ");
  return `${flight.stops} stop${flight.stops > 1 ? "s" : ""} via ${via}`;
}

// "+1" when the flight lands the day after it departs.
export function dayShift(flight) {
  const days = Math.round(
    (new Date(flight.arrival_date) - new Date(flight.date)) / 86400000,
  );
  return days > 0 ? ` +${days}` : "";
}
