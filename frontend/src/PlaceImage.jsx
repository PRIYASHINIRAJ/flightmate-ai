import { useState } from "react";
import { activityType } from "./activityTypes";

// Wikipedia photo of a place, or its activity icon if there's none.
export function PlaceImage({ place, className }) {
  const [failed, setFailed] = useState(false);
  const TypeIcon = activityType(place.type).icon;

  if (!place.image || failed) {
    return (
      <span className={`${className} place-icon type-${place.type}`}>
        <TypeIcon size={20} />
      </span>
    );
  }

  return (
    <a
      className={className}
      href={place.wiki_url}
      target="_blank"
      rel="noreferrer"
      title={`${place.title} on Wikipedia`}
      onClick={(event) => event.stopPropagation()}
    >
      <img
        src={place.image}
        alt={place.title}
        loading="lazy"
        onError={() => setFailed(true)}
      />
    </a>
  );
}

// The AI suggested this place but it wasn't found on Wikipedia or
// OpenStreetMap near the destination, so it may not exist.
export function UnverifiedTag() {
  return (
    <span
      className="unverified-tag"
      title="Not found on OpenStreetMap or Wikipedia near this destination. Please check it exists before you go."
    >
      Unverified
    </span>
  );
}
