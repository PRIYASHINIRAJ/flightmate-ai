
import asyncio
import contextvars
import json
import os
import re
import shutil
import sys
import traceback
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import math

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from google.genai import errors, types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client


# --------------------------------------------------
# Configuration
# --------------------------------------------------

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("GEMINI_API_KEY is missing from .env")

# Retry once at most, so a busy Gemini doesn't eat the whole request timeout.
client = genai.Client(
    api_key=api_key,
    http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(attempts=2),
    ),
)

# gemini-2.5-* models return 404 for new users, even though they still
# appear in check_models.py.
MODEL = "gemini-3.8-flash"

# Tried in order when a model is overloaded (503), over the free-tier
# quota (429) or retired (404).
FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest"]

# Live flight data: Kiwi.com's public MCP server (free, no API key).
KIWI_MCP_URL = "https://mcp.kiwi.com"

# Common city names and aliases. Kiwi.com resolves city names to all of a
# city's airports (e.g. Bangkok -> BKK and DMK), so we pass names, not codes.
FLIGHT_CITIES = {
    "kuala lumpur": "Kuala Lumpur",
    "kl": "Kuala Lumpur",
    "kul": "Kuala Lumpur",
    "singapore": "Singapore",
    "sin": "Singapore",
    "bangkok": "Bangkok",
    "bkk": "Bangkok",
    "penang": "Penang",
    "pen": "Penang",
    "langkawi": "Langkawi",
    "kota kinabalu": "Kota Kinabalu",
    "kk": "Kota Kinabalu",
    "bki": "Kota Kinabalu",
    "sandakan": "Sandakan",
    "tawau": "Tawau",
    "semporna": "Semporna",
    "kudat": "Kudat",
    "labuan": "Labuan",
    "miri": "Miri",
    "sibu": "Sibu",
    "kuching": "Kuching",
    "kch": "Kuching",
    "ipoh": "Ipoh",
    "melaka": "Melaka",
    "malacca": "Melaka",
    "kota bharu": "Kota Bharu",
    "kuala terengganu": "Kuala Terengganu",
    "alor setar": "Alor Setar",
    "johor bahru": "Johor Bahru",
    "jb": "Johor Bahru",
    "phuket": "Phuket",
    "bali": "Bali",
    "denpasar": "Bali",
    "jakarta": "Jakarta",
    "hong kong": "Hong Kong",
    "taipei": "Taipei",
    "tokyo": "Tokyo",
    "osaka": "Osaka",
    "seoul": "Seoul",
    "manila": "Manila",
    "hanoi": "Hanoi",
    "ho chi minh": "Ho Chi Minh City",
    "saigon": "Ho Chi Minh City",
    "sydney": "Sydney",
    "melbourne": "Melbourne",
    "dubai": "Dubai",
    "london": "London",
}

# Airline name -> (display name, IATA codes Kiwi.com filters by).
AIRLINES = {
    "airasia x": ("AirAsia X", "D7"),
    "airasia": ("AirAsia", "AK,D7,FD,QZ,Z2"),
    "air asia": ("AirAsia", "AK,D7,FD,QZ,Z2"),
    "malaysia airlines": ("Malaysia Airlines", "MH"),
    "mas": ("Malaysia Airlines", "MH"),
    "singapore airlines": ("Singapore Airlines", "SQ"),
    "sia": ("Singapore Airlines", "SQ"),
    "batik air": ("Batik Air", "OD,ID"),
    "batik": ("Batik Air", "OD,ID"),
    "firefly": ("Firefly", "FY"),
    "scoot": ("Scoot", "TR"),
    "thai airways": ("Thai Airways", "TG"),
    "thai lion": ("Thai Lion Air", "SL"),
    "jetstar": ("Jetstar", "3K,JQ,GK"),
    "cathay": ("Cathay Pacific", "CX"),
    "emirates": ("Emirates", "EK"),
    "qatar": ("Qatar Airways", "QR"),
    "garuda": ("Garuda Indonesia", "GA"),
    "vietjet": ("VietJet Air", "VJ"),
}

# Departure/arrival windows for "morning flights", "arrive in the evening" etc.
TIME_OF_DAY = {
    "morning": ("05:00", "11:59"),
    "afternoon": ("12:00", "16:59"),
    "evening": ("17:00", "20:59"),
    "night": ("21:00", "23:59"),
}

TIME_PATTERN = r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)|\d{1,2}:\d{2}|noon|midnight)"

MONTHS = {
    name: number
    for number, name in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"],
        start=1,
    )
}

MONTH_PATTERN = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"

WEEKDAYS = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]

# Number of flights returned to the frontend per search. All results are
# kept in memory for questions like "which one is the most expensive?".
MAX_RESULTS = 6

# Flight list orders: (sort key, reverse).
FLIGHT_ORDERS = {
    "price": (lambda f: (f["price"], f["duration_minutes"]), False),
    "price_desc": (lambda f: (f["price"], -f["duration_minutes"]), True),
    "duration": (lambda f: (f["duration_minutes"], f["price"]), False),
    "duration_desc": (lambda f: (f["duration_minutes"], -f["price"]), True),
    "departure": (lambda f: (f["date"], f["departure"]), False),
    "departure_desc": (lambda f: (f["date"], f["departure"]), True),
}

FLIGHT_LABELS = {
    "price": "Cheapest flight",
    "price_desc": "Most expensive flight",
    "duration": "Fastest flight",
    "duration_desc": "Longest flight",
    "departure": "Earliest flight",
    "departure_desc": "Latest flight",
}

# Words that ask for one end of a flight list. "least expensive" is
# checked before "expensive".
SUPERLATIVES = (
    ("price", r"cheapest|lowest price|least expensive|most affordable"),
    ("price_desc", r"most expensive|priciest|highest price|costliest|expensive"),
    ("duration", r"fastest|quickest|shortest"),
    ("duration_desc", r"longest|slowest"),
    ("departure", r"earliest|first flight"),
    ("departure_desc", r"latest|last flight"),
)

# --- Trip builder ---

DESTINATION_WORDS = r"to|in|at|visit|visiting|explore|exploring"

# Words that follow "to"/"in"/"from" but aren't places.
NOT_PLACES = {
    *WEEKDAYS, *MONTHS,
    "january", "february", "march", "april", "june", "july", "august",
    "september", "october", "november", "december",
    "the", "me", "my", "a", "an", "go", "travel", "visit", "see", "fly",
    "plan", "be", "have", "spend", "explore", "stay", "make", "build",
    "generate", "know", "do", "get", "find", "morning", "afternoon",
    "evening", "night", "weekend", "week", "month", "days", "nights",
    "total", "budget", "luxury", "style", "with", "it", "there", "another",
}

TRAVELLER_TYPES = (
    ("Solo", r"solo|alone|myself|just me|by myself"),
    ("Couple", r"couple|partner|wife|husband|girlfriend|boyfriend|honeymoon"),
    ("Family", r"family|kids|children|parents"),
    ("Friends", r"friends|mates|buddies"),
)

INTERESTS = (
    ("Food", r"food\w*|eat\w*|cuisine|street food|restaurants?"),
    ("Culture", r"cultur\w*|histor\w*|heritage|temples?|museums?|colonial"),
    ("Shopping", r"shop\w*|markets?"),
    ("Nightlife", r"nightlife|bars?|party|parties|clubs?"),
    ("Nature", r"nature|hik\w*|parks?|outdoors?|mountains?"),
    ("Beaches", r"beach\w*|islands?|snorkel\w*"),
    ("Relaxing", r"relax\w*|spa|chill\w*|slow"),
    ("Adventure", r"adventur\w*|thrill\w*"),
    ("Hidden gems", r"hidden gems?|local gems?|off the beaten"),
)

BUDGET_STYLES = (
    ("Budget", r"budget|backpack\w*|cheap|affordable"),
    ("Mid-range", r"mid-?range|moderate|boutique|comfort\w*"),
    ("Luxury", r"luxury|luxurious|5-star|five star|high-end|all-out"),
)

TRIP_QUESTIONS = {
    "destination": (
        "Where would you like to go?",
        ["Bangkok", "Bali", "Tokyo", "Mumbai"],
    ),
    "origin": (
        "Where will you be flying from?",
        ["Kuala Lumpur", "Singapore", "Penang"],
    ),
    "dates": (
        "When would you like to go, and for how long? "
        "For example: '10 Nov, 6 days 5 nights'.",
        ["This weekend, 2 days", "Next week, 4 days", "10 Nov, 6d5n"],
    ),
    "travellers": (
        "Who are you travelling with?",
        ["Solo trip", "As a couple", "With friends", "With family"],
    ),
    "interests": (
        "What are you after on this trip, and what's your budget style? "
        "(Street food, culture, shopping, nature… budget, mid-range or luxury?)",
        ["Street food & culture", "Shopping & nightlife",
         "Nature & relaxing", "Mid-range comfort"],
    ),
}

# Map pins: places are looked up on OpenStreetMap (free, no key). Its
# usage policy asks apps to identify themselves and send 1 request/second.
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Both OpenStreetMap and Wikipedia require a contact (URL or email) in the
# User-Agent and block requests without one. Set APP_CONTACT in .env.
APP_CONTACT = os.getenv("APP_CONTACT", "http://localhost:5173")
NOMINATIM_HEADERS = {
    "User-Agent": f"FlightMateAI/1.0 ({APP_CONTACT}; local learning project)",
}
geocode_cache = {}
nominatim_locks = {}

# A flight must leave/land within this distance of the requested places.
MAX_AIRPORT_DISTANCE_KM = 250

# Wikipedia places further than this from the destination are wrong matches.
MAX_PLACE_DISTANCE_KM = 150

# Named places checked on OpenStreetMap per trip (1 second each).
MAX_PLACE_LOOKUPS = 20

# Real places for itineraries: OpenStreetMap's Overpass API (free, no key).
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# OpenStreetMap address types that are an actual town or city.
SETTLEMENT_TYPES = {"city", "town", "village", "municipality", "suburb", "hamlet"}

# Fallback category searches when every Overpass mirror is down.
PLACE_SEARCH_PHRASES = [
    "tourist attraction", "beach", "museum", "park", "viewpoint", "cape",
    "island", "waterfall", "nature reserve", "monument", "temple",
    "restaurant", "cafe", "market",
]

# Real driving times: the public OSRM road-routing server (free, no key).
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/"

# OpenStreetMap tags -> activity types. First match wins.
OSM_CATEGORIES = (
    ("food", "amenity", r"^(restaurant|cafe|food_court)$"),
    ("shopping", "amenity", r"^marketplace$"),
    ("culture", "tourism", r"^(museum|gallery)$"),
    ("culture", "historic", r"."),
    ("nature", "natural", r"."),
    ("nature", "place", r"^(island|islet)$"),
    ("nature", "leisure", r"^(park|nature_reserve|garden)$"),
    ("culture", "amenity", r"^place_of_worship$"),
    ("sight", "tourism", r"."),
)

# Typical time spent at each kind of stop, in minutes.
VISIT_MINUTES = {
    "sight": 75, "culture": 90, "nature": 105, "food": 60,
    "shopping": 60, "relax": 60, "nightlife": 90, "transport": 30,
}

# Words that can be capitalised in a title without naming a specific place.
GENERIC_WORDS = {
    "lunch", "dinner", "breakfast", "brunch", "coffee", "tea", "seafood", "local",
    "street", "food", "market", "night", "morning", "afternoon", "evening",
    "sunset", "sunrise", "beach", "beaches", "walk", "stroll", "relax", "relaxing",
    "visit", "tour", "trip", "drive", "journey", "road", "scenic", "coastal",
    "town", "city", "village", "centre", "center", "old", "hotel", "resort",
    "check-in", "check", "rest", "free", "time", "explore", "exploring",
    "shopping", "souvenir", "souvenirs", "traditional", "cultural", "heritage",
    "nature", "park", "day", "arrival", "departure", "return", "back", "kopitiam",
    "hawker", "stall", "stalls", "cafe", "restaurant", "fresh", "views", "view",
    "leisure", "leisurely", "quiet", "slow", "easy", "early", "late", "final",
    "last", "first", "morning's", "farewell", "welcome", "settle", "settling",
    "into", "around", "nearby", "boutique", "spa", "massage", "photo", "photos",
    "stop", "break", "picnic", "swim", "swimming", "snorkelling", "snorkeling",
    "sightseeing", "highlights", "landmarks", "culture", "history", "art",
    "crafts", "handicraft", "handicrafts", "waterfront", "promenade", "harbour",
    "harbor", "pier", "jetty", "marina", "seaside", "countryside", "rural",
    "indoor", "outdoor", "rainy", "sunny", "cosy", "cozy", "casual", "fine",
    "dining", "meal", "snacks", "dessert", "drinks", "bar", "nightlife",
}

NAME_LINK_WORDS = {"of", "de", "la", "the", "&", "and", "bin", "binti", "at", "a", "an"}

# Place photos: lead images of Wikipedia articles (free, no key).
WIKIPEDIA_HEADERS = NOMINATIM_HEADERS
WIKIPEDIA_CACHE = {}

ACTIVITY_TYPES = {
    "sight", "food", "culture", "shopping", "nature",
    "nightlife", "relax", "transport",
}

# Local MCP server; still used for destination guides in trip plans.
FLIGHT_SERVER_PARAMS = StdioServerParameters(
    command=sys.executable,
    args=["server.py"],
    cwd=str(BASE_DIR),
)

app = FastAPI(title="Flight and Weather AI API")

