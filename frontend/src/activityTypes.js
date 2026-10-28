import {
  CameraIcon,
  CarIcon,
  CoffeeIcon,
  LandmarkIcon,
  MoonIcon,
  ShoppingIcon,
  TreeIcon,
  UtensilsIcon,
} from "./icons";

const ACTIVITY_TYPES = {
  sight: { icon: CameraIcon, label: "Place" },
  food: { icon: UtensilsIcon, label: "Restaurant" },
  culture: { icon: LandmarkIcon, label: "Culture" },
  shopping: { icon: ShoppingIcon, label: "Shopping" },
  nature: { icon: TreeIcon, label: "Nature" },
  nightlife: { icon: MoonIcon, label: "Nightlife" },
  relax: { icon: CoffeeIcon, label: "Relax" },
  transport: { icon: CarIcon, label: "Getting around" },
};

// Icon and label for an activity type ("food" -> Restaurant).
export function activityType(type) {
  return ACTIVITY_TYPES[type] || ACTIVITY_TYPES.sight;
}
