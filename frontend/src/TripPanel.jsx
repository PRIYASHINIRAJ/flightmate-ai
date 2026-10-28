import { useEffect, useState } from "react";
import TripItinerary from "./TripItinerary";
import {
  ArrowLeftIcon,
  CalendarIcon,
  CameraIcon,
  CheckIcon,
  CloudSunIcon,
  HeartIcon,
  PinIcon,
  PlaneIcon,
  SparklesIcon,
  TakeoffIcon,
  UsersIcon,
} from "./icons";
import "./TripPanel.css";

const CHECKLIST_ICONS = {
  destination: PinIcon,
  origin: TakeoffIcon,
  travellers: UsersIcon,
  dates: CalendarIcon,
  interests: HeartIcon,
};

// Each stage owns one fifth of the progress ring.
const GENERATING_STAGES = [
  { label: "Live flights", doing: "Finding live flights on Kiwi.com", icon: TakeoffIcon },
  { label: "Weather", doing: "Checking the weather forecast", icon: CloudSunIcon },
  { label: "Places", doing: "Picking places worth your time", icon: CameraIcon },
  { label: "Day plan", doing: "Building your day-by-day plan", icon: CalendarIcon },
  { label: "Map check", doing: "Checking every place on the map", icon: PinIcon },
];

const RING_RADIUS = 130;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;
const SEGMENT_GAP_DEGREES = 7;
const SEGMENT_LENGTH =
  RING_CIRCUMFERENCE / GENERATING_STAGES.length -
  (SEGMENT_GAP_DEGREES / 360) * RING_CIRCUMFERENCE;
// Stage badges sit outside the ring, at the middle of their segment.
const NODE_RADIUS_PERCENT = 43;

function ProgressRing({ filled, total }) {
  const radius = 32;
  const circumference = 2 * Math.PI * radius;

  return (
    <div className="progress-ring">
      <svg width="76" height="76" viewBox="0 0 76 76" aria-hidden="true">
        <circle className="ring-track" cx="38" cy="38" r={radius} />
        <circle
          className="ring-fill"
          cx="38"
          cy="38"
          r={radius}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - filled / total)}
        />
      </svg>
      <span>
        <strong>{filled}</strong>/{total}
      </span>
    </div>
  );
}

function TripChecklist({ trip, onGenerate, isBusy }) {
  const complete = trip.filled === trip.total;

  return (
    <div className="checklist">
      <div className="checklist-head">
        <ProgressRing filled={trip.filled} total={trip.total} />
        <div>
          <div className="eyebrow">Trip checklist</div>
          <h2>{complete ? "Ready to plan!" : "Your trip is taking shape"}</h2>
          <p>
            {trip.filled} of {trip.total} captured
          </p>
        </div>
      </div>

      <ol className="checklist-steps">
        {trip.checklist.map((item) => {
          const ItemIcon = CHECKLIST_ICONS[item.key];

          return (
            <li key={item.key} className={item.done ? "done" : "todo"}>
              <span className="step-dot">
                {item.done && <CheckIcon size={14} />}
              </span>
              <div>
                <div className="step-label">
                  <ItemIcon size={15} />
                  {item.label}
                </div>
                <div className="step-value">{item.value}</div>
              </div>
            </li>
          );
        })}
      </ol>

      <div className="generate-card">
        <button
          type="button"
          className="generate-button"
          onClick={onGenerate}
          disabled={isBusy || !trip.checklist[0].done}
        >
          <SparklesIcon size={18} />
          Generate my trip
        </button>
        <p>
          {trip.checklist[0].done
            ? "I'll build it now and fill in anything you haven't covered, or keep chatting and I'll start once the checklist is full."
            : "Tell me where you'd like to go and I can start building."}
        </p>
      </div>
    </div>
  );
}