# The deployed frontend's address goes in ALLOWED_ORIGINS (comma-separated).
ALLOWED_ORIGINS = ["http://localhost:5173"] + [
    origin.strip().rstrip("/")
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str


class WeatherServiceError(Exception):
    """The weather MCP tool returned an error result."""


class FlightSearchError(Exception):
    """The live flight search failed or returned an error."""


# What the conversation was last about, so short follow-ups keep their
# context ("now?", "only AirAsia", "what about Penang?").
# One per visitor: the frontend sends a random X-Session-Id header.
def new_memory():
    return {
        "topic": None,             # "weather" or "flight"
        "weather_location": None,
        "weather_prompt": None,
        "flight": None,            # {"origin", "destination", "date", "filters", "flights"}
        "trip": None,              # trip builder: details collected + itinerary
    }


MAX_SESSIONS = 500
sessions = {}
current_memory = contextvars.ContextVar("current_memory")


class SessionMemory:
    """Behaves like the memory dict of the visitor making this request."""

    def _data(self):
        return current_memory.get()

    def __getitem__(self, key):
        return self._data()[key]

    def __setitem__(self, key, value):
        self._data()[key] = value

    def __iter__(self):
        return iter(self._data())


memory = SessionMemory()


@app.middleware("http")
async def use_session_memory(request, call_next):
    session_id = request.headers.get("x-session-id", "")[:64] or "default"

    if session_id not in sessions:
        # Forget the oldest visitors so memory use stays bounded.
        while len(sessions) >= MAX_SESSIONS:
            sessions.pop(next(iter(sessions)))

        sessions[session_id] = new_memory()

    current_memory.set(sessions[session_id])
    return await call_next(request)


# --------------------------------------------------
# MCP helpers
# --------------------------------------------------

def get_text_result(result):
    """Extract readable text from an MCP tool result."""
    return "\n".join(
        item.text if hasattr(item, "text") else str(item)
        for item in result.content
    )


def get_structured(result):
    """Return a tool's structured result, unwrapping FastMCP's
    {"result": ...} wrapper used for non-dict return types."""
    structured = result.structuredContent

    if structured is None:
        try:
            return json.loads(get_text_result(result))
        except ValueError:
            return None

    if set(structured) == {"result"}:
        return structured["result"]

    return structured


def get_weather_server_params():
    npx_path = shutil.which("npx.cmd") or shutil.which("npx")

    if not npx_path:
        raise RuntimeError(
            "Could not find npx. Please check your Node.js installation."
        )

    return StdioServerParameters(
        command=npx_path,
        args=["-y", "@dangahagan/weather-mcp@latest"],
        env={
            **os.environ,
            "WEATHER_UNITS": "metric",
        },
    )


@asynccontextmanager
async def mcp_session(server_params):
    """Start a local MCP server and yield an initialised session."""
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


@asynccontextmanager
async def remote_mcp_session(url):
    """Connect to a hosted MCP server and yield an initialised session."""
    async with streamablehttp_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


async def get_weather_text(location, tool_name, **options):
    """Call a weather MCP tool and return its text."""
    arguments = {
        "city_name": location,
        "units": "metric",
        "detail": "standard",
        **options,
    }

    async with asyncio.timeout(60):
        async with mcp_session(get_weather_server_params()) as session:
            result = await session.call_tool(tool_name, arguments=arguments)

    if result.isError:
        raise WeatherServiceError(get_text_result(result))

    return get_text_result(result)


# --------------------------------------------------
# Gemini helper
# --------------------------------------------------

def generate_with_fallback(prompt, config=None, models=None, timeout=40):
    """Call Gemini, moving to the next model if one is overloaded,
    rate-limited, retired or slower than `timeout` seconds. Raises the
    last error if every model fails."""
    config = (config or types.GenerateContentConfig()).model_copy(update={
        "http_options": types.HttpOptions(
            timeout=timeout * 1000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    })
    last_error = None

    for model in models or [MODEL, *FALLBACK_MODELS]:
        try:
            return client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
        except (errors.APIError, httpx.TimeoutException) as error:
            code = getattr(error, "code", "timeout")

            if code not in (404, 429, 500, 503, 504, "timeout"):
                raise

            print(
                f"Gemini model {model} unavailable ({code}), "
                "trying the next one.",
                file=sys.stderr,
            )
            last_error = error

    raise last_error


# --------------------------------------------------
# Date helpers
# --------------------------------------------------

def parse_travel_date(message):
    """Read a travel date from 'tomorrow', 'on 5 Nov', 'Nov 5', '5/11'
    or 'friday'. Returns None if the message has no date."""
    text = message.lower()
    today = date.today()

    if re.search(r"\bday after tomorrow\b", text):
        return today + timedelta(days=2)

    if re.search(r"\btomorrow\b", text):
        return today + timedelta(days=1)

    if re.search(r"\b(today|tonight)\b", text):
        return today

    if re.search(r"\bnext week\b", text):
        return today + timedelta(days=7)

    if re.search(r"\bweekend\b", text):
        # The coming Saturday (today if it's already Saturday), or the
        # one after for "next weekend".
        saturday = today + timedelta(days=(5 - today.weekday()) % 7)
        return saturday + timedelta(days=7 if "next weekend" in text else 0)

    day = month = year = None

    match = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + MONTH_PATTERN
        + r"(?:\s+(\d{4}))?",
        text,
    )

    if match:
        day, month, year = int(match.group(1)), MONTHS[match.group(2)], match.group(3)
    else:
        match = re.search(
            r"\b" + MONTH_PATTERN + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b"
            r"(?:,?\s+(\d{4}))?",
            text,
        )

        if match:
            month, day, year = MONTHS[match.group(1)], int(match.group(2)), match.group(3)
        else:
            match = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", text)

            if match:
                day, month, year = (
                    int(match.group(1)),
                    int(match.group(2)),
                    match.group(3),
                )

    if day:
        year = int(year) if year else today.year

        if year < 100:
            year += 2000

        try:
            result = date(year, month, day)
        except ValueError:
            return None

        # "5 Jan" asked in October means next year's 5 Jan.
        if result < today and not match.group(3):
            result = result.replace(year=result.year + 1)

        return result

    match = re.search(r"\b(" + "|".join(WEEKDAYS) + r")\b", text)

    if match:
        days_ahead = (WEEKDAYS.index(match.group(1)) - today.weekday()) % 7
        return today + timedelta(days=days_ahead or 7)

    return None


def describe_day(day):
    """'today', 'tomorrow' or 'Wed 28 Oct'."""
    delta = (day - date.today()).days

    if delta == 0:
        return "today"

    if delta == 1:
        return "tomorrow"

    return day.strftime("%a %d %b").replace(" 0", " ")


# --------------------------------------------------
# Weather helpers
# --------------------------------------------------

def get_location(message):
    """Extract a supported location from a weather question."""
    text = message.lower()

    locations = {
        "kuala lumpur": "Kuala Lumpur, Malaysia",
        "kl": "Kuala Lumpur, Malaysia",
        "kul": "Kuala Lumpur, Malaysia",
        "singapore": "Singapore",
        "sin": "Singapore",
        "bangkok": "Bangkok, Thailand",
        "bkk": "Bangkok, Thailand",
        "penang": "Penang, Malaysia",
        "pen": "Penang, Malaysia",
        "johor bahru": "Johor Bahru, Malaysia",
        "johor": "Johor, Malaysia",
        "malacca": "Malacca, Malaysia",
        "melaka": "Malacca, Malaysia",
        "ipoh": "Ipoh, Malaysia",
        "tokyo": "Tokyo, Japan",
        "london": "London, United Kingdom",
        "new york": "New York, USA",
        "sydney": "Sydney, Australia",
    }

    # Prefer longer names before shorter aliases.
    for name in sorted(locations, key=len, reverse=True):
        if re.search(r"\b" + re.escape(name) + r"\b", text):
            return locations[name]

    # Try extracting a location not included in the list.
    match = re.search(
        r"\b(?:weather|forecast|conditions)\b"
        r".{0,35}?\b(?:in|for|at)\s+"
        r"([a-zA-Z][a-zA-Z\s,.-]{1,45})",
        message,
        re.IGNORECASE,
    )

    if match:
        candidate = match.group(1).strip(" ?!.,")
        candidate = re.sub(
            r"\s+(right now|today|tomorrow|this week|next week)$",
            "",
            candidate,
            flags=re.IGNORECASE,
        ).strip()

        # "Mumbai when I arrive" -> "Mumbai"
        candidate = re.sub(
            r"\s+(when|while|during|on|at|by|for|if|after|before|once)\b.*$",
            "",
            candidate,
            flags=re.IGNORECASE,
        ).strip()

        if candidate:
            return candidate

    return None


def is_weather_question(message):
    """Identify weather-related questions."""
    return bool(
        re.search(
            r"\b(weather|forecast|temperature|rain|raining|"
            r"rainfall|precipitation|humidity|wind|hot|cold|"
            r"conditions|drizzle|showers)\b",
            message,
            re.IGNORECASE,
        )
    )


def is_arrival_question(message):
    """Identify 'weather when I arrive / land' questions."""
    return bool(
        re.search(
            r"\b(arriv\w*|land|landing|lands|get there|reach)\b",
            message,
            re.IGNORECASE,
        )
    )


def is_weather_follow_up(message):
    """Identify short follow-ups such as 'now?', 'and at 9pm?' or
    'what about Singapore?' after a weather question."""
    if memory["topic"] != "weather":
        return False

    if len(message.split()) > 6:
        return False

    # "KL to Singapore tomorrow" is a flight search, not a weather follow-up.
    if parse_route(message):
        return False

    if re.search(
        r"\b(flights?|fly|airlines?|tickets?|price|cheapest)\b",
        message,
        re.IGNORECASE,
    ):
        return False

    return bool(
        get_requested_hour(message) is not None
        or re.search(
            r"\b(now|right now|currently|today|tonight|tomorrow|later|"
            r"morning|afternoon|evening|what about|how about)\b",
            message,
            re.IGNORECASE,
        )
    )


def get_weather_tool(message):
    """Choose the appropriate weather MCP tool without Gemini."""
    text = message.lower()

    if any(word in text for word in (
        "summary",
        "overall",
        "weather rundown",
        "weather like",
    )):
        return "get_weather_summary"

    if any(word in text for word in (
        "tomorrow",
        "tonight",
        "this week",
        "next week",
        "forecast",
        "hourly",
        "next 7 days",
        "next seven days",
        "will it rain",
        "going to rain",
    )):
        return "get_forecast"

    return "get_current_conditions"


def needs_hourly_forecast(message):
    """Check whether the question asks about a particular time of day."""
    return bool(
        re.search(
            r"\b\d{1,2}\s*(?:am|pm)\b"
            r"|\b\d{1,2}:\d{2}\b"
            r"|\b(?:morning|afternoon|evening|hourly)\b",
            message,
            re.IGNORECASE,
        )
    )


def get_requested_hour(message):
    """Return the hour (0-23) asked about, e.g. '8pm' -> 20, or None."""
    match = re.search(
        r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
        message,
        re.IGNORECASE,
    )

    if match:
        hour = int(match.group(1))
        period = match.group(3).lower()

        if not 1 <= hour <= 12:
            return None

        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0

        return hour

    match = re.search(r"\b(\d{1,2}):(\d{2})\b", message)

    if match and int(match.group(1)) <= 23:
        return int(match.group(1))

    return None


def parse_forecast_blocks(weather_text):
    """Split forecast text into (header, fields) pairs, one per
    '## ...' block (an hour or a day)."""
    entries = []

    blocks = re.split(r"^## ", weather_text, flags=re.MULTILINE)[1:]

    for block in blocks:
        lines = block.strip().splitlines()
        fields = {}

        for line in lines[1:]:
            field = re.match(r"\*\*(.+?):\*\*\s*(.+)", line.strip())

            if field:
                fields[field.group(1).lower()] = field.group(2).strip()

        entries.append((lines[0].strip(), fields))

    return entries


def parse_hourly_forecast(weather_text):
    """Split hourly forecast text into {date, hour, fields} entries."""
    entries = []

    for header, fields in parse_forecast_blocks(weather_text):
        match = re.match(r"(\S+),\s*(\d{1,2}):\d{2}", header)

        if match:
            entries.append({
                "date": match.group(1),
                "hour": int(match.group(2)),
                "fields": fields,
            })

    return entries


def format_hour(hour):
    """Format 20 as '8 PM'."""
    period = "AM" if hour < 12 else "PM"
    return f"{hour % 12 or 12} {period}"


def answer_for_hour(
    message, location, weather_text, hour, topic=None, target_date=None
):
    """Build a short answer for one hour of the hourly forecast.
    `topic` is extra text (e.g. the previous question) used to tell
    whether the user is asking about rain. `target_date` picks a specific
    day; otherwise today, or tomorrow if the message says so."""
    entries = parse_hourly_forecast(weather_text)

    if not entries:
        return None

    if target_date:
        wanted_date = target_date.strftime("%d/%m/%Y")
        day_label = describe_day(target_date)
    else:
        dates = list(dict.fromkeys(entry["date"] for entry in entries))
        wants_tomorrow = "tomorrow" in message.lower()
        wanted_date = dates[1] if wants_tomorrow and len(dates) > 1 else dates[0]
        day_label = "tomorrow" if wants_tomorrow else "today"

    entry = next(
        (
            item for item in entries
            if item["date"] == wanted_date and item["hour"] == hour
        ),
        None,
    )

    if not entry:
        return None

    fields = entry["fields"]
    conditions = fields.get("conditions", "unknown conditions")
    temperature = fields.get("temperature", "N/A")
    chance = fields.get("precipitation chance")
    when = f"at {format_hour(hour)} {day_label} in {location}"

    if re.search(
        r"\b(rain|raining|rainy|drizzle|showers|precipitation|umbrella)\b",
        f"{message} {topic or ''}",
        re.IGNORECASE,
    ):
        wet = bool(
            re.search(r"rain|drizzle|shower|thunder", conditions, re.IGNORECASE)
        )
        answer = (
            f"Yes, rain is expected {when}: {conditions.lower()}."
            if wet
            else f"No, rain isn't expected {when}: {conditions.lower()}."
        )

        if chance:
            answer += f" Chance of rain: {chance}."

        return answer + f" Temperature: {temperature}."

    return (
        f"Weather {when}: {conditions}, {temperature}"
        + (f", {chance} chance of rain." if chance else ".")
    )


# --------------------------------------------------
# Flight helpers
# --------------------------------------------------

def get_flight_city(text):
    """Map 'kl', 'kuala lumpur now' etc. to a city name; unknown
    cities are returned title-cased."""
    text = text.strip().lower()

    for name in sorted(FLIGHT_CITIES, key=len, reverse=True):
        if text == name or text.startswith(name + " "):
            return FLIGHT_CITIES[name]

    return text.title()


def find_known_cities(message):
    """Return (start, end, city) for each known flight city in the
    message, in the order they appear."""
    text = message.lower()
    found = []

    for name in sorted(FLIGHT_CITIES, key=len, reverse=True):
        for city in re.finditer(r"\b" + re.escape(name) + r"\b", text):
            overlaps = any(
                city.start() < end and start < city.end()
                for start, end, _ in found
            )

            if not overlaps:
                found.append((city.start(), city.end(), FLIGHT_CITIES[name]))

    return sorted(found)


def parse_route(message):
    """Find (origin, destination) in messages like 'KUL to Bangkok',
    'from SIN to KL' or 'KL -> Penang', without Gemini. Returns None
    when no route is found."""
    text = message.lower()

    # "from X to Y" also works for cities not in FLIGHT_CITIES.
    match = re.search(
        r"\bfrom\s+([a-z][a-z .]*?)\s+(?:to|->|→)\s+([a-z][a-z .]*?)"
        r"(?=\s+(?:on|at|for|tomorrow|today|tonight|next|this|please|"
        r"thanks|thank|under|below|with|in|only|after|before|by|"
        r"departing|arriving|leaving|and|"
        + "|".join(WEEKDAYS)
        + r")\b|\s+\d|[?.!,]|$)",
        text,
    )

    if match:
        return (
            get_flight_city(match.group(1)),
            get_flight_city(match.group(2)),
        )

    # Otherwise look for two known cities joined by "to" or an arrow.
    found = find_known_cities(message)

    if len(found) >= 2:
        between = text[found[0][1]:found[1][0]]

        if re.fullmatch(r"\s*(?:to|->|→|-)\s*", between):
            return found[0][2], found[1][2]

    return None


def parse_clock(text):
    """Convert '3pm', '3:30 pm', '15:00', 'noon' to 'HH:MM'."""
    text = text.strip().lower()

    if text == "noon":
        return "12:00"

    if text == "midnight":
        return "00:00"

    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)

    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    period = match.group(3)

    if period == "pm" and hour != 12:
        hour += 12
    elif period == "am" and hour == 12:
        hour = 0

    if hour > 23 or minute > 59:
        return None

    return f"{hour:02d}:{minute:02d}"


