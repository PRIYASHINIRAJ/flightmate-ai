import {
  CloudIcon,
  CloudSunIcon,
  DrizzleIcon,
  FogIcon,
  RainIcon,
  StormIcon,
  SunIcon,
} from "./icons";

// Open-Meteo conditions ("Moderate rain showers", "Partly cloudy", ...)
// grouped into the kinds we have icons and effects for. First match wins.
const WEATHER_KINDS = [
  { kind: "storm", test: /thunder/i, icon: StormIcon, label: "Stormy" },
  { kind: "drizzle", test: /drizzle/i, icon: DrizzleIcon, label: "Drizzly" },
  { kind: "rain", test: /rain|shower/i, icon: RainIcon, label: "Rainy" },
  { kind: "fog", test: /fog|mist/i, icon: FogIcon, label: "Foggy" },
  { kind: "partly", test: /partly|mainly clear/i, icon: CloudSunIcon, label: "Partly cloudy" },
  { kind: "cloudy", test: /overcast|cloud/i, icon: CloudIcon, label: "Cloudy" },
  { kind: "sunny", test: /.*/, icon: SunIcon, label: "Sunny" },
];

const WEATHER_TIPS = {
  storm: "Thunderstorms likely, so keep indoor options handy.",
  drizzle: "Light drizzle on and off, so a small umbrella helps.",
  rain: "Rain expected, so bring an umbrella.",
  fog: "Misty start, so views may clear later.",
  partly: "A mix of sun and cloud.",
  cloudy: "Grey skies, but good for walking.",
  sunny: "Sunny, so wear sunscreen and stay hydrated.",
};

export function getWeatherKind(weather) {
  if (!weather) return null;

  const match = WEATHER_KINDS.find((item) => item.test.test(weather.conditions || ""));
  return { ...match, tip: WEATHER_TIPS[match.kind] };
}
