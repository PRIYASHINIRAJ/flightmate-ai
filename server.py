
from mcp.server.fastmcp import FastMCP

# Create our MCP server
mcp = FastMCP("Flight Search Server")

# Mock flight data for learning. Times are local to each airport.
flights = [
    {"airline": "Malaysia Airlines", "from": "Kuala Lumpur", "to": "Singapore", "price_rm": 250, "departure": "09:00", "arrival": "10:05"},
    {"airline": "AirAsia", "from": "Kuala Lumpur", "to": "Singapore", "price_rm": 120, "departure": "14:30", "arrival": "15:35"},
    {"airline": "Batik Air", "from": "Kuala Lumpur", "to": "Singapore", "price_rm": 180, "departure": "19:40", "arrival": "20:45"},
    {"airline": "Batik Air", "from": "Kuala Lumpur", "to": "Bangkok", "price_rm": 260, "departure": "07:15", "arrival": "08:25"},
    {"airline": "Malaysia Airlines", "from": "Kuala Lumpur", "to": "Bangkok", "price_rm": 350, "departure": "11:00", "arrival": "12:10"},
    {"airline": "AirAsia", "from": "Kuala Lumpur", "to": "Bangkok", "price_rm": 220, "departure": "16:45", "arrival": "17:55"},
    {"airline": "AirAsia", "from": "Bangkok", "to": "Kuala Lumpur", "price_rm": 210, "departure": "20:30", "arrival": "23:40"},
    {"airline": "Singapore Airlines", "from": "Singapore", "to": "Kuala Lumpur", "price_rm": 280, "departure": "10:15", "arrival": "11:15"},
    {"airline": "AirAsia", "from": "Singapore", "to": "Kuala Lumpur", "price_rm": 150, "departure": "18:00", "arrival": "19:05"},
    {"airline": "Malaysia Airlines", "from": "Kuala Lumpur", "to": "Penang", "price_rm": 180, "departure": "08:30", "arrival": "09:30"},
    {"airline": "AirAsia", "from": "Kuala Lumpur", "to": "Penang", "price_rm": 100, "departure": "13:20", "arrival": "14:20"},
    {"airline": "Firefly", "from": "Kuala Lumpur", "to": "Penang", "price_rm": 140, "departure": "18:10", "arrival": "19:10"},
]

# Mock destination guides for travel planning.
destinations = {
    "kuala lumpur": {
        "city": "Kuala Lumpur",
        "summary": "Malaysia's capital, known for its skyline, street food and shopping.",
        "highlights": ["Petronas Twin Towers", "Batu Caves", "Jalan Alor night food street", "KLCC Park"],
        "getting_around": "LRT and MRT trains, or Grab rides.",
        "tips": "Afternoon thunderstorms are common, so plan indoor visits after lunch.",
        "currency": "Malaysian ringgit (MYR)",
    },
    "singapore": {
        "city": "Singapore",
        "summary": "A compact, clean city-state famous for hawker food and gardens.",
        "highlights": ["Gardens by the Bay", "Marina Bay Sands", "Maxwell Food Centre", "Sentosa"],
        "getting_around": "MRT trains reach almost everywhere; use a contactless card.",
        "tips": "Carry an umbrella; short heavy showers are frequent.",
        "currency": "Singapore dollar (SGD)",
    },
    "bangkok": {
        "city": "Bangkok",
        "summary": "Thailand's lively capital of temples, markets and river life.",
        "highlights": ["Grand Palace", "Wat Arun", "Chatuchak Weekend Market", "Chao Phraya river boats"],
        "getting_around": "BTS Skytrain, MRT and river boats avoid traffic jams.",
        "tips": "Dress modestly for temples (covered shoulders and knees).",
        "currency": "Thai baht (THB)",
    },
    "penang": {
        "city": "Penang",
        "summary": "An island known for George Town's heritage streets and food.",
        "highlights": ["George Town street art", "Penang Hill", "Kek Lok Si Temple", "Gurney Drive hawker centre"],
        "getting_around": "Grab rides or the free CAT bus in George Town.",
        "tips": "Try char kway teow and assam laksa at the hawker centres.",
        "currency": "Malaysian ringgit (MYR)",
    },
}

city_aliases = {
    "kl": "kuala lumpur",
    "kul": "kuala lumpur",
    "kuala lumpur": "kuala lumpur",
    "sin": "singapore",
    "bkk": "bangkok",
    "pen": "penang",
}


def normalize_city(name: str) -> str:
    name = name.strip().lower()
    return city_aliases.get(name, name)


@mcp.tool()
def search_flights(
    origin: str,
    destination: str,
    max_price_rm: int | None = None,
    airline: str | None = None,
    depart_after: str | None = None,
    depart_before: str | None = None,
    arrive_after: str | None = None,
    arrive_before: str | None = None,
) -> list[dict]:
    """Search mock flights by origin and destination city, cheapest first.
    Accepts common names and abbreviations such as KL, KUL, BKK, SIN, and PEN.
    Optional filters: max_price_rm (budget in RM), airline (name or part of it),
    and departure/arrival windows as 24-hour "HH:MM" strings.
    """
    origin_normalized = normalize_city(origin)
    destination_normalized = normalize_city(destination)

    matches = [
        flight for flight in flights
        if flight["from"].lower() == origin_normalized
        and flight["to"].lower() == destination_normalized
    ]

    # "HH:MM" strings compare correctly as text.
    if max_price_rm is not None:
        matches = [f for f in matches if f["price_rm"] <= max_price_rm]
    if airline:
        matches = [f for f in matches if airline.lower() in f["airline"].lower()]
    if depart_after:
        matches = [f for f in matches if f["departure"] >= depart_after]
    if depart_before:
        matches = [f for f in matches if f["departure"] <= depart_before]
    if arrive_after:
        matches = [f for f in matches if f["arrival"] >= arrive_after]
    if arrive_before:
        matches = [f for f in matches if f["arrival"] <= arrive_before]

    return sorted(matches, key=lambda f: f["price_rm"])


@mcp.tool()
def get_destination_info(city: str) -> dict:
    """Get a short mock travel guide for a city: summary, highlights,
    how to get around, tips and currency.
    """
    info = destinations.get(normalize_city(city))

    if not info:
        return {"city": city, "summary": "No guide available for this city yet."}

    return info


if __name__ == "__main__":
    mcp.run()