def parse_flight_filters(message):
    """Read budget, airline, direct-only, sort order and departure/arrival
    time filters from a message, e.g. 'direct AirAsia under RM200
    arriving before 6pm'."""
    text = message.lower()
    filters = {}

    budget = re.search(
        r"(?:under|below|less than|cheaper than|max(?:imum)?|"
        r"budget(?: of| is)?|within|up to)\s*(?:rm\s*)?(\d+)"
        r"|\brm\s*(\d+)\s*(?:or less|or below|max)",
        text,
    )

    if budget:
        filters["max_price_rm"] = int(budget.group(1) or budget.group(2))

    for name in sorted(AIRLINES, key=len, reverse=True):
        if re.search(r"\b" + re.escape(name) + r"\b", text):
            filters["airline"] = AIRLINES[name][0]
            break

    if re.search(r"\b(direct|non-?stop|no stops?)\b", text):
        filters["direct"] = True

    order = get_superlative(text)

    if order:
        filters["sort"] = order

    # Explicit times: "departing after 3pm", "arrive by 18:00".
    for kind, verbs in (
        ("arrive", r"arriv\w*|land\w*|get(?:ting)? there|reach\w*"),
        ("depart", r"depart\w*|leav\w*|take\s*off|takes\s*off|fly\w*"),
        ("depart", r""),  # bare "after 3pm" means departure
    ):
        match = re.search(
            (rf"\b(?:{verbs})\s+" if verbs else r"\b")
            + r"(after|before|by)\s+" + TIME_PATTERN,
            text,
        )

        if match and not any(key.startswith(kind) for key in filters):
            clock = parse_clock(match.group(2))

            if clock:
                direction = "after" if match.group(1) == "after" else "before"
                filters[f"{kind}_{direction}"] = clock

                # Blank out the match so later patterns don't reuse it.
                text = text[:match.start()] + " " + text[match.end():]

    # Time of day: "evening flights", "arriving in the morning".
    for kind, pattern in (
        ("arrive", r"\b(?:arriv\w*|land\w*)\s+(?:in\s+the\s+)?"
                   r"(morning|afternoon|evening|night)\b"),
        ("depart", r"\b(morning|afternoon|evening|night)\s+"
                   r"(?:flights?|departures?)\b"),
        ("depart", r"\b(?:depart\w*|leav\w*|fly\w*)\s+(?:in\s+the\s+)?"
                   r"(morning|afternoon|evening|night)\b"),
        ("depart", r"\bin\s+the\s+(morning|afternoon|evening)\b"),
    ):
        match = re.search(pattern, text)

        if match and not any(key.startswith(kind) for key in filters):
            start, end = TIME_OF_DAY[match.group(1)]
            filters[f"{kind}_after"] = start
            filters[f"{kind}_before"] = end
            text = text[:match.start()] + " " + text[match.end():]

    return filters


def describe_filters(filters):
    """'AirAsia · under RM 200 · direct only · departing after 15:00'."""
    labels = {
        "airline": "{}",
        "max_price_rm": "under RM {}",
        "direct": "direct only",
        "depart_after": "departing after {}",
        "depart_before": "departing by {}",
        "arrive_after": "arriving after {}",
        "arrive_before": "arriving by {}",
    }
    sort_labels = {
        "price_desc": "most expensive first",
        "duration": "fastest first",
        "duration_desc": "longest first",
        "departure": "earliest first",
        "departure_desc": "latest first",
    }

    parts = [
        labels[key].format(filters[key])
        for key in labels
        if filters.get(key) not in (None, False)
    ]

    if filters.get("sort") in sort_labels:
        parts.append(sort_labels[filters["sort"]])

    return " · ".join(parts)


def merge_filters(old, new):
    """Add new filters to the previous search's. A new departure or
    arrival window replaces the old one instead of combining with it."""
    merged = dict(old)

    for kind in ("depart", "arrive"):
        if any(key.startswith(kind) for key in new):
            merged.pop(f"{kind}_after", None)
            merged.pop(f"{kind}_before", None)

    merged.update(new)
    return merged


def get_airline_codes(airline):
    for display, codes in AIRLINES.values():
        if display.lower() == airline.lower():
            return codes

    return None


def normalize_itinerary(item, currency):
    """Turn a Kiwi.com itinerary into the flight dict the frontend shows."""
    leg = item["outbound"]
    segments = leg["segments"]
    departure = datetime.fromisoformat(leg["departureTime"])
    arrival = datetime.fromisoformat(leg["arrivalTime"])

    return {
        "airline": " + ".join(
            dict.fromkeys(segment["carrierName"] for segment in segments)
        ),
        "flight_numbers": [segment["flightNumber"] for segment in segments],
        "from": segments[0]["fromCity"],
        "to": segments[-1]["toCity"],
        "from_country": segments[0].get("fromCountry", ""),
        "to_country": segments[-1].get("toCountry", ""),
        "from_airport": leg["from"],
        "to_airport": leg["to"],
        "route": leg["route"],
        "date": departure.date().isoformat(),
        "departure": departure.strftime("%H:%M"),
        "arrival": arrival.strftime("%H:%M"),
        "arrival_date": arrival.date().isoformat(),
        "duration_minutes": leg["durationSeconds"] // 60,
        "stops": leg["stops"],
        "cabin": leg.get("cabinClass"),
        "baggage": item.get("baggage"),
        "price": round(item["price"]),
        "currency": currency,
        "booking_url": item.get("bookingUrl"),
        "image_id": item.get("imageId"),
    }


class FlightResults(list):
    """Flights from a search, plus the checked places and a note on why
    there are no flights (if any)."""

    note = ""
    origin_place = None
    destination_place = None


def matches_filters(flight, filters):
    """Exact checks on top of Kiwi.com's filters, which only work in
    whole hours and by airline code."""
    checks = (
        ("max_price_rm", lambda value: flight["price"] <= value),
        ("airline", lambda value: value.lower() in flight["airline"].lower()),
        ("direct", lambda value: not value or flight["stops"] == 0),
        ("depart_after", lambda value: flight["departure"] >= value),
        ("depart_before", lambda value: flight["departure"] <= value),
        ("arrive_after", lambda value: flight["arrival"] >= value),
        ("arrive_before", lambda value: flight["arrival"] <= value),
    )

    return all(
        check(filters[key])
        for key, check in checks
        if filters.get(key) is not None
    )


async def search_flights(origin, destination, travel_date, filters):
    """Search live flights on Kiwi.com's MCP server."""
    arguments = {
        "flyFrom": origin,
        "flyTo": destination,
        "departureDate": travel_date.strftime("%d/%m/%Y"),
        "currency": "MYR",
        "sort": "duration" if filters.get("sort") == "duration" else "price",
    }

    if filters.get("max_price_rm") is not None:
        arguments["price_to"] = filters["max_price_rm"]

    if filters.get("airline"):
        codes = get_airline_codes(filters["airline"])

        if codes:
            arguments["select_airlines"] = codes

    if filters.get("direct"):
        arguments["max_sector_stopovers"] = 0

    # Kiwi.com takes whole hours (0-23); minutes are checked afterwards.
    for key, kiwi_key in (
        ("depart_after", "dtime_from"),
        ("depart_before", "dtime_to"),
        ("arrive_after", "atime_from"),
        ("arrive_before", "atime_to"),
    ):
        if filters.get(key):
            arguments[kiwi_key] = int(filters[key][:2])

    try:
        async with asyncio.timeout(45):
            async with remote_mcp_session(KIWI_MCP_URL) as session:
                result = await session.call_tool(
                    "search-flight",
                    arguments=arguments,
                )
    except TimeoutError:
        raise FlightSearchError("Kiwi.com took too long to respond.")
    except Exception as error:
        print(f"Kiwi.com MCP error: {error!r}", file=sys.stderr)
        raise FlightSearchError("Couldn't reach Kiwi.com.") from None

    data = get_structured(result) or {}

    if result.isError or data.get("error"):
        raise FlightSearchError(
            str(data.get("error") or get_text_result(result))[:200]
        )

    currency = data.get("currency", "MYR")
    flights = [
        normalize_itinerary(item, currency)
        for item in data.get("itineraries", [])
        if item.get("outbound")
    ]
    flights = [flight for flight in flights if matches_filters(flight, filters)]

    kept, rejected, origin_place, destination_place = await keep_real_route(
        flights, origin, destination
    )
    results = FlightResults(sort_flights(kept, filters.get("sort", "price")))
    results.origin_place = origin_place
    results.destination_place = destination_place

    if not kept and rejected:
        wrong_places = ", ".join(dict.fromkeys(
            f"{flight['to']} ({flight['to_airport']}), {flight['to_country']}"
            for flight in rejected
        ))
        results.note = (
            f"Kiwi.com only offered flights to {wrong_places}, which isn't "
            f"{destination}, so I left them out."
        )

    if not kept and origin_place and destination_place:
        distance = distance_km(origin_place, destination_place)

        if distance < 600:
            results.note += (
                f" {destination} is about {round(distance)} km from {origin} "
                "in a straight line, so it's usually reached by road."
            )

    results.note = results.note.strip()
    return results


def sort_flights(flights, order):
    key, reverse = FLIGHT_ORDERS.get(order, FLIGHT_ORDERS["price"])
    return sorted(flights, key=key, reverse=reverse)


def format_duration(minutes):
    hours, rest = divmod(minutes, 60)

    if not hours:
        return f"{rest}m"

    return f"{hours}h {rest}m" if rest else f"{hours}h"


def format_stops(flight):
    if flight["stops"] == 0:
        return "direct"

    via = ", ".join(flight["route"][1:-1])
    plural = "s" if flight["stops"] > 1 else ""
    return f"{flight['stops']} stop{plural} via {via}"


def flight_reply(origin, destination, travel_date, flights, filters, label=None):
    """Build the /chat response for a flight search and remember all
    results for follow-ups; the frontend gets the top MAX_RESULTS."""
    memory["topic"] = "flight"
    memory["flight"] = {
        "origin": origin,
        "destination": destination,
        "date": travel_date,
        "filters": filters,
        "flights": flights,
    }

    description = describe_filters(filters)
    when = describe_day(travel_date)

    if not flights:
        reply = f"No flights found from {origin} to {destination} {when}"
        reply += f" ({description})." if description else "."

        if getattr(flights, "note", ""):
            reply += f" {flights.note}"

        return {"reply": reply, "flights": []}

    return {
        "reply": f"Filtered: {description}" if description else "",
        "flights": flights[:MAX_RESULTS],
        "flights_label": label
        or FLIGHT_LABELS.get(filters.get("sort"), "Cheapest flight"),
    }


def get_superlative(message):
    """'which one is the most expensive?' -> 'price_desc'."""
    for order, pattern in SUPERLATIVES:
        if re.search(rf"\b(?:{pattern})\b", message, re.IGNORECASE):
            return order

    return None


def is_pick_question(message):
    """Questions asking for one flight ('which one is the most expensive?',
    'what's the fastest flight?'), as opposed to 'find the cheapest
    flights from KL to Bangkok', which lists them."""
    return bool(
        re.search(
            r"^\s*(which|what|what's|whats|show me|tell me|give me)\b"
            r"|\bwhich (one|flight)\b|\?\s*$",
            message,
            re.IGNORECASE,
        )
    )


def get_pick_target(message, filters, travel_date):
    """Work out which search a 'which one is...' question is about:
    the last one, or a new route/date named in the question. Returns
    (origin, destination, date, filters) or None."""
    last = memory["flight"]
    filters = {key: value for key, value in filters.items() if key != "sort"}
    route = parse_route(message)

    if route:
        origin, destination = route
    elif last:
        origin, destination = last["origin"], last["destination"]
    else:
        return None

    if last and (origin, destination) == (last["origin"], last["destination"]):
        last_filters = {
            key: value for key, value in last["filters"].items() if key != "sort"
        }
        return (
            origin,
            destination,
            travel_date or last["date"],
            merge_filters(last_filters, filters),
        )

    return (
        origin,
        destination,
        travel_date or date.today() + timedelta(days=1),
        filters,
    )


