import { useEffect, useRef, useState } from "react";
import { PlaceImage, UnverifiedTag } from "./PlaceImage";
import RouteMap from "./RouteMap";
import WeatherEffect from "./WeatherEffect";
import { activityType } from "./activityTypes";
import { postJson } from "./api";
import { formatDate, formatPrice, formatStops } from "./flightFormat";
import {
  CarIcon,
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ClockIcon,
  CloudIcon,
  LandingIcon,
  MaximizeIcon,
  MinimizeIcon,
  PlusIcon,
  TakeoffIcon,
  TrashIcon,
} from "./icons";
import { getWeatherKind } from "./weather";
import "./DayPage.css";

// Straight-line distance between two {lat, lng} points.
function distanceKm(a, b) {
  const rad = (degrees) => (degrees * Math.PI) / 180;
  const h =
    Math.sin(rad(b.lat - a.lat) / 2) ** 2 +
    Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(rad(b.lng - a.lng) / 2) ** 2;

  return 6371 * 2 * Math.asin(Math.sqrt(h));
}

const shortDate = (isoDate) => formatDate(isoDate, { weekday: undefined });

function FlightCard({ flight, arriving }) {
  const Icon = arriving ? LandingIcon : TakeoffIcon;

  return (
    <article className="place-card flight">
      <span className="place-photo flight-photo">
        <Icon size={26} />
      </span>
      <div className="place-text">
        <span className="place-type">
          <Icon size={15} />
          {arriving ? "Arrival flight" : "Return flight"}
        </span>
        <strong>
          {arriving
            ? `Land in ${flight.to} (${flight.to_airport})`
            : `Fly home from ${flight.from_airport}`}
        </strong>
        <span className="place-meta">
          <span>
            <ClockIcon size={14} />
            {flight.departure} → {flight.arrival}
          </span>
          <span>
            {flight.airline} {flight.flight_numbers.join(", ")} · {formatStops(flight)}
          </span>
        </span>
      </div>
      {flight.booking_url && (
        <a className="book-link" href={flight.booking_url} target="_blank" rel="noreferrer">
          {formatPrice(flight)}
        </a>
      )}
    </article>
  );
}

