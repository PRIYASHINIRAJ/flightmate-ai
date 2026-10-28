// Animated weather drawn over the day page: falling rain, lightning,
// drifting clouds, fog or sunshine. Purely decorative.

const DROP_COUNTS = { storm: 90, rain: 70, drizzle: 40 };

// Spread values out evenly without Math.random, so renders stay stable.
function spread(index, step, range) {
  return ((index * step) % (range * 1000)) / 1000;
}

function WeatherEffect({ kind, intensity = "strong" }) {
  if (!kind) return null;

  const drops = DROP_COUNTS[kind] || 0;
  const scale = intensity === "soft" ? 0.4 : 1;

  return (
    <div className={`weather-fx fx-${kind} fx-${intensity}`} aria-hidden="true">
      {Array.from({ length: Math.round(drops * scale) }, (_, index) => (
        <span
          key={index}
          className="drop"
          style={{
            left: `${spread(index, 37_123, 100)}%`,
            animationDelay: `${spread(index, 137, 2)}s`,
            animationDuration: `${(kind === "drizzle" ? 1.1 : 0.65) + spread(index, 73, 0.5)}s`,
          }}
        />
      ))}

      {kind === "storm" && <span className="flash" />}

      {(kind === "cloudy" || kind === "partly" || kind === "storm") && (
        <>
          <span className="cloud cloud-a" />
          <span className="cloud cloud-b" />
        </>
      )}

      {kind === "fog" && <span className="fog" />}

      {(kind === "sunny" || kind === "partly") && <span className="sun-glow" />}
    </div>
  );
}

export default WeatherEffect;