async def pick_reply(origin, destination, travel_date, filters, order):
    """Answer 'which one is the most expensive?' with one flight,
    searching first only if the question is about a different search."""
    last = memory["flight"]
    same_search = (
        last
        and (last["origin"], last["destination"], last["date"])
        == (origin, destination, travel_date)
        and {k: v for k, v in last["filters"].items() if k != "sort"} == filters
    )

    if same_search:
        flights = last["flights"]
        memory["topic"] = "flight"
    else:
        flights = await search_flights(origin, destination, travel_date, filters)
        flight_reply(origin, destination, travel_date, flights, filters)

    if not flights:
        return {
            "reply": (
                f"No flights found from {origin} to {destination} "
                f"{describe_day(travel_date)}. {getattr(flights, 'note', '')}"
            ).strip()
        }

    pick = sort_flights(flights, order)[0]
    label = FLIGHT_LABELS[order]
    prices = [flight["price"] for flight in flights]

    reply = (
        f"The {label.lower()} {describe_day(travel_date)} is {pick['airline']} "
        f"{', '.join(pick['flight_numbers'])}, departing {pick['from_airport']} "
        f"at {pick['departure']} and landing at {pick['to_airport']} at "
        f"{pick['arrival']} ({format_duration(pick['duration_minutes'])}, "
        f"{format_stops(pick)}) for {format_price(pick)}."
    )

    if len(flights) > 1:
        reply += (
            f" Across {len(flights)} options, prices range from "
            f"RM {min(prices)} to RM {max(prices)}."
        )

    return {"reply": reply, "flights": [pick], "flights_label": label}


def is_results_question(message):
    """Questions about the last results ('which one has baggage?', 'how
    long is it?'), as opposed to refinements ('what about Friday?')."""
    return bool(
        re.search(
            r"^\s*(which|how|does|do|is|are|when|where|can|tell me|"
            r"what(?:'s| is| time| are))\b"
            r"|\b(baggage|bags?|luggage|layovers?|terminal|how long|"
            r"flight number|book)\b",
            message,
            re.IGNORECASE,
        )
    )


def get_follow_up_route(message, filters, travel_date):
    """Reuse the last flight search for follow-ups like 'only AirAsia',
    'under RM200', 'what about Friday?' or 'what about Penang?'.
    Returns (origin, destination, filters, date) or None."""
    last = memory["flight"]

    if memory["topic"] != "flight" or not last or is_results_question(message):
        return None

    new_date = travel_date or last["date"]
    cities = find_known_cities(message)

    # A new destination starts with fresh filters.
    if len(cities) == 1 and re.search(
        r"\b(what about|how about|instead|to)\b", message, re.IGNORECASE
    ):
        return last["origin"], cities[0][2], filters, new_date

    if filters or travel_date or re.search(
        r"\b(only|instead|any other|other options|show more)\b",
        message,
        re.IGNORECASE,
    ):
        return (
            last["origin"],
            last["destination"],
            merge_filters(last["filters"], filters),
            new_date,
        )

    return None


def flight_context():
    """Describe the last search for Gemini, so it can answer questions
    such as 'how long is the AirAsia flight?'."""
    last = memory["flight"]

    if not last:
        return "No flight search yet."

    fields = (
        "airline", "flight_numbers", "from", "to", "from_airport",
        "to_airport", "route", "date", "departure", "arrival",
        "arrival_date", "duration_minutes", "stops", "cabin", "baggage",
        "price", "currency",
    )
    flights = [
        {field: flight.get(field) for field in fields}
        for flight in last["flights"]
    ]

    return (
        f"Last search: {last['origin']} to {last['destination']} on "
        f"{last['date'].isoformat()}, filters {json.dumps(last['filters'])}.\n"
        f"Results (live Kiwi.com data, prices in {flights[0]['currency'] if flights else 'MYR'}): "
        f"{json.dumps(flights)}"
    )


SEARCH_FLIGHTS_DECLARATION = types.FunctionDeclaration(
    name="search_flights",
    description=(
        "Search live one-way flights on Kiwi.com. Use for any request for "
        "flight options, prices or times on a route."
    ),
    parameters={
        "type": "object",
        "properties": {
            "origin": {
                "type": "string",
                "description": "Departure city or airport, e.g. 'Kuala Lumpur'",
            },
            "destination": {
                "type": "string",
                "description": "Arrival city or airport, e.g. 'Bangkok'",
            },
            "date": {
                "type": "string",
                "description": "Departure date as YYYY-MM-DD",
            },
            "max_price_rm": {
                "type": "integer",
                "description": "Maximum price in Malaysian ringgit",
            },
            "airline": {
                "type": "string",
                "description": "Preferred airline name, e.g. 'AirAsia'",
            },
            "direct_only": {
                "type": "boolean",
                "description": "Only non-stop flights",
            },
        },
        "required": ["origin", "destination"],
    },
)


# --------------------------------------------------
# Travel planning helpers
# --------------------------------------------------

def format_price(flight):
    if flight["currency"] == "MYR":
        return f"RM {flight['price']}"

    return f"{flight['price']} {flight['currency']}"


def is_itinerary_request(message):
    """'Plan me an itinerary for 6d5n in Mumbai', 'plan a trip to Bali',
    'holiday in Tokyo', 'plan another trip'."""
    return bool(
        re.search(
            r"\b(itinerar\w*|itenar\w*|itinery|holiday|vacation|getaway)\b"
            r"|\bplan\w*\b.*\b(trip|travel|holiday|vacation|getaway)\b"
            r"|\btrip\s+(?:to|from|in)\b"
            r"|\b\d+\s*d\s*\d+\s*n\b",
            message,
            re.IGNORECASE,
        )
    )


def wants_generate(message):
    return bool(
        re.search(
            r"\b(generate|build|create|make)\b.*\b(trip|itinerary|plan|it)\b"
            r"|^\s*(go ahead|that's all|thats all|done|ok,? generate)\b",
            message,
            re.IGNORECASE,
        )
    )


def extract_place(message, prepositions):
    """Find a place after one of the prepositions, e.g. 'in Mumbai' or
    'from KL'. Skips non-places like 'to go' or 'in November'."""
    pattern = (
        rf"\b(?:{prepositions})\s+([a-z][a-z .'-]*?)"
        r"(?=\s+(?:from|to|for|on|in|with|next|this|tomorrow|today|and|by|"
        r"around|during|starting|leaving|please)\b|\s*\d|[,.!?]|$)"
    )

    for match in re.finditer(pattern, message.lower()):
        candidate = match.group(1).strip(" .'-")
        words = candidate.split()

        if not words or len(words) > 4 or words[0] in NOT_PLACES:
            continue

        return get_flight_city(candidate)

    return None


def parse_trip_length(message, known_days=None):
    """Return days from '6d5n', '6 days 5 nights', '5 nights', '4-day',
    'a week' or 'weekend', or None. 'Weekend' only implies 2 days when no
    length is known yet: 'this weekend' answering "when?" for a 5-day trip
    is a start date, not a new length."""
    text = message.lower()

    match = re.search(r"\b(\d+)\s*d\s*(\d+)\s*n\b", text)

    if match:
        return int(match.group(1))

    match = re.search(r"\b(\d+)\s*-?\s*days?\b", text)

    if match:
        return int(match.group(1))

    match = re.search(r"\b(\d+)\s*-?\s*nights?\b", text)

    if match:
        return int(match.group(1)) + 1

    if re.search(r"\ba week\b|\bone week\b", text):
        return 7

    if re.search(r"\bweekend\b", text) and not known_days:
        return 2

    return None


def parse_travellers(message):
    text = message.lower()
    match = re.search(
        r"\b(\d+)\s*(?:people|persons|pax|adults|travell?ers|of us)\b", text
    )

    if match:
        count = int(match.group(1))
        return "Solo" if count == 1 else f"{count} people"

    for label, pattern in TRAVELLER_TYPES:
        if re.search(rf"\b(?:{pattern})\b", text):
            return label

    return None


def parse_interests(message):
    """'street food and culture, budget' -> 'Food, Culture · Budget'."""
    text = message.lower()
    interests = [
        label for label, pattern in INTERESTS
        if re.search(rf"\b(?:{pattern})\b", text)
    ]
    style = next(
        (
            label for label, pattern in BUDGET_STYLES
            if re.search(rf"\b(?:{pattern})\b", text)
        ),
        None,
    )

    parts = []

    if interests:
        parts.append(", ".join(interests))

    if style:
        parts.append(style)

    return " · ".join(parts) or None


def update_trip(trip, message):
    """Fill trip details from a message. A short answer to the question
    just asked counts too (e.g. 'Mumbai' after 'Where to?')."""
    asked = trip.get("asked")
    is_short_name = bool(re.fullmatch(r"[a-zA-Z][a-zA-Z .'-]{1,40}", message.strip()))

    destination = extract_place(message, DESTINATION_WORDS)
    origin = extract_place(message, "from|leaving|departing")

    if not destination and asked == "destination" and is_short_name:
        destination = get_flight_city(message)

    if not origin and asked == "origin" and is_short_name:
        origin = get_flight_city(message.lower().removeprefix("from "))

    if destination and destination != origin:
        trip["destination"] = destination

    if origin:
        trip["origin"] = origin

    start = parse_travel_date(message)
    days = parse_trip_length(message, known_days=trip.get("days"))

    if start:
        trip["start"] = start

    if days:
        trip["days"] = max(1, min(days, 14))

    travellers = parse_travellers(message)

    if travellers:
        trip["travellers"] = travellers

    interests = parse_interests(message)

    # Free-text answers to "What are you after?" are kept as written.
    if not interests and asked == "interests" and not wants_generate(message):
        interests = message.strip()[:80]

    if interests:
        trip["interests"] = interests


def describe_trip_dates(trip):
    parts = []

    if trip.get("start"):
        parts.append(trip["start"].strftime("%d %b %Y").lstrip("0"))

    if trip.get("days"):
        days = trip["days"]
        nights = days - 1
        parts.append(
            f"{days} day{'s' if days > 1 else ''}"
            + (f" {nights} night{'s' if nights > 1 else ''}" if nights else "")
        )

    return ", ".join(parts) or None


def get_missing_slot(trip):
    if not trip.get("destination"):
        return "destination"

    if not trip.get("origin"):
        return "origin"

    if not trip.get("start") or not trip.get("days"):
        return "dates"

    if not trip.get("travellers"):
        return "travellers"

    if not trip.get("interests"):
        return "interests"

    return None


def trip_state(trip):
    """The checklist the frontend shows in the trip panel."""
    dates = describe_trip_dates(trip)
    places = trip.get("places", {})

    # Show the place as found on the map ("Kudat, Sabah, Malaysia") so a
    # wrong match is easy to spot.
    def place_label(slot):
        place = places.get(slot)
        return place["label"] if place and place["name"] == trip.get(slot) else trip.get(slot)

    slots = [
        ("destination", "Where to", place_label("destination"),
         "I'll ask where you'd like to go"),
        ("origin", "Where from", place_label("origin"),
         "I'll ask where you're flying from"),
        ("travellers", "Who's coming", trip.get("travellers"),
         "I'll ask who you're travelling with"),
        ("dates", "When you'd go", dates, "I'll ask when and for how long"),
        ("interests", "What you're after", trip.get("interests"),
         "I'll ask what would make this trip yours"),
    ]

    checklist = [
        {
            "key": key,
            "label": label,
            "value": value or placeholder,
            "done": bool(value) and (
                key != "dates" or bool(trip.get("start") and trip.get("days"))
            ),
        }
        for key, label, value, placeholder in slots
    ]

    return {
        "stage": trip["stage"],
        "checklist": checklist,
        "filled": sum(item["done"] for item in checklist),
        "total": len(checklist),
    }


def trip_question(trip, slot):
    """Next question and quick replies for a missing detail."""
    if slot == "dates" and trip.get("days") and not trip.get("start"):
        return "When would you like to go?", [
            "This weekend", "Next week", "On 10 Nov",
        ]

    if slot == "dates" and trip.get("start") and not trip.get("days"):
        return "How many days will you stay?", [
            "3 days 2 nights", "5 days 4 nights", "A week",
        ]

    return TRIP_QUESTIONS[slot]


async def verify_trip_places(trip):
    """Check the destination and origin are real places on OpenStreetMap.
    An unknown one is cleared; returns (slot, name) for it, or None."""
    places = trip.setdefault("places", {})

    for slot in ("destination", "origin"):
        name = trip.get(slot)

        if not name or places.get(slot, {}).get("name") == name:
            continue

        # Short unknown names ("Kk") match random places, so don't look up.
        known = name.lower() in FLIGHT_CITIES or name in FLIGHT_CITIES.values()
        place = await locate_place(name) if known or len(name) > 3 else None

        if not place:
            trip[slot] = None
            places.pop(slot, None)
            return slot, name

        places[slot] = place

    return None


async def handle_trip(message, new=False):
    """Collect trip details one question at a time."""
    if new or not memory["trip"] or memory["trip"]["stage"] != "collecting":
        memory["trip"] = {"stage": "collecting", "asked": None}

    trip = memory["trip"]
    update_trip(trip, message)

    # Never guess a place: ask again if it can't be found on the map.
    unclear = await verify_trip_places(trip)

    if unclear:
        slot, name = unclear
        trip["asked"] = slot
        question = (
            "Which city are you flying from?" if slot == "origin"
            else "Where would you like to go?"
        )
        return {
            "reply": (
                f"I couldn't find a place called \"{name}\". {question} "
                "Please type its full name, e.g. 'Kota Kinabalu'."
            ),
            "trip": trip_state(trip),
            "quick_replies": TRIP_QUESTIONS[slot][1],
        }

    missing = get_missing_slot(trip)

    if trip.get("destination") and (not missing or wants_generate(message)):
        trip["stage"] = "ready"
        return {
            "reply": (
                f"Perfect, I have what I need for {trip['destination']}. "
                "Building your trip now…"
                if not missing
                else f"On it! I'll fill in anything you haven't told me "
                f"and build your {trip['destination']} trip now…"
            ),
            "trip": trip_state(trip),
        }

    trip["asked"] = missing
    question, quick_replies = trip_question(trip, missing)

    known = [
        part for part in (
            trip.get("destination"),
            f"from {trip['origin']}" if trip.get("origin") else None,
            describe_trip_dates(trip),
        )
        if part
    ]
    intro = f"Got it: {' · '.join(known)}. " if known else ""

    if trip.get("destination"):
        quick_replies = [*quick_replies, "Generate my trip"]

    return {
        "reply": intro + question,
        "trip": trip_state(trip),
        "quick_replies": quick_replies,
    }


