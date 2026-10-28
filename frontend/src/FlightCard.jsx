import {
  dayShift,
  formatDate,
  formatDuration,
  formatPrice,
  formatStops,
} from "./flightFormat";
import { TakeoffIcon } from "./icons";

function FlightCard({ flights, label }) {
  const [best, ...others] = flights;

  return (
    <div className="flight-card">
      <div className="flight-card-top">
        <span className="flight-card-label">{label || "Cheapest flight"}</span>
        <span className="flight-date">{formatDate(best.date)}</span>
      </div>

      <div className="flight-row">
        <span className="flight-icon">
          <TakeoffIcon size={22} />
        </span>

        <div className="flight-info">
          <div className="flight-airline">
            {best.airline}
            <span className="flight-number">
              {best.flight_numbers.join(" · ")}
            </span>
          </div>
          <div className="flight-route">
            {best.from} ({best.from_airport}) → {best.to} ({best.to_airport})
          </div>
        </div>

        <div className="flight-price">{formatPrice(best)}</div>
      </div>

      <div className="flight-times">
        <div>
          <strong>{best.departure}</strong>
          <span>{best.from_airport}</span>
        </div>
        <div className="flight-line">
          <span>{formatDuration(best.duration_minutes)}</span>
          <span className="flight-line-bar" />
          <span>{formatStops(best)}</span>
        </div>
        <div>
          <strong>
            {best.arrival}
            <sup>{dayShift(best)}</sup>
          </strong>
          <span>{best.to_airport}</span>
        </div>
      </div>

      {best.booking_url && (
        <a
          className="book-button"
          href={best.booking_url}
          target="_blank"
          rel="noreferrer"
        >
          Book on Kiwi.com
        </a>
      )}

      {others.length > 0 && (
        <div className="flight-others">
          <div className="flight-others-title">More options</div>

          {others.map((flight) => (
            <a
              className="flight-other"
              key={flight.booking_url || flight.flight_numbers.join()}
              href={flight.booking_url}
              target="_blank"
              rel="noreferrer"
            >
              <span className="flight-other-main">
                <strong>
                  {flight.departure} – {flight.arrival}
                  <sup>{dayShift(flight)}</sup>
                </strong>
                {flight.airline} · {flight.from_airport}→{flight.to_airport}
              </span>
              <span className="flight-other-meta">
                {formatDuration(flight.duration_minutes)} · {formatStops(flight)}
              </span>
              <span className="flight-other-price">{formatPrice(flight)}</span>
            </a>
          ))}
        </div>
      )}

      <div className="flight-card-note">
        Live prices from Kiwi.com · may change before booking
      </div>
    </div>
  );
}

export default FlightCard;
