import { useState } from "react";
import DayPage from "./DayPage";
import FlightCard from "./FlightCard";
import { PlaceImage, UnverifiedTag } from "./PlaceImage";
import RouteMap from "./RouteMap";
import { activityType } from "./activityTypes";
import { formatDate } from "./flightFormat";
import {
  BulbIcon,
  CalendarIcon,
  CarIcon,
  ChevronRightIcon,
  CloudIcon,
  PinIcon,
  SparklesIcon,
  UsersIcon,
} from "./icons";
import { getWeatherKind } from "./weather";
import "./TripItinerary.css";

const TABS = [
  { key: "itinerary", label: "Itinerary" },
  { key: "route", label: "Route" },
  { key: "flights", label: "Flights" },
];

function describeTravellers(travellers) {
  if (travellers === "Solo") return "1 traveller";
  if (travellers === "Couple") return "2 travellers";
  if (/^\d+ people$/.test(travellers)) return travellers.replace("people", "travellers");

  return `With ${travellers.toLowerCase()}`;
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

const shortDate = (isoDate) => formatDate(isoDate, { weekday: undefined });

// Weather icon + high temperature, e.g. "☂ 31°C".
function WeatherInline({ weather }) {
  const kind = getWeatherKind(weather);

  if (!kind) {
    return (
      <span className="weather-inline none" title="Forecasts are available up to 7 days ahead">
        <CloudIcon size={15} />
        No forecast yet
      </span>
    );
  }

  const KindIcon = kind.icon;

  return (
    <span
      className={`weather-inline ${kind.kind}`}
      title={`${weather.conditions} · ${weather.low}–${weather.high}°C${
        weather.rain_chance ? ` · ${weather.rain_chance} chance of rain` : ""
      }`}
    >
      <KindIcon size={16} />
      {weather.high}°C
    </span>
  );
}

// One row per day on the overview.
function DayRow({ day, onOpen }) {
  const cover = day.activities.find((activity) => activity.image) || day.activities[0];
  const places = day.activities.map((activity) => activity.title).slice(0, 3);

  return (
    <li>
      <button type="button" className="day-row" onClick={onOpen}>
        {cover ? (
          <PlaceImage place={cover} className="day-row-photo" />
        ) : (
          <span className="day-row-photo place-icon">
            <CalendarIcon size={20} />
          </span>
        )}

        <span className="day-row-text">
          <span className="day-row-meta">
            Day {day.day} · {formatDate(day.date)}
            <span className="dot">·</span>
            <WeatherInline weather={day.weather} />
            <span className="dot">·</span>
            <span className="day-row-count">{plural(day.activities.length, "experience")}</span>
          </span>
          <strong>{day.title}</strong>
          <span className="day-row-places">{places.join(" · ")}</span>
        </span>

        <ChevronRightIcon size={20} />
      </button>
    </li>
  );
}

function TripItinerary({ itinerary, activeTab, onTabChange }) {
  const [openDay, setOpenDay] = useState(null);
  const [routeFocus, setRouteFocus] = useState(null);
  // Edits (removed/added places) live here until a new trip is generated.
  const [days, setDays] = useState(itinerary.days);

  function updateDay(dayIndex, change) {
    setDays((previous) =>
      previous.map((day, index) =>
        index === dayIndex ? { ...day, activities: change(day.activities) } : day,
      ),
    );
  }

  if (openDay !== null) {
    return (
      <DayPage
        key={openDay}
        itinerary={itinerary}
        days={days}
        dayIndex={openDay}
        onSelectDay={setOpenDay}
        onBack={() => setOpenDay(null)}
        onDelete={(activityIndex) =>
          updateDay(openDay, (activities) =>
            activities.filter((_, index) => index !== activityIndex),
          )
        }
        onAdd={(place) => updateDay(openDay, (activities) => [...activities, place])}
      />
    );
  }

  const { outbound, return: inbound } = itinerary.flights;
  const experiences = days.reduce((total, day) => total + day.activities.length, 0);
  const flightCount = [outbound, inbound].filter(Boolean).length;
  const routeStops = days
    .filter((day) => day.pin)
    .map((day) => ({
      id: day.day,
      number: day.day,
      lat: day.pin.lat,
      lng: day.pin.lng,
      label: `Day ${day.day} · ${day.pin.name}`,
    }));

  return (
    <div className="itinerary">
      <div
        className={`trip-hero ${itinerary.image ? "has-image" : ""}`}
        style={
          itinerary.image ? { backgroundImage: `url(${itinerary.image})` } : undefined
        }
      />

      <div className="trip-title">
        <h2>{itinerary.title}</h2>
        <div className="trip-meta">
          {itinerary.destination_label && (
            <span>
              <PinIcon size={17} />
              {itinerary.destination_label}
            </span>
          )}
          <span>
            <UsersIcon size={17} />
            {describeTravellers(itinerary.travellers)}
          </span>
          <span>
            <CalendarIcon size={17} />
            {shortDate(itinerary.start)} – {shortDate(itinerary.end)}
          </span>
        </div>
        <div className="trip-stats">
          1 city ·{" "}
          {itinerary.ground_travel ? "by road" : plural(flightCount, "flight")} ·{" "}
          {experiences} experiences · {plural(itinerary.days_count, "day")}
        </div>
      </div>

      <nav className="trip-tabs">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={activeTab === tab.key ? "active" : ""}
            onClick={() => onTabChange(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {activeTab === "itinerary" && (
        <div className="trip-section">
          {itinerary.summary && (
            <div className="trip-summary">
              <span className="trip-summary-icon">
                <SparklesIcon size={18} />
              </span>
              <div>
                <strong>Why you'll love it</strong>
                <p>{itinerary.summary}</p>
                <div className="trip-tags">
                  <span>From {itinerary.origin}</span>
                  <span>{itinerary.interests}</span>
                </div>
              </div>
            </div>
          )}

          <h3>
            Itinerary <span>{plural(itinerary.days_count, "day")}</span>
          </h3>

          <ol className="day-rows">
            {days.map((day, index) => (
              <DayRow key={day.day} day={day} onOpen={() => setOpenDay(index)} />
            ))}
          </ol>

          {itinerary.extras?.length > 0 && (
            <div className="trip-extras">
              <h3>
                More to explore <span>if you have spare time</span>
              </h3>

              <div className="extras-grid">
                {itinerary.extras.map((extra) => (
                  <article key={extra.title} className="extra-card">
                    <PlaceImage place={extra} className="extra-photo" />
                    <div className="extra-body">
                      <span className="extra-type">{activityType(extra.type).label}</span>
                      <strong>
                        {extra.title}
                        {extra.verified === false && <UnverifiedTag />}
                      </strong>
                      <p>{extra.description}</p>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          )}

          {itinerary.tips.length > 0 && (
            <div className="trip-tips">
              <h4>
                <BulbIcon size={16} />
                Good to know
              </h4>
              <ul>
                {itinerary.tips.map((tip) => (
                  <li key={tip}>{tip}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {activeTab === "route" && (
        <div className="trip-section">
          <h3>
            Route <span>one highlight per day</span>
          </h3>

          <div className="trip-map">
            <RouteMap
              stops={routeStops}
              center={itinerary.map_center}
              focusId={routeFocus}
              onSelect={setRouteFocus}
              className="trip-map-canvas"
            />

            <ol className="trip-map-legend">
              {days.filter((day) => day.pin).map((day) => (
                <li key={day.day}>
                  <button type="button" onClick={() => setRouteFocus(day.day)}>
                    <span className="legend-pin">{day.day}</span>
                    <span className="legend-text">
                      <strong>{day.pin.name}</strong>
                      <span>
                        {formatDate(day.date)}
                        {day.pin.source === "ai-estimate" && " · approx. location"}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          </div>
        </div>
      )}

      {activeTab === "flights" && (
        <div className="trip-section">
          <h3>
            Flights <span>live Kiwi.com prices</span>
          </h3>

          {itinerary.ground_travel ? (
            <div className="ground-travel">
              <CarIcon size={22} />
              <div>
                <strong>No flights on this route</strong>
                <p>
                  {itinerary.destination} is about {itinerary.ground_travel.distance_km} km
                  from {itinerary.origin} by road
                  {itinerary.ground_travel.minutes &&
                    ` (around ${Math.floor(itinerary.ground_travel.minutes / 60)} h ${
                      itinerary.ground_travel.minutes % 60
                    } min)`}
                  , so the itinerary plans the journey by car, bus or taxi.
                </p>
              </div>
            </div>
          ) : (
            <>
              {outbound ? (
                <FlightCard
                  flights={[outbound]}
                  label={`Outbound · ${outbound.from} → ${outbound.to}`}
                />
              ) : (
                <p className="trip-empty">No outbound flight found for this date.</p>
              )}

              {inbound ? (
                <FlightCard
                  flights={[inbound]}
                  label={`Return · ${inbound.from} → ${inbound.to}`}
                />
              ) : (
                <p className="trip-empty">No return flight found for this date.</p>
              )}
            </>
          )}
        </div>
      )}

      {itinerary.flights_total && (
        <div className="trip-footer">
          <div>
            <strong>From RM{itinerary.flights_total.toLocaleString()}</strong>
            <span>Return flights, per person</span>
          </div>
          <button
            type="button"
            onClick={() => onTabChange(activeTab === "flights" ? "itinerary" : "flights")}
          >
            {activeTab === "flights" ? "View itinerary" : "View flights"}
          </button>
        </div>
      )}
    </div>
  );
}

export default TripItinerary;