async def get_trip_weather(destination, start, days):
    """Daily forecast for each trip day, or [] if the trip is more than
    a week away (the forecast only covers 7 days)."""
    offset = (start - date.today()).days

    if offset < 0 or offset >= 7:
        return []

    text = await get_weather_text(
        get_location(destination) or destination,
        "get_forecast",
        granularity="daily",
        days=min(offset + days, 7),
    )

    forecast = []

    for _, fields in parse_forecast_blocks(text)[offset:]:
        high = re.search(r"High\s*(-?\d+)", fields.get("temperature", ""))
        low = re.search(r"Low\s*(-?\d+)", fields.get("temperature", ""))
        forecast.append({
            "conditions": fields.get("conditions"),
            "high": int(high.group(1)) if high else None,
            "low": int(low.group(1)) if low else None,
            "rain_chance": fields.get("precipitation chance"),
        })

    return forecast


def pick_trip_flight(flights, outbound, trip_start):
    """Cheapest flight that fits the trip. Outbound must land on day 1 or
    (overnight) day 2, preferably by 16:00; the return should leave from
    12:00. Multi-day journeys are skipped. Returns None if none fit."""
    if outbound:
        latest = (trip_start + timedelta(days=1)).isoformat()
        flights = [flight for flight in flights if flight["arrival_date"] <= latest]

    if not flights:
        return None

    suitable = [
        flight for flight in flights
        if flight["stops"] <= 1
        and (
            flight["arrival_date"] == trip_start.isoformat() and flight["arrival"] <= "16:00"
            if outbound
            else flight["departure"] >= "12:00"
        )
    ]

    return (suitable or flights)[0]


def parse_json_reply(text):
    """Parse JSON from Gemini, tolerating ```json fences."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    return json.loads(text)


def template_itinerary(trip, guide):
    """Basic itinerary when Gemini is unavailable."""
    destination = trip["destination"]
    highlights = guide.get("highlights") or [
        f"{destination} old town", f"a local market in {destination}",
        f"{destination}'s best-known landmark", "a viewpoint at sunset",
    ]
    days = []

    for index in range(trip["days"]):
        place = highlights[index % len(highlights)]

        if index == 0:
            title = "Arrival & first impressions"
            activities = [
                {"time": "17:00", "title": "Check in and freshen up",
                 "description": "Settle into your stay after the flight.", "type": "relax"},
                {"time": "19:00", "title": f"Dinner near {place}",
                 "description": "Try a popular local spot for your first meal.", "type": "food"},
            ]
        elif index == trip["days"] - 1:
            title = "Last morning & departure"
            activities = [
                {"time": "09:00", "title": "Breakfast and souvenir shopping",
                 "description": "Pick up gifts before heading to the airport.", "type": "shopping"},
            ]
        else:
            title = f"Discover {place}"
            activities = [
                {"time": "09:30", "title": f"Visit {place}",
                 "description": "Go early to beat the crowds.", "type": "sight"},
                {"time": "13:00", "title": "Local lunch",
                 "description": "Ask locals for their favourite nearby spot.", "type": "food"},
                {"time": "15:30", "title": "Explore the neighbourhood",
                 "description": "Wander, shop and take photos.", "type": "culture"},
            ]

        days.append({"title": title, "activities": activities})

    tips = [tip for tip in (guide.get("getting_around"), guide.get("tips")) if tip]

    return {
        "title": f"{trip['days']}-Day {destination} Getaway",
        "summary": guide.get("summary") or f"A relaxed first look at {destination}.",
        "days": days,
        "tips": tips or ["The AI planner was unavailable, so this is a basic plan."],
    }


async def get_destination_guide(destination):
    try:
        async with asyncio.timeout(30):
            async with mcp_session(FLIGHT_SERVER_PARAMS) as session:
                result = await session.call_tool(
                    "get_destination_info",
                    arguments={"city": destination},
                )
        guide = get_structured(result) or {}
        return guide if guide.get("highlights") else {}
    except Exception as error:
        print(f"Destination guide error: {error!r}", file=sys.stderr)
        return {}


async def nominatim_search(params):
    """Search OpenStreetMap; returns the result list, or None on errors.
    Successful results are cached."""
    key = json.dumps(params, sort_keys=True)

    # One request at a time, even when searches run in parallel.
    async with nominatim_lock():
        if key in geocode_cache:
            return geocode_cache[key]

        try:
            async with httpx.AsyncClient(timeout=10, headers=NOMINATIM_HEADERS) as http:
                response = await http.get(
                    NOMINATIM_URL,
                    params={"format": "jsonv2", "limit": 1, **params},
                )
                response.raise_for_status()
                results = response.json()
        except (httpx.HTTPError, ValueError) as error:
            print(f"OpenStreetMap error for {params.get('q')!r}: {error!r}", file=sys.stderr)
            return None
        finally:
            # OpenStreetMap's usage policy allows at most 1 request per second.
            await asyncio.sleep(1.1)

        geocode_cache[key] = results
        return results


def nominatim_lock():
    """A lock per event loop (asyncio locks can't be shared between loops)."""
    loop = asyncio.get_running_loop()
    return nominatim_locks.setdefault(loop, asyncio.Lock())


async def geocode(query, near=None):
    """Look up a place on OpenStreetMap. `near` (lat, lng) limits the search
    to about 60 km around it. Returns (lat, lng) or None."""
    params = {"q": query}

    if near:
        lat, lng = near
        params["viewbox"] = f"{lng - 0.6},{lat + 0.6},{lng + 0.6},{lat - 0.6}"
        params["bounded"] = 1

    results = await nominatim_search(params)
    return (float(results[0]["lat"]), float(results[0]["lon"])) if results else None


async def locate_place(name):
    """Confirm a city/town exists. Returns {"name", "lat", "lng",
    "country", "label"} (label like 'Kudat, Sabah, Malaysia') or None."""
    results = await nominatim_search({
        "q": name,
        "limit": 5,
        "addressdetails": 1,
        "accept-language": "en",
    })

    if not results:
        return None

    # "Kudat" first matches the whole Kudat district, whose centre is ~50 km
    # from Kudat town. Prefer the town/city itself when it's close by.
    top = results[0]
    result = next(
        (
            item for item in results
            if item.get("addresstype") in SETTLEMENT_TYPES
            and distance_km(
                {"lat": float(item["lat"]), "lng": float(item["lon"])},
                {"lat": float(top["lat"]), "lng": float(top["lon"])},
            ) < 100
        ),
        top,
    )
    address = result.get("address", {})
    region = address.get("state") or address.get("region")
    country = address.get("country")

    return {
        "name": name,
        "lat": float(result["lat"]),
        "lng": float(result["lon"]),
        "country": country,
        "label": ", ".join(dict.fromkeys(
            part for part in (name, region, country) if part
        )),
    }


def distance_km(a, b):
    """Straight-line distance between two places with "lat"/"lng"."""
    lat1, lng1, lat2, lng2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    )
    return 6371 * 2 * math.asin(math.sqrt(h))


async def keep_real_route(flights, origin, destination):
    """Kiwi.com fuzzy-matches unknown names (e.g. 'Kudat' -> Kudahuvadhoo,
    Maldives). Keep only flights that leave near the origin and land near
    the destination. Returns (kept, rejected, origin_place, destination_place)."""
    origin_place = await locate_place(origin)
    destination_place = await locate_place(destination)

    if not origin_place or not destination_place:
        return flights, [], origin_place, destination_place

    kept, rejected = [], []

    for flight in flights:
        departure = await locate_place(f"{flight['from']}, {flight['from_country']}")
        arrival = await locate_place(f"{flight['to']}, {flight['to_country']}")

        near_enough = all(
            point is None or distance_km(point, target) <= MAX_AIRPORT_DISTANCE_KM
            for point, target in (
                (departure, origin_place),
                (arrival, destination_place),
            )
        )
        (kept if near_enough else rejected).append(flight)

    return kept, rejected, origin_place, destination_place


def clean_place(place):
    """Title, description, type and Wikipedia title of an activity or extra."""
    return {
        "title": str(place.get("title", "")),
        "description": str(place.get("description", "")),
        "type": place.get("type") if place.get("type") in ACTIVITY_TYPES else "sight",
        "place": str(place.get("place") or "").strip(),
        "wikipedia": str(place.get("wikipedia") or "").strip(),
    }


async def wikimedia_get(http, url):
    """GET a Wikimedia URL as JSON, retrying briefly when it is busy.
    Returns None when the page doesn't exist or Wikimedia stays down."""
    for attempt in range(3):
        try:
            response = await http.get(url)
        except httpx.HTTPError as error:
            print(f"Wikimedia error for {url}: {error!r}", file=sys.stderr)
            return None

        if response.status_code == 404:
            return None

        if response.status_code in (429, 502, 503, 504) and attempt < 2:
            await asyncio.sleep(1 + attempt * 2)
            continue

        if response.status_code != 200:
            print(f"Wikimedia {response.status_code} for {url}", file=sys.stderr)
            return None

        try:
            return response.json()
        except ValueError:
            return None

    return None


def is_photo(url):
    # Logos, maps and flags (SVG) are not photos of the place.
    return bool(url) and not re.search(r"\.svg\b", url, re.IGNORECASE)


async def wikipedia_page(http, title):
    """Photo, link and coordinates of a Wikipedia article. `title` may
    carry a language ("fr:Tour Eiffel", as OpenStreetMap stores it) or be
    a Wikidata id ("Q243"). Uses the REST endpoints, which stay up when
    the older w/api.php endpoint is rate-limiting us."""
    if WIKIPEDIA_CACHE.get(title):
        return WIKIPEDIA_CACHE[title]

    page = None

    if re.fullmatch(r"Q\d+", title):
        page = await wikidata_page(http, title)
    else:
        match = re.match(r"([a-z]{2,3}(?:-[a-z]+)?):(.+)", title)
        language, name = match.groups() if match else ("en", title)
        summary = await wikimedia_get(
            http,
            f"https://{language}.wikipedia.org/api/rest_v1/page/summary/"
            + quote(name.strip().replace(" ", "_"), safe=""),
        )

        if summary and summary.get("type") != "disambiguation":
            coordinates = summary.get("coordinates") or {}
            image = (summary.get("thumbnail") or {}).get("source")
            page = {
                "image": image if is_photo(image) else None,
                "url": ((summary.get("content_urls") or {}).get("desktop") or {}).get("page"),
                "lat": coordinates.get("lat"),
                "lng": coordinates.get("lon"),
            }

    # Failures aren't cached, so a busy moment doesn't lose the photo for good.
    if page:
        WIKIPEDIA_CACHE[title] = page

    return page


async def wikidata_page(http, item_id):
    """For places OpenStreetMap links only to Wikidata: the English (or
    any) Wikipedia article, else the item's own photo (P18)."""
    data = await wikimedia_get(
        http, f"https://www.wikidata.org/wiki/Special:EntityData/{item_id}.json"
    )
    entity = ((data or {}).get("entities") or {}).get(item_id)

    if not entity:
        return None

    sitelinks = entity.get("sitelinks") or {}
    article = sitelinks.get("enwiki") or next(
        (link for key, link in sitelinks.items() if re.fullmatch(r"[a-z]{2,3}wiki", key)),
        None,
    )

    if article:
        language = article["site"][:-4]
        page = await wikipedia_page(http, f"{language}:{article['title']}")

        if page and page["image"]:
            return page

    def claim_value(prop):
        for claim in (entity.get("claims") or {}).get(prop, []):
            value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")

            if value:
                return value

        return None

    photo = claim_value("P18")
    coordinates = claim_value("P625") or {}
    image = (
        "https://commons.wikimedia.org/wiki/Special:FilePath/"
        + quote(photo.replace(" ", "_")) + "?width=400"
        if photo else None
    )
    return {
        "image": image if is_photo(photo) else None,
        "url": f"https://www.wikidata.org/wiki/{item_id}",
        "lat": coordinates.get("latitude"),
        "lng": coordinates.get("longitude"),
    }


async def get_wikipedia_images(titles, near=None):
    """Lead photos for Wikipedia articles (see wikipedia_page for the
    accepted title forms). Returns {title: {"image", "url", "far"}} for
    articles that exist. "far" is True when the article's coordinates are
    more than MAX_PLACE_DISTANCE_KM from `near` (a place dict), i.e. a
    wrong match."""
    titles = list(dict.fromkeys(title for title in titles if title))[:60]

    if not titles:
        return {}

    # A few at a time, so Wikimedia doesn't start refusing us.
    limit = asyncio.Semaphore(6)

    async def lookup(http, title):
        async with limit:
            return title, await wikipedia_page(http, title)

    async with httpx.AsyncClient(
        timeout=15, headers=WIKIPEDIA_HEADERS, follow_redirects=True
    ) as http:
        results = await asyncio.gather(*(lookup(http, title) for title in titles))

    images = {}

    for title, page in results:
        if not page:
            continue

        far = bool(
            near and page["lat"] is not None
            and distance_km({"lat": page["lat"], "lng": page["lng"]}, near)
            > MAX_PLACE_DISTANCE_KM
        )
        images[title] = {**page, "far": far}

    found = sum(bool(page["image"]) for page in images.values())
    print(f"Wikipedia photos: {found} of {len(titles)} places", file=sys.stderr)
    return images