function TripGenerating({ destination }) {
  const [percent, setPercent] = useState(2);

  // The backend replies in one go, so ease towards 94% while waiting;
  // the itinerary replaces this screen as soon as it arrives.
  useEffect(() => {
    const timer = setInterval(() => {
      setPercent((value) => value + (94 - value) * 0.035);
    }, 300);

    return () => clearInterval(timer);
  }, []);

  const share = 100 / GENERATING_STAGES.length;
  const activeStage = Math.min(Math.floor(percent / share), GENERATING_STAGES.length - 1);
  const planeAngle = (percent / 100) * 360;

  return (
    <div className="generating">
      <div className="generating-glow glow-a" />
      <div className="generating-glow glow-b" />

      <div className="planner-badge">
        <span className="planner-avatar">
          <PlaneIcon size={14} />
        </span>
        FlightMate is planning{destination ? ` your ${destination} trip` : ""}
      </div>

      <div className="orbit">
        <svg className="orbit-ring" viewBox="0 0 400 400" aria-hidden="true">
          <defs>
            <linearGradient id="ring-fill" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#c4ee6a" />
              <stop offset="100%" stopColor="#5b8f1d" />
            </linearGradient>
          </defs>

          {GENERATING_STAGES.map((stage, index) => {
            const filled = Math.min(Math.max((percent - index * share) / share, 0), 1);
            const rotation = -90 + index * (360 / GENERATING_STAGES.length) + SEGMENT_GAP_DEGREES / 2;

            return (
              <g key={stage.label} transform={`rotate(${rotation} 200 200)`}>
                <circle
                  className="ring-segment-track"
                  cx="200"
                  cy="200"
                  r={RING_RADIUS}
                  strokeDasharray={`${SEGMENT_LENGTH} ${RING_CIRCUMFERENCE}`}
                />
                <circle
                  className={`ring-segment-fill ${filled === 1 ? "complete" : ""}`}
                  cx="200"
                  cy="200"
                  r={RING_RADIUS}
                  strokeDasharray={`${SEGMENT_LENGTH * filled} ${RING_CIRCUMFERENCE}`}
                />
              </g>
            );
          })}
        </svg>

        {/* The plane flies around the ring at the current progress. */}
        <div className="orbit-plane" style={{ transform: `rotate(${planeAngle}deg)` }}>
          <span>
            <PlaneIcon size={20} />
          </span>
        </div>

        <div className="orbit-center">
          <strong>{Math.round(percent)}%</strong>
          <span key={activeStage} className="orbit-doing">
            {GENERATING_STAGES[activeStage].doing}
            <span className="orbit-dots" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
          </span>
        </div>

        {GENERATING_STAGES.map((stage, index) => {
          const StageIcon = stage.icon;
          const angle =
            ((-90 + (index + 0.5) * (360 / GENERATING_STAGES.length)) * Math.PI) / 180;
          const state =
            index < activeStage ? "done" : index === activeStage ? "active" : "pending";

          return (
            <div
              key={stage.label}
              className={`orbit-node ${state}`}
              style={{
                left: `${50 + NODE_RADIUS_PERCENT * Math.cos(angle)}%`,
                top: `${50 + NODE_RADIUS_PERCENT * Math.sin(angle)}%`,
              }}
            >
              <span className="orbit-node-icon">
                {state === "done" ? <CheckIcon size={22} /> : <StageIcon size={22} />}
              </span>
              <span className="orbit-node-label">{stage.label}</span>
            </div>
          );
        })}
      </div>

      <h2>Your trip is being generated</h2>
      <p className="generating-note">
        Only real places from the map, real driving times and live flights.
        This can take up to a minute.
      </p>
    </div>
  );
}

function TripPanel({ trip, activeTab, onTabChange, onGenerate, onClose, isBusy }) {
  let content;

  if (trip.stage === "done" && trip.itinerary) {
    content = (
      <TripItinerary
        // A new trip starts on the overview, not on a day page.
        key={`${trip.itinerary.title}-${trip.itinerary.start}`}
        itinerary={trip.itinerary}
        activeTab={activeTab}
        onTabChange={onTabChange}
      />
    );
  } else if (trip.stage === "ready" || trip.stage === "generating") {
    const destination = trip.checklist?.find((item) => item.key === "destination");
    content = <TripGenerating destination={destination?.done ? destination.value.split(",")[0] : ""} />;
  } else {
    content = (
      <TripChecklist trip={trip} onGenerate={onGenerate} isBusy={isBusy} />
    );
  }

  return (
    <aside className="trip-panel">
      <button type="button" className="trip-back" onClick={onClose}>
        <ArrowLeftIcon size={16} />
        Back to chat
      </button>
      {content}
    </aside>
  );
}

export default TripPanel;