function AddExperience({ onAdd }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!open) {
    return (
      <button type="button" className="add-experience" onClick={() => setOpen(true)}>
        <PlusIcon size={20} />
        Add Experience
      </button>
    );
  }

  async function handleSubmit(event) {
    event.preventDefault();

    if (!name.trim() || busy) return;

    setBusy(true);
    setError("");

    try {
      // The backend finds its photo and checks it on the map.
      const data = await postJson("/trip/place", { name: name.trim() });

      if (data.place) {
        onAdd(data.place);
        setName("");
        setOpen(false);
      }
    } catch (requestError) {
      console.error("Add place error:", requestError);
      setError("Couldn't add that place. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="add-experience-form" onSubmit={handleSubmit}>
      <input
        autoFocus
        value={name}
        onChange={(event) => setName(event.target.value)}
        placeholder="Place name, e.g. Kudat Marina"
        aria-label="Place to add"
        disabled={busy}
      />
      <button type="submit" disabled={!name.trim() || busy}>
        {busy ? "Adding…" : "Add"}
      </button>
      <button type="button" className="ghost" onClick={() => setOpen(false)} disabled={busy}>
        Cancel
      </button>
      {error && <p className="add-error">{error}</p>}
    </form>
  );
}

function DayPage({ itinerary, days, dayIndex, onSelectDay, onBack, onDelete, onAdd }) {
  const day = days[dayIndex];
  const weather = getWeatherKind(day.weather);
  const [focusId, setFocusId] = useState(null);
  const [expanded, setExpanded] = useState(null);
  const [mapFull, setMapFull] = useState(false);
  const pageRef = useRef(null);
  const pillsRef = useRef(null);

  // Start at the top, with the selected date pill in view.
  useEffect(() => {
    pageRef.current?.scrollIntoView({ block: "start" });
    pillsRef.current
      ?.querySelector(".active")
      ?.scrollIntoView({ block: "nearest", inline: "center" });
  }, []);

  // Esc leaves the full-screen map.
  useEffect(() => {
    if (!mapFull) return undefined;

    const onKey = (event) => event.key === "Escape" && setMapFull(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mapFull]);

  // Real road distance and time from the backend (OSRM), including any
  // drive from the starting city. Older trips fall back to straight lines.
  const mapped = day.activities.filter((activity) => activity.lat != null);
  const totalKm =
    day.drive_km ??
    mapped.slice(1).reduce((sum, activity, index) => sum + distanceKm(mapped[index], activity), 0);
  const driveMinutes = day.drive_minutes;

  const stops = day.activities
    .map((activity, index) =>
      activity.lat != null
        ? {
            id: index,
            number: index + 1,
            lat: activity.lat,
            lng: activity.lng,
            label: activity.title,
            type: activity.type,
          }
        : null,
    )
    .filter(Boolean);

  const times = day.activities.map((activity) => activity.time).filter(Boolean);
  const KindIcon = weather?.icon || CloudIcon;
  const lastIndex = days.length - 1;

  function selectActivity(index) {
    setExpanded((current) => (current === index ? null : index));

    if (day.activities[index].lat != null) {
      setFocusId(index);
    }
  }

  return (
    <div ref={pageRef} className="day-page">
      <div className="day-list">
        <div className="day-topbar">
          <button type="button" className="back-button" onClick={onBack} aria-label="Back to trip">
            <ChevronLeftIcon size={20} />
          </button>
          <nav className="breadcrumb" aria-label="Breadcrumb">
            <button type="button" onClick={onBack}>Trip plan</button>
            <ChevronRightIcon size={16} />
            <strong>Itinerary</strong>
          </nav>
        </div>

        <div className="date-pills">
          <button
            type="button"
            className="pill-arrow"
            onClick={() => onSelectDay(dayIndex - 1)}
            disabled={dayIndex === 0}
            aria-label="Previous day"
          >
            <ChevronLeftIcon size={18} />
          </button>

          <div ref={pillsRef} className="date-pills-track">
            {days.map((item, index) => (
              <button
                key={item.day}
                type="button"
                className={index === dayIndex ? "active" : ""}
                onClick={() => onSelectDay(index)}
              >
                {shortDate(item.date)}
              </button>
            ))}
          </div>

          <button
            type="button"
            className="pill-arrow"
            onClick={() => onSelectDay(dayIndex + 1)}
            disabled={dayIndex === lastIndex}
            aria-label="Next day"
          >
            <ChevronRightIcon size={18} />
          </button>
        </div>

        <p className="day-summary">
          <strong>{shortDate(day.date)}</strong>
          <span className="dot">·</span>
          <strong>{day.title}</strong>
          <span className="dot">·</span>
          {itinerary.destination}
          <span className="dot">·</span>
          <span
            className={`summary-weather ${weather?.kind || "none"}`}
            title={
              day.weather
                ? `${weather.label}, ${day.weather.low}–${day.weather.high}°C${
                    day.weather.rain_chance ? `, ${day.weather.rain_chance} chance of rain` : ""
                  }. ${weather.tip}`
                : "Forecasts are available up to 7 days ahead"
            }
          >
            <KindIcon size={18} />
            <u>{day.weather ? `${day.weather.high}°C` : "No forecast"}</u>
          </span>
          <span className="dot">·</span>
          {day.activities.length} Experience{day.activities.length === 1 ? "" : "s"}
        </p>

        {(times.length > 1 || totalKm > 0) && (
          <p className="day-info">
            {times.length > 1 && (
              <span>
                <ClockIcon size={17} />
                <strong>Plan</strong> {times[0]} – {times[times.length - 1]}
              </span>
            )}
            {totalKm > 0 && (
              <span>
                <CarIcon size={17} />
                <strong>Driving</strong> about{" "}
                {totalKm < 10 ? totalKm.toFixed(1) : Math.round(totalKm)} km
                {driveMinutes > 0 &&
                  ` · ${
                    driveMinutes >= 60
                      ? `${Math.floor(driveMinutes / 60)} h ${driveMinutes % 60} min`
                      : `${driveMinutes} min`
                  }`}
              </span>
            )}
          </p>
        )}

        <div className="place-list">
          {day.flight_in && <FlightCard flight={day.flight_in} arriving />}

          {day.activities.map((activity, index) => {
            const type = activityType(activity.type);
            const TypeIcon = type.icon;

            return (
              <article
                key={`${activity.title}-${index}`}
                className={`place-card ${focusId === index ? "focused" : ""}`}
                onClick={() => selectActivity(index)}
              >
                <PlaceImage place={activity} className="place-photo" />

                <div className="place-text">
                  <span className="place-type">
                    <TypeIcon size={15} />
                    {type.label}
                  </span>
                  <strong>{activity.title}</strong>
                  <span className="place-meta">
                    {activity.time && (
                      <span>
                        <ClockIcon size={14} />
                        {activity.time}
                      </span>
                    )}
                    {activity.verified === true && (
                      <span className="on-map" title="Found on the map near this destination">
                        <CheckIcon size={14} />
                        On the map
                      </span>
                    )}
                    {activity.verified === false && <UnverifiedTag />}
                  </span>
                  {expanded === index && activity.description && (
                    <span className="place-description">{activity.description}</span>
                  )}
                </div>

                <button
                  type="button"
                  className="delete-button"
                  aria-label={`Remove ${activity.title}`}
                  title="Remove from this day"
                  onClick={(event) => {
                    event.stopPropagation();
                    setFocusId(null);
                    setExpanded(null);
                    onDelete(index);
                  }}
                >
                  <TrashIcon size={18} />
                </button>
              </article>
            );
          })}

          {day.flight_out && <FlightCard flight={day.flight_out} />}

          <AddExperience onAdd={onAdd} />
        </div>
      </div>

      <div className={`day-map ${mapFull ? "fullscreen" : ""}`}>
        <RouteMap
          stops={stops}
          center={itinerary.map_center}
          focusId={focusId}
          onSelect={(id) => {
            setFocusId(id);
            setExpanded(id);
          }}
          className="day-map-canvas"
        />
        <WeatherEffect kind={weather?.kind} />

        <button
          type="button"
          className="map-fullscreen"
          onClick={() => setMapFull((value) => !value)}
          aria-label={mapFull ? "Exit full screen" : "Full screen map"}
          title={mapFull ? "Exit full screen (Esc)" : "Full screen"}
        >
          {mapFull ? <MinimizeIcon size={18} /> : <MaximizeIcon size={18} />}
        </button>

        {!stops.length && (
          <div className="map-note">No confirmed map locations for this day.</div>
        )}
      </div>
    </div>
  );
}

export default DayPage;