def get_highlight_name(plan_day):
    """The day's map pin: Gemini's highlight, or the first sight."""
    name = str((plan_day.get("highlight") or {}).get("name") or "")

    if not name:
        name = next(
            (
                str(activity.get("title", ""))
                for activity in plan_day.get("activities", [])
                if activity.get("type") in ("sight", "culture", "nature")
            ),
            "",
        )

    return clean_place_name(name)


def clean_place_name(name):
    """'Lunch at Mia Seafood (local favourite)' -> 'Mia Seafood': map
    searches miss places when extra words are included."""
    name = re.sub(r"\s*\(.*?\)", "", name)
    name = re.sub(
        r"^(visit(ing)?|explore|lunch at|dinner at|breakfast at|coffee at|"
        r"check-in at|check in at|stay at|walk (along|at|on))\s+",
        "",
        name,
        flags=re.IGNORECASE,
    )
    name = re.sub(r"\s+(visit|tour|walk|trip|stroll)$", "", name, flags=re.IGNORECASE)
    return name.strip()


async def add_day_pins(destination, plan_days, itinerary_days, center=None):
    """Give each day one map pin, located on OpenStreetMap. Gemini's own
    coordinates are used only if OpenStreetMap can't find the place and
    they're close to the city. Returns the city's (lat, lng) or None."""
    center = center or await geocode(destination)

    for plan_day, day in zip(plan_days, itinerary_days):
        day["pin"] = None
        name = get_highlight_name(plan_day)

        if not name:
            continue

        point = await geocode(name, near=center) if center else await geocode(
            f"{name}, {destination}"
        )
        source = "openstreetmap"

        if not point and center:
            highlight = plan_day.get("highlight") or {}

            try:
                lat, lng = float(highlight["lat"]), float(highlight["lng"])
            except (KeyError, TypeError, ValueError):
                continue

            if abs(lat - center[0]) < 0.6 and abs(lng - center[1]) < 0.6:
                point, source = (lat, lng), "ai-estimate"

        if point:
            day["pin"] = {
                "name": name,
                "lat": point[0],
                "lng": point[1],
                "source": source,
            }

    return center


async def verify_places(places, wiki_pages, center):
    """Mark each named place as verified (found on Wikipedia near the
    destination, or on OpenStreetMap near it) or not, and give verified
    places map coordinates. General activities ("Lunch nearby", travel)
    get None. AI can invent plausible-sounding venues, especially in small
    towns; the UI flags unverified ones."""
    lookups = 0

    for place in places:
        name = clean_place_name(place.pop("place") or place["wikipedia"])
        wiki = wiki_pages.get(place.pop("wikipedia"), {})
        place["verified"], place["lat"], place["lng"] = None, None, None

        if not name:
            continue

        if wiki and not wiki["far"] and wiki.get("url"):
            place["verified"] = True

            if wiki.get("lat") is not None:
                place["lat"], place["lng"] = wiki["lat"], wiki["lng"]
                continue

        if center and lookups < MAX_PLACE_LOOKUPS:
            lookups += 1
            point = await geocode(name, near=center)

            if point:
                place["verified"] = True
                place["lat"], place["lng"] = point
            elif place["verified"] is None:
                place["verified"] = False


async def run_overpass(query):
    """Run an OpenStreetMap Overpass query on all mirrors at once (public
    servers are often busy) and return the first answer's elements, or
    None if every mirror failed."""

    async def ask(url):
        async with httpx.AsyncClient(timeout=20, headers=NOMINATIM_HEADERS) as http:
            response = await http.post(url, data={"data": query})
            response.raise_for_status()
            return response.json().get("elements", [])

    tasks = [asyncio.create_task(ask(url)) for url in OVERPASS_URLS]

    try:
        for finished in asyncio.as_completed(tasks):
            try:
                return await finished
            except (httpx.HTTPError, ValueError) as error:
                print(f"Overpass mirror failed: {error!r}", file=sys.stderr)
    finally:
        for task in tasks:
            task.cancel()

    return None


async def find_places_by_search(center):
    """Fallback when every Overpass mirror is down: category searches on
    OpenStreetMap's normal search, limited to the area around `center`."""
    lat, lng = center
    places = []

    for phrase in PLACE_SEARCH_PHRASES:
        results = await nominatim_search({
            "q": phrase,
            "limit": 25,
            "viewbox": f"{lng - 0.45},{lat + 0.45},{lng + 0.45},{lat - 0.45}",
            "bounded": 1,
            "extratags": 1,
            "accept-language": "en",
        }) or []

        for result in results:
            name = (result.get("name") or "").strip()

            if name:
                places.append({
                    "tags": {
                        result.get("category") or result.get("class", ""): result.get("type", ""),
                        **(result.get("extratags") or {}),
                        "name": name,
                    },
                    "lat": float(result["lat"]),
                    "lon": float(result["lon"]),
                })

    return places


def osm_category(tags):
    for activity_type, key, pattern in OSM_CATEGORIES:
        if re.search(pattern, tags.get(key, "")):
            return activity_type

    return "sight"


async def find_real_places(center):
    """Named attractions, nature spots and places to eat near `center`
    (lat, lng), straight from OpenStreetMap. The itinerary may only name
    places from this list. Notable places (with a Wikipedia/Wikidata link)
    come first. Returns [] if OpenStreetMap is unavailable."""
    lat, lng = center
    places = []

    # Small towns need a wider search to find enough to do.
    for radius in (15000, 45000):
        # A bounding box is much cheaper for the busy servers than "around".
        lat_step = radius / 111_000
        lng_step = radius / (111_000 * max(math.cos(math.radians(lat)), 0.2))
        around = f"({lat - lat_step},{lng - lng_step},{lat + lat_step},{lng + lng_step})"
        query = (
            "[out:json][timeout:18];("
            f'nwr["tourism"~"^(attraction|viewpoint|museum|gallery|zoo|theme_park|aquarium)$"]["name"]{around};'
            f'nwr["natural"~"^(beach|peak|waterfall|cave_entrance|bay|cape|hot_spring)$"]["name"]{around};'
            f'nwr["place"~"^(island|islet)$"]["name"]{around};'
            f'nwr["leisure"~"^(park|nature_reserve|garden)$"]["name"]{around};'
            f'nwr["historic"~"^(monument|memorial|castle|fort|ruins|archaeological_site)$"]["name"]{around};'
            ")->.sights;("
            f'nwr["amenity"~"^(restaurant|cafe|food_court)$"]["name"]{around};'
            f'nwr["amenity"="marketplace"]["name"]{around};'
            ")->.food;"
            ".sights out center tags 250;.food out center tags 120;"
        )
        elements = await run_overpass(query)

        if elements is None:
            elements = await find_places_by_search(center)
            radius = 45000  # the fallback search can't widen further

        places, seen = [], set()

        for element in elements:
            tags = element.get("tags", {})
            name = (tags.get("name:en") or tags.get("name") or "").strip()
            point = element if "lat" in element else element.get("center", {})

            # Skip sign-like or placeholder names ("To Tanjung …", "Warung + shop").
            if (
                not name
                or name.lower() in seen
                or "lat" not in point
                or re.match(r"(?i)^(to|ke|ke arah)\s", name)
                or "+" in name
            ):
                continue

            seen.add(name.lower())
            wikipedia = tags.get("wikipedia", "")
            place = {
                "name": name,
                "lat": point["lat"],
                "lng": point["lon"],
                "type": osm_category(tags),
                # Its photo source: "lang:Title" as tagged (e.g. "fr:Musée
                # du Louvre"), or else its Wikidata id.
                "wikipedia": wikipedia or tags.get("wikidata", ""),
                "notable": bool(tags.get("wikidata") or wikipedia),
            }
            place["distance_km"] = round(distance_km(place, {"lat": lat, "lng": lng}), 1)
            places.append(place)

        if sum(place["type"] != "food" for place in places) >= 15 or radius == 45000:
            break

    places.sort(key=lambda place: (not place["notable"], place["distance_km"]))
    sights = [place for place in places if place["type"] != "food"][:80]
    food = [place for place in places if place["type"] == "food"][:40]

    for number, place in enumerate(sights + food, start=1):
        place["id"] = number

    return sights + food


async def drive_legs(points):
    """[(km, minutes)] for driving between consecutive {lat, lng} points,
    using OSRM road routing. Falls back to a straight-line estimate."""
    if len(points) < 2:
        return []

    coordinates = ";".join(f"{point['lng']:.6f},{point['lat']:.6f}" for point in points)

    try:
        async with httpx.AsyncClient(timeout=15, headers=NOMINATIM_HEADERS) as http:
            response = await http.get(f"{OSRM_URL}{coordinates}", params={"overview": "false"})
            response.raise_for_status()
            data = response.json()

        if data.get("code") == "Ok":
            return [
                (leg["distance"] / 1000, leg["duration"] / 60)
                for leg in data["routes"][0]["legs"]
            ]
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as error:
        print(f"OSRM error: {error!r}", file=sys.stderr)

    # No road route (e.g. islands): straight line x1.35 at 40 km/h.
    return [
        (distance_km(a, b) * 1.35, distance_km(a, b) * 1.35 / 40 * 60)
        for a, b in zip(points, points[1:])
    ]


def parse_minutes(text):
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(text or "").strip())
    return int(match.group(1)) * 60 + int(match.group(2)) if match else None


def format_minutes(minutes):
    minutes = min(max(int(minutes), 0), 23 * 60 + 55)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def round_up_5(minutes):
    return -(-int(minutes) // 5) * 5


def format_drive(km, minutes):
    hours, rest = divmod(round(minutes), 60)
    duration = f"{hours} h {rest} min" if hours else f"{rest} min"
    return f"about {round(km)} km, {duration}"


async def schedule_day(day, start_minutes, end_minutes, start_point):
    """Give the day realistic times: real driving time between stops
    (OSRM) plus typical visit lengths. Gemini's time is kept only when it's
    later than possible and not a long idle gap. Stops that can't fit
    before `end_minutes` are dropped. Returns (drive_km, drive_minutes)."""
    activities = day["activities"]

    if not activities:
        return 0, 0

    # Where each stop happens: its own location, or the previous one's.
    positions, current = [], start_point

    for activity in activities:
        if activity.get("lat") is not None:
            current = {"lat": activity["lat"], "lng": activity["lng"]}

        positions.append(current)

    route = [start_point or positions[0]] + positions
    unique, index_of = [], []

    for point in route:
        if point and (not unique or (point["lat"], point["lng"]) != (unique[-1]["lat"], unique[-1]["lng"])):
            unique.append(point)

        index_of.append(len(unique) - 1)

    legs = await drive_legs(unique) if len(unique) > 1 else []

    clock, kept, total_km, total_minutes = start_minutes, [], 0, 0

    for index, activity in enumerate(activities):
        a, b = index_of[index], index_of[index + 1]
        km, minutes = legs[a] if b == a + 1 and a < len(legs) else (0, 0)
        travel = minutes if km > 0.3 else 10
        earliest = round_up_5(clock + travel)
        wanted = parse_minutes(activity.get("time"))
        begin = wanted if wanted and earliest <= wanted <= earliest + 150 else earliest
        duration = VISIT_MINUTES.get(activity["type"], 60)

        # Doesn't fit before the flight / drive home: leave it out.
        if end_minutes and begin + duration > end_minutes:
            continue

        activity["time"] = format_minutes(begin)
        kept.append(activity)
        clock = begin + duration
        total_km += km
        total_minutes += minutes

    day["activities"] = kept
    return total_km, total_minutes


def unknown_names(text, known):
    """Proper names in `text` (two or more capitalised words, e.g.
    'Pasir Panjang Beach') that aren't real places we know about."""
    names = []

    for match in re.finditer(
        r"\b[A-Z][\w'’.-]*(?:\s+(?:of|de|la|the|&|and|bin|binti)?\s*[A-Z][\w'’.-]*)+",
        text or "",
    ):
        phrase = match.group(0).strip().rstrip(".,;:!?'’")
        words = [
            word.lower().strip(".,'’")
            for word in phrase.split()
            if word.lower() not in NAME_LINK_WORDS
        ]

        if len(words) < 2 or all(word in GENERIC_WORDS for word in words):
            continue

        if re.search(r"\b(Sea|Ocean|Strait|Gulf)$", phrase):
            continue

        lower = phrase.lower()

        if any(lower in name or name in lower for name in known):
            continue

        names.append(phrase)

    return names


def drop_unknown_sentences(text, known):
    """Remove sentences that mention places we couldn't confirm."""
    sentences = re.split(r"(?<=[.!?])\s+", text or "")
    return " ".join(
        sentence for sentence in sentences if not unknown_names(sentence, known)
    ).strip()


def template_from_places(days, candidates, destination):
    """A plan built only from real OpenStreetMap places, used when Gemini
    is unavailable."""
    sights = [place for place in candidates if place["type"] != "food"]
    food = [place for place in candidates if place["type"] == "food"]
    plan_days = []

    for index in range(days):
        day_sights = sights[index * 2:index * 2 + 2]
        activities = [
            {"time": "09:30", "title": f"Visit {place['name']}", "type": place["type"],
             "place_id": place["id"], "description": ""}
            for place in day_sights
        ]

        if index < len(food):
            activities.insert(1, {
                "time": "12:30", "title": f"Lunch at {food[index]['name']}", "type": "food",
                "place_id": food[index]["id"], "description": "",
            })

        plan_days.append({
            "title": f"{day_sights[0]['name']} & around" if day_sights else f"Exploring {destination}",
            "highlight_id": day_sights[0]["id"] if day_sights else None,
            "activities": activities,
        })

    return {
        "title": f"{days}-Day {destination} Trip",
        "summary": f"A plan built from real places in and around {destination}.",
        "days": plan_days,
        "extras": [{"place_id": place["id"], "description": ""} for place in sights[days * 2:days * 2 + 4]],
        "tips": [],
    }


async def build_itinerary(trip):
    """Live flights + weather + Gemini -> a day-by-day itinerary."""
    origin, destination = trip["origin"], trip["destination"]
    start, days = trip["start"], trip["days"]
    end = start + timedelta(days=days - 1)

    # Real coordinates and full names ("Kudat, Sabah, Malaysia") so neither
    # Kiwi.com nor Gemini can mix the place up with a similar name.
    places = trip.get("places", {})
    origin_place = places.get("origin") or await locate_place(origin)
    destination_place = places.get("destination") or await locate_place(destination)
    origin_label = origin_place["label"] if origin_place else origin
    destination_label = destination_place["label"] if destination_place else destination
    weather_place = (
        f"{destination}, {destination_place['country']}"
        if destination_place and destination_place["country"] else destination
    )

    outbound, inbound, weather = await asyncio.gather(
        search_flights(origin, destination, start, {}),
        search_flights(destination, origin, end, {}),
        get_trip_weather(weather_place, start, days),
        return_exceptions=True,
    )

    for name, result in (("outbound", outbound), ("return", inbound), ("weather", weather)):
        if isinstance(result, Exception):
            print(f"Trip {name} error: {result!r}", file=sys.stderr)

    outbound_flight = pick_trip_flight(outbound, True, start) if isinstance(outbound, list) else None
    return_flight = pick_trip_flight(inbound, False, start) if isinstance(inbound, list) else None
    weather = weather if isinstance(weather, list) else []

    # Day the outbound flight lands on (overnight flights land on day 2).
    arrival_index = (
        (date.fromisoformat(outbound_flight["arrival_date"]) - start).days
        if outbound_flight else 0
    )

    # Nearby places often have no flights at all (Kota Kinabalu -> Kudat).
    ground_travel = None

    if not outbound_flight and not return_flight and origin_place and destination_place:
        if distance_km(origin_place, destination_place) < 800:
            [(road_km, road_minutes)] = await drive_legs([origin_place, destination_place])
            ground_travel = {
                "distance_km": round(road_km),
                "minutes": round(road_minutes),
            }

    center = (
        (destination_place["lat"], destination_place["lng"])
        if destination_place else None
    )

    # The only named places the plan may use: real ones from OpenStreetMap.
    candidates = await find_real_places(center) if center else []
    candidates_by_id = {place["id"]: place for place in candidates}

    if ground_travel:
        travel_lines = (
            f"- There are NO flights between {origin} and {destination}; they "
            f"travel by road ({format_drive(ground_travel['distance_km'], ground_travel['minutes'])}). "
            "Do NOT add the drive to or from "
            f"{origin} as an activity; it is added automatically. Day 1 starts "
            "around midday after the drive, and the last day ends mid-afternoon.\n"
        )
    else:
        travel_lines = (
            (
                f"- Day {arrival_index + 1}: flight {', '.join(outbound_flight['flight_numbers'])} "
                f"lands at {outbound_flight['to_airport']} ({outbound_flight['to']}) at "
                f"{outbound_flight['arrival']}. Start activities about 2 hours later"
                + (", and keep Day 1 for travelling" if arrival_index else "")
                + ".\n"
                if outbound_flight
                else "- No outbound flight was found; don't plan around a flight time.\n"
            )
            + (
                f"- Day {days}: the return flight leaves {return_flight['from_airport']} "
                f"at {return_flight['departure']}. Finish activities 3 hours before.\n"
                if return_flight else ""
            )
        )

    prompt = (
        f"You are an expert travel planner. Build a {days}-day itinerary for "
        f"{destination_label}"
        + (
            f" (coordinates {destination_place['lat']:.4f}, {destination_place['lng']:.4f})"
            if destination_place else ""
        )
        + ".\n"
        f"- Travelling from: {origin_label}\n"
        f"- Dates: {start:%A %d %B %Y} to {end:%A %d %B %Y} — exactly {days} "
        "days. Do not shorten or lengthen the trip.\n"
        f"- Travellers: {trip['travellers']}\n"
        f"- Interests and budget style: {trip['interests']}\n"
        + travel_lines
        + (f"- Daily weather: {json.dumps(weather)}\n" if weather else "")
        + "\nREAL PLACES (from OpenStreetMap; id. name (type, km from centre)):\n"
        + "\n".join(
            f"{place['id']}. {place['name']} ({place['type']}, {place['distance_km']} km)"
            for place in candidates
        )
        + "\n\nRules:\n"
        "- 2 to 4 activities per day (fewer on travel days).\n"
        "- EVERY specific named place (attraction, beach, museum, restaurant, "
        "market) MUST come from the REAL PLACES list, referenced by its "
        '"place_id". Never name any place that is not in the list, in titles, '
        "descriptions, day titles, the summary or tips.\n"
        "- Anything else must be a general activity with place_id null and no "
        'proper names, written in sentence case (e.g. "Seafood lunch in town", '
        '"Relax at the hotel").\n'
        "- Group each day's places so they are close together. Match the "
        "interests and budget style. Prefer indoor places on rainy days.\n\n"
        "Reply with JSON only, in this shape:\n"
        '{"title": "5-Day Kudat Nature & Coast Trip", '
        '"summary": "Two sentences on why this trip suits them.", '
        '"days": [{"title": "Short day title", "highlight_id": 3, '
        '"activities": [{"time": "09:00", "title": "Visit <place name>", '
        '"description": "One helpful sentence.", "type": "sight", "place_id": 3}, '
        '{"time": "12:30", "title": "Seafood lunch in town", "description": '
        '"One helpful sentence.", "type": "food", "place_id": null}]}], '
        '"extras": [{"place_id": 12, "description": "Why it is worth adding."}], '
        '"tips": ["Three short practical tips without place names."]}\n'
        f'"days" must have exactly {days} items. "type" is one of: sight, '
        "food, culture, shopping, nature, nightlife, relax, transport. "
        '"highlight_id" is the day\'s most important place from the list. '
        '"extras" lists 3 to 5 more places from the list that are NOT used in '
        "the days."
    )

    plan = None

    try:
        # Lite models answer in seconds; gemini-3.8-flash can take minutes
        # when busy, so it's the last resort here.
        response = await asyncio.to_thread(
            generate_with_fallback,
            prompt,
            types.GenerateContentConfig(response_mime_type="application/json"),
            [*FALLBACK_MODELS, MODEL],
            60,
        )
        plan = parse_json_reply(response.text)

        if not isinstance(plan.get("days"), list) or not plan["days"]:
            raise ValueError("No days in itinerary")
    except Exception as error:
        print(f"Itinerary Gemini error: {error!r}", file=sys.stderr)
        plan = template_from_places(days, candidates, destination)

    plan_days = [day for day in plan["days"] if isinstance(day, dict)][:days]

    # Gemini occasionally returns fewer days; pad with free days.
    while len(plan_days) < days:
        plan_days.append({
            "title": "Free day",
            "activities": [{
                "time": "10:00", "title": "Free time to explore at your own pace",
                "description": "", "type": "relax", "place_id": None,
            }],
        })

    # Names we know are real: the OpenStreetMap list and the trip's places.
    known = {place["name"].lower() for place in candidates} | {
        part.strip().lower()
        for label in (destination_label, origin_label)
        for part in label.split(",")
        if part.strip()
    }
    removed = []

    def place_for(item):
        try:
            return candidates_by_id.get(int(item.get("place_id")))
        except (TypeError, ValueError):
            return None

    async def to_activity(item):
        """A real listed place, a general activity, or None when it names
        a place we can't confirm near the destination."""
        title = str(item.get("title") or "").strip()

        if not title:
            return None

        place = place_for(item)
        activity_type = item.get("type") if item.get("type") in ACTIVITY_TYPES else None
        activity = {
            "time": str(item.get("time") or ""),
            "title": title,
            "description": "",
            "type": activity_type or (place["type"] if place else "sight"),
            "wikipedia": "",
            "lat": None,
            "lng": None,
            "verified": None,
        }

        if place:
            # The title must be about this place, not some other one.
            if unknown_names(title, known):
                verb = "Lunch at" if place["type"] == "food" else "Visit"
                activity["title"] = f"{verb} {place['name']}"

            activity.update(
                wikipedia=place["wikipedia"],
                lat=place["lat"],
                lng=place["lng"],
                verified=True,
            )
        else:
            names = unknown_names(title, known)

            if names:
                # Names a place outside the list: keep it only if it
                # really exists near the destination.
                point = await geocode(names[0], near=center) if center else None

                if not point:
                    removed.append(title)
                    return None

                known.add(names[0].lower())
                activity.update(lat=point[0], lng=point[1], verified=True)

        activity["description"] = drop_unknown_sentences(
            str(item.get("description") or ""), known
        )
        return activity

    itinerary_days = []

    for index, day in enumerate(plan_days):
        activities = []

        for item in day.get("activities", []):
            if not isinstance(item, dict):
                continue

            # On road trips the drives to/from the origin are added below.
            if ground_travel and item.get("type") == "transport" and re.search(
                rf"\b(drive|driving|journey|travel|transfer|road trip|{re.escape(origin.lower())})\b",
                str(item.get("title", "")).lower(),
            ):
                continue

            activity = await to_activity(item)

            if activity:
                activities.append(activity)

        highlight = place_for({"place_id": day.get("highlight_id")})
        pin_activity = next((a for a in activities if a["lat"] is not None), None)
        title = str(day.get("title") or "").strip()

        if not title or unknown_names(title, known):
            title = f"{highlight['name']} & around" if highlight else f"Exploring {destination}"

        itinerary_days.append({
            "day": index + 1,
            "date": (start + timedelta(days=index)).isoformat(),
            "title": title,
            "weather": weather[index] if index < len(weather) else None,
            "activities": activities,
            "pin": (
                {"name": highlight["name"], "lat": highlight["lat"],
                 "lng": highlight["lng"], "source": "openstreetmap"}
                if highlight
                else {"name": pin_activity["title"], "lat": pin_activity["lat"],
                      "lng": pin_activity["lng"], "source": "openstreetmap"}
                if pin_activity else None
            ),
            "flight_in": outbound_flight if index == arrival_index else None,
            "flight_out": return_flight if index == days - 1 else None,
        })

    if removed:
        print(f"Removed unconfirmed places: {removed}", file=sys.stderr)

    # Realistic times from real driving times, plus the road-trip drives.
    center_point = {"lat": center[0], "lng": center[1]} if center else None

    for index, day in enumerate(itinerary_days):
        start_minutes, end_minutes = 9 * 60, 21 * 60 + 30

        if outbound_flight and index == arrival_index:
            start_minutes = parse_minutes(outbound_flight["arrival"]) + 90

        if ground_travel and index == 0:
            start_minutes = 8 * 60 + ground_travel["minutes"]

        if index == days - 1:
            if return_flight:
                end_minutes = parse_minutes(return_flight["departure"]) - 180
            elif ground_travel:
                end_minutes = 15 * 60 + 30

        km, minutes = await schedule_day(day, start_minutes, end_minutes, center_point)

        if ground_travel and index == 0:
            day["activities"].insert(0, {
                "time": "08:00",
                "title": f"Drive from {origin} to {destination}",
                "description": f"By road, {format_drive(ground_travel['distance_km'], ground_travel['minutes'])}.",
                "type": "transport", "wikipedia": "", "lat": None, "lng": None, "verified": None,
            })
            km += ground_travel["distance_km"]
            minutes += ground_travel["minutes"]

        if ground_travel and index == days - 1:
            last = day["activities"][-1] if day["activities"] else None
            leave = (
                parse_minutes(last["time"]) + VISIT_MINUTES.get(last["type"], 60)
                if last else 10 * 60
            )
            day["activities"].append({
                "time": format_minutes(round_up_5(leave)),
                "title": f"Drive back to {origin}",
                "description": f"By road, {format_drive(ground_travel['distance_km'], ground_travel['minutes'])}.",
                "type": "transport", "wikipedia": "", "lat": None, "lng": None, "verified": None,
            })
            km += ground_travel["distance_km"]
            minutes += ground_travel["minutes"]

        day["drive_km"] = round(km, 1)
        day["drive_minutes"] = round(minutes)

    used_ids = {
        place["id"]
        for day in plan_days
        for item in day.get("activities", [])
        if isinstance(item, dict) and (place := place_for(item))
    }
    extras = []

    for item in plan.get("extras", []):
        place = place_for(item) if isinstance(item, dict) else None

        if place and place["id"] not in used_ids:
            used_ids.add(place["id"])
            extras.append({
                "title": place["name"],
                "description": drop_unknown_sentences(str(item.get("description") or ""), known),
                "type": place["type"],
                "wikipedia": place["wikipedia"],
                "lat": place["lat"],
                "lng": place["lng"],
                "verified": True,
            })

    all_places = [place for day in itinerary_days for place in day["activities"]] + extras[:5]
    extras = extras[:5]

    # Photos only from each place's own Wikipedia link in OpenStreetMap.
    images = await get_wikipedia_images(
        [destination] + [place["wikipedia"] for place in all_places],
        near=destination_place,
    )

    for place in all_places:
        found = images.get(place.pop("wikipedia"), {})
        usable = found.get("image") and not found.get("far")
        place["image"] = found.get("image") if usable else None
        place["wiki_url"] = found.get("url") if usable else None

    map_center = center

    flights_total = sum(
        flight["price"] for flight in (outbound_flight, return_flight) if flight
    )

    # The title must match the real trip length ("2-Day ..." for a 5-day trip
    # would be wrong).
    title = re.sub(
        r"\b\d+\s*-?\s*Days?\b",
        f"{days}-Day",
        plan.get("title") or f"{days}-Day {destination} Trip",
        flags=re.IGNORECASE,
    )

    if unknown_names(title, known):
        title = f"{days}-Day {destination} Trip"

    destination_photo = images.get(destination, {})
    hero_image = (
        f"https://images.kiwi.com/photos/600x600/{outbound_flight['image_id']}.jpg"
        if outbound_flight and outbound_flight.get("image_id")
        else None if destination_photo.get("far") else destination_photo.get("image")
    )

    return {
        "title": title,
        "summary": drop_unknown_sentences(str(plan.get("summary") or ""), known),
        "destination": destination,
        "origin": origin,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days_count": days,
        "travellers": trip["travellers"],
        "interests": trip["interests"],
        "map_center": (
            {"lat": map_center[0], "lng": map_center[1]} if map_center else None
        ),
        "destination_label": destination_label,
        "image": hero_image,
        "flights": {"outbound": outbound_flight, "return": return_flight},
        "ground_travel": ground_travel,
        "flights_total": flights_total or None,
        "days": itinerary_days,
        "extras": extras,
        "tips": [
            tip
            for tip in (drop_unknown_sentences(str(tip), known) for tip in plan.get("tips", []))
            if tip
        ][:5],
    }


async def generate_trip():
    """Fill missing details with defaults, then build the itinerary."""
    trip = memory["trip"]

    if not trip or not trip.get("destination"):
        return {
            "reply": "Tell me where you'd like to go first, e.g. 'Plan me 6d5n in Mumbai'.",
        }

    filled_in = []

    for key, default, label in (
        ("origin", "Kuala Lumpur", "flying from Kuala Lumpur"),
        ("start", date.today() + timedelta(days=7), "starting next week"),
        ("days", 3, "3 days"),
        ("travellers", "Solo", "a solo trip"),
        ("interests", "Local highlights", "local highlights"),
    ):
        if not trip.get(key):
            trip[key] = default
            filled_in.append(label)

    trip["stage"] = "done"
    itinerary = await build_itinerary(trip)
    trip["itinerary"] = itinerary

    # Follow-up flight and weather questions use this trip.
    if itinerary["flights"]["outbound"]:
        flight_reply(
            trip["origin"],
            trip["destination"],
            trip["start"],
            [itinerary["flights"]["outbound"]],
            {},
        )

    memory["weather_location"] = (
        get_location(trip["destination"]) or itinerary["destination_label"]
    )

    experiences = sum(len(day["activities"]) for day in itinerary["days"])
    reply = (
        f"Here's your {itinerary['title']}! {itinerary['days_count']} days, "
        f"{experiences} experiences"
    )

    if itinerary["flights_total"]:
        reply += f", with return flights from RM {itinerary['flights_total']}"

    reply += ". " + (itinerary["summary"] or "")

    if itinerary["ground_travel"]:
        reply += (
            f"\n\nThere are no flights between {trip['origin']} and "
            f"{trip['destination']} (about {itinerary['ground_travel']['distance_km']} km "
            "apart), so I've planned the journey by road."
        )
    elif not itinerary["flights"]["outbound"] or not itinerary["flights"]["return"]:
        reply += "\n\nI couldn't find suitable flights for every leg on these dates."

    if filled_in:
        reply += f"\n\nI assumed {', '.join(filled_in)}. Tell me if you'd like to change anything."

    return {
        "reply": reply.strip(),
        "trip": {**trip_state(trip), "itinerary": itinerary},
        "quick_replies": ["Show itinerary", "Show flights", "Plan another trip"],
    }


# --------------------------------------------------
# Request handlers
# --------------------------------------------------

async def handle_arrival_weather(user_prompt):
    """Answer 'What's the weather in Bangkok when I arrive?' using the
    top flight from the last search."""
    last = memory["flight"]
    asked_location = get_location(user_prompt)

    if not last or not last["flights"]:
        return {
            "reply": (
                "Search for a flight first (e.g. 'KUL to Bangkok tomorrow'), "
                "then ask about the weather when you arrive."
            )
        }

    flight = last["flights"][0]
    destination = flight["to"]
    destination_location = get_location(destination) or destination

    names_destination = destination.lower() in user_prompt.lower()

    if asked_location and asked_location != destination_location and not names_destination:
        return {
            "reply": (
                f"Your last search was to {destination}. Search for a flight "
                f"to {asked_location} first, then ask again."
            )
        }

    arrival_date = date.fromisoformat(flight["arrival_date"])
    days_ahead = (arrival_date - date.today()).days
    intro = (
        f"Your {flight['airline']} flight {flight['flight_numbers'][0]} lands "
        f"at {flight['to_airport']} ({destination}) at {flight['arrival']} "
        f"{describe_day(arrival_date)}."
    )

    if days_ahead > 6:
        return {
            "reply": (
                f"{intro} That's more than a week away, so there's no hourly "
                "forecast yet. Ask again closer to the date."
            )
        }

    hour, minute = map(int, flight["arrival"].split(":"))

    # Round to the nearest forecast hour.
    if minute >= 30:
        hour = min(hour + 1, 23)

    # "standard" detail caps hourly output at 48 hours.
    weather_text = await get_weather_text(
        destination_location,
        "get_forecast",
        granularity="hourly",
        days=max(days_ahead + 1, 2),
        detail="full" if days_ahead > 1 else "standard",
    )

    memory["topic"] = "weather"
    memory["weather_location"] = destination_location
    memory["weather_prompt"] = user_prompt

    answer = answer_for_hour(
        user_prompt,
        destination_location,
        weather_text,
        hour,
        target_date=arrival_date,
    )

    if not answer:
        return {"reply": f"{intro} I couldn't find the forecast for that time."}

    return {"reply": f"{intro} {answer}"}


async def handle_weather(user_prompt, weather_topic):
    weather_location = (
        get_location(user_prompt) or memory["weather_location"]
    )

    if not weather_location:
        return {
            "reply": (
                "Which city would you like the weather for? "
                "For example: Kuala Lumpur, Singapore or Bangkok."
            )
        }

    memory["topic"] = "weather"
    memory["weather_location"] = weather_location

    # Keep the original question as the topic for later follow-ups.
    if not weather_topic:
        memory["weather_prompt"] = user_prompt

    tool_name = get_weather_tool(user_prompt)
    requested_hour = get_requested_hour(user_prompt)

    # A specific time needs the hourly forecast.
    if requested_hour is not None:
        tool_name = "get_forecast"

    options = {}

    if tool_name == "get_forecast":
        if needs_hourly_forecast(user_prompt):
            options = {"granularity": "hourly", "days": 2}
        else:
            options = {"granularity": "daily", "days": 7}

    elif tool_name == "get_weather_summary":
        options = {"include": ["current", "forecast", "alerts"], "days": 2}

    weather_text = await get_weather_text(weather_location, tool_name, **options)

    if requested_hour is not None:
        short_answer = answer_for_hour(
            user_prompt,
            weather_location,
            weather_text,
            requested_hour,
            topic=weather_topic,
        )

        if short_answer:
            return {"reply": short_answer}

    return {
        "reply": (
            f"Weather for {weather_location}\n\n"
            f"{weather_text}\n\n"
            "Weather forecasts are estimates and may change."
        )
    }


async def handle_flights(user_prompt):
    filters = parse_flight_filters(user_prompt)
    travel_date = parse_travel_date(user_prompt)

    # "Which one is the most expensive?" -> one flight, not the list again.
    order = get_superlative(user_prompt)

    if order and is_pick_question(user_prompt):
        target = get_pick_target(user_prompt, filters, travel_date)

        if target:
            return await pick_reply(*target, order)

    # Simple routes like "KUL to Bangkok tomorrow" don't need Gemini.
    route = parse_route(user_prompt)

    if route:
        origin, destination = route
        travel_date = travel_date or date.today() + timedelta(days=1)
    else:
        follow_up = get_follow_up_route(user_prompt, filters, travel_date)

        if follow_up:
            origin, destination, filters, travel_date = follow_up
            route = (origin, destination)

    if route:
        flights = await search_flights(origin, destination, travel_date, filters)
        return flight_reply(origin, destination, travel_date, flights, filters)

    # Everything else (unclear requests, questions about the results)
    # goes to Gemini, with the last search as context.
    prompt = (
        "You are FlightMate, a flight assistant that uses live Kiwi.com data. "
        f"Today is {date.today():%A %d %B %Y}.\n"
        "- If the user wants flight options for a route, date or filters, "
        "call search_flights.\n"
        "- If they ask about the previous results (times, prices, stops, "
        "duration, airports, baggage, which is best), answer briefly from "
        "those results only. Use RM for MYR prices and 24-hour times.\n"
        "- If a new search is missing the origin or destination, ask for it.\n"
        "- Never invent flights. Plain text only, no markdown, and don't "
        "mention data field names.\n\n"
        f"{flight_context()}\n\n"
        f"User: {user_prompt}"
    )

    try:
        response = await asyncio.to_thread(
            generate_with_fallback,
            prompt,
            types.GenerateContentConfig(
                tools=[types.Tool(function_declarations=[SEARCH_FLIGHTS_DECLARATION])]
            ),
        )
    except errors.APIError as error:
        print(f"Gemini error: {error.code} {error.message}", file=sys.stderr)

        return {
            "reply": (
                "The AI service is unavailable right now, so I couldn't "
                "understand that request. Try again in a minute, or ask in "
                "the form 'KUL to Bangkok tomorrow'."
            )
        }

    for call in response.function_calls or []:
        arguments = dict(call.args or {})

        if (
            call.name != "search_flights"
            or not arguments.get("origin")
            or not arguments.get("destination")
        ):
            continue

        # Filters read locally are more reliable than Gemini's guesses.
        gemini_filters = {}

        if arguments.get("max_price_rm"):
            gemini_filters["max_price_rm"] = int(arguments["max_price_rm"])

        if arguments.get("airline"):
            known = AIRLINES.get(str(arguments["airline"]).lower())
            gemini_filters["airline"] = known[0] if known else str(arguments["airline"])

        if arguments.get("direct_only"):
            gemini_filters["direct"] = True

        filters = {**gemini_filters, **filters}

        try:
            gemini_date = date.fromisoformat(str(arguments.get("date")))
        except ValueError:
            gemini_date = None

        travel_date = (
            travel_date or gemini_date or date.today() + timedelta(days=1)
        )

        origin = get_flight_city(str(arguments["origin"]))
        destination = get_flight_city(str(arguments["destination"]))
        flights = await search_flights(origin, destination, travel_date, filters)

        return flight_reply(origin, destination, travel_date, flights, filters)

    return {
        "reply": response.text
        or (
            "Please tell me where you're flying from and to, e.g. "
            "'KUL to Bangkok tomorrow'."
        )
    }


# --------------------------------------------------
# API routes
# --------------------------------------------------

@app.get("/")
def home():
    return {"message": "Flight and Weather AI API is running!"}


@app.post("/reset")
def reset():
    """Forget the conversation (the frontend's 'New chat' button)."""
    for key in memory:
        memory[key] = None

    return {"ok": True}


class PlaceRequest(BaseModel):
    name: str


@app.post("/trip/place")
async def trip_place(request: PlaceRequest):
    """Look up a place the user adds to a day: photo, map location and
    whether it really exists near the destination."""
    name = request.name.strip()[:80]
    trip = memory["trip"] or {}
    itinerary = trip.get("itinerary") or {}
    center = itinerary.get("map_center")

    if not name:
        return {"place": None}

    is_food = re.search(
        r"\b(restaurant|restoran|cafe|café|kopitiam|bistro|bar|food|hawker|"
        r"kedai makan|eatery|bakery|coffee)\b",
        name,
        re.IGNORECASE,
    )
    place = {
        "time": "",
        "title": name,
        "description": "",
        "type": "food" if is_food else "sight",
        "place": name,
        "wikipedia": name,
    }

    images = await get_wikipedia_images([name], near=center)

    if images.get(name, {}).get("far"):
        place["wikipedia"] = ""

    found = images.get(place["wikipedia"], {})
    place["image"] = found.get("image")
    place["wiki_url"] = found.get("url") if found.get("image") else None

    await verify_places(
        [place],
        images,
        (center["lat"], center["lng"]) if center else None,
    )
    return {"place": place}


@app.post("/trip/generate")
async def trip_generate():
    try:
        return await generate_trip()
    except Exception as error:
        print(f"Trip generate error: {error!r}", file=sys.stderr)
        traceback.print_exc()

        if memory["trip"]:
            memory["trip"]["stage"] = "collecting"

        return {
            "reply": (
                "I couldn't build the trip just now. "
                "Please try again in a moment."
            ),
            "trip": trip_state(memory["trip"]) if memory["trip"] else None,
        }


@app.post("/chat")
async def chat(request: ChatRequest):
    user_prompt = request.message.strip()

    if not user_prompt:
        return {"reply": "Please enter a flight or weather question."}

    try:
        # Trip builder: "Plan me an itinerary for 6d5n in Mumbai".
        trip = memory["trip"]
        collecting = trip and trip["stage"] == "collecting"

        if is_itinerary_request(user_prompt) and not (
            collecting and not re.search(r"\b(another|new|different)\b", user_prompt, re.IGNORECASE)
        ):
            return await handle_trip(user_prompt, new=True)

        # While collecting, answers go to the checklist unless they're
        # clearly a weather question or a flight search.
        if collecting and not is_weather_question(user_prompt) and not parse_route(user_prompt):
            return await handle_trip(user_prompt)

        # Weather: does not require Gemini.
        weather_question = is_weather_question(user_prompt)
        weather_topic = None

        if weather_question and is_arrival_question(user_prompt):
            return await handle_arrival_weather(user_prompt)

        # Treat "now?", "and at 9pm?" etc. as continuing the last weather question.
        if not weather_question and is_weather_follow_up(user_prompt):
            weather_question = True
            weather_topic = memory["weather_prompt"]

        if weather_question:
            return await handle_weather(user_prompt, weather_topic)

        return await handle_flights(user_prompt)

    except TimeoutError:
        return {"reply": "That took too long. Please try again in a moment."}

    except FlightSearchError as error:
        print(f"Flight search error: {error}", file=sys.stderr)
        return {
            "reply": (
                "Live flight search is unavailable right now "
                f"({error}). Please try again shortly."
            )
        }

    except WeatherServiceError as error:
        print(f"Weather MCP tool error: {error}", file=sys.stderr)
        return {
            "reply": (
                "The weather service couldn't retrieve the data. "
                "Please try again later."
            )
        }

    except Exception as error:
        print(f"Chat error: {error!r}", file=sys.stderr)
        traceback.print_exc()

        return {
            "reply": (
                "Something went wrong on the server. "
                "Please check the backend terminal for details."
            )
        }
