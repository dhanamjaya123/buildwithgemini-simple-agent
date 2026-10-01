# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging
import os
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.memory import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.genai import types
from google.cloud import firestore, storage
from a2ui.schema.manager import A2uiSchemaManager
from a2ui.basic_catalog.provider import BasicCatalog
from .a2ui_utils import a2ui_callback

# Hardcoded Project ID string as required for Agent Platform deployment
FIRESTORE_PROJECT = "qwiklabs-gcp-01-a07090ebc697"
STATIC_ASSETS_BUCKET = "qwiklabs-gcp-01-a07090ebc697-static-assets-bucket"

# Load Agent Engine resource name from deployment_metadata.json if available
DEPLOYMENT_METADATA_PATH = Path(__file__).parent.parent / "deployment_metadata.json"
REMOTE_AGENT_RUNTIME_ID = "projects/866472104900/locations/us-east1/reasoningEngines/7452294099995983872"

if DEPLOYMENT_METADATA_PATH.exists():
    try:
        with open(DEPLOYMENT_METADATA_PATH, "r") as f:
            meta = json.load(f)
            REMOTE_AGENT_RUNTIME_ID = meta.get("remote_agent_runtime_id", REMOTE_AGENT_RUNTIME_ID)
    except Exception as e:
        logging.warning(f"Could not load deployment_metadata.json: {e}")

code_executor = AgentEngineSandboxCodeExecutor(
    agent_engine_resource_name=REMOTE_AGENT_RUNTIME_ID
)



# Fallback local in-memory store if Firestore database instance is not provisioned
_LOCAL_DESTINATIONS = [
    {
        "id": "kyoto",
        "name": "Kyoto, Japan",
        "category": "Culture & Nature",
        "country": "Japan",
        "description": "Famous for classical Buddhist temples, gardens, imperial palaces, and traditional wooden houses.",
        "avg_daily_budget_usd": 180,
        "best_season": "Spring (Cherry Blossom) & Autumn",
        "rating": 4.9,
    },
    {
        "id": "santorini",
        "name": "Santorini, Greece",
        "category": "Beach & Romance",
        "country": "Greece",
        "description": "Iconic Aegean island known for whitewashed cubiform houses, blue-domed churches, and stunning sunsets.",
        "avg_daily_budget_usd": 250,
        "best_season": "May to October",
        "rating": 4.8,
    },
    {
        "id": "banff",
        "name": "Banff National Park, Canada",
        "category": "Adventure & Mountains",
        "country": "Canada",
        "description": "Breathtaking turquoise glacial lakes, majestic Canadian Rockies peaks, and outdoor adventure.",
        "avg_daily_budget_usd": 200,
        "best_season": "June to September & December to March",
        "rating": 4.9,
    },
    {
        "id": "florence",
        "name": "Florence, Italy",
        "category": "Art & Food",
        "country": "Italy",
        "description": "Cradle of the Renaissance, packed with world-class art galleries, historic architecture, and Tuscan cuisine.",
        "avg_daily_budget_usd": 190,
        "best_season": "April to June & September to October",
        "rating": 4.7,
    },
]


def _get_firestore_client():
    """Returns a Firestore client initialized with the hardcoded project ID."""
    try:
        return firestore.Client(project=FIRESTORE_PROJECT)
    except Exception as e:
        logging.warning(f"Could not initialize Firestore client: {e}")
        return None


def get_destinations(category: str = None) -> list[dict]:
    """Reads destinations from the Firestore backend collection.

    Args:
        category: Optional category filter (e.g. 'Culture & Nature', 'Beach & Romance').

    Returns:
        List of destination dictionaries.
    """
    client = _get_firestore_client()
    if client:
        try:
            col = client.collection("destinations")
            query = col if not category else col.where("category", "==", category)
            docs = query.stream()
            results = [doc.to_dict() for doc in docs]
            if results:
                return results
        except Exception as e:
            logging.warning(f"Firestore query failed: {e}. Falling back to seeded data.")

    # Fallback in-memory filter
    if category:
        return [d for d in _LOCAL_DESTINATIONS if category.lower() in d["category"].lower()]
    return _LOCAL_DESTINATIONS


def add_destination(
    name: str,
    country: str,
    category: str,
    description: str,
    avg_daily_budget_usd: int,
    best_season: str = "All Year",
) -> dict:
    """Adds a new destination to the Firestore backend collection.

    Args:
        name: Name of the destination (e.g. 'Paris, France').
        country: Country name.
        category: Travel category (e.g. 'Art & Culture').
        description: Short description of attraction highlights.
        avg_daily_budget_usd: Estimated average daily cost in USD.
        best_season: Recommended time of year to visit.

    Returns:
        Dictionary confirming the added destination details.
    """
    doc_id = name.lower().replace(" ", "_").replace(",", "")
    dest_data = {
        "id": doc_id,
        "name": name,
        "country": country,
        "category": category,
        "description": description,
        "avg_daily_budget_usd": avg_daily_budget_usd,
        "best_season": best_season,
        "rating": 4.5,
    }

    client = _get_firestore_client()
    if client:
        try:
            client.collection("destinations").document(doc_id).set(dest_data)
            return {"status": "success", "source": "firestore", "destination": dest_data}
        except Exception as e:
            logging.warning(f"Firestore write failed: {e}. Storing locally.")

    _LOCAL_DESTINATIONS.append(dest_data)
    return {"status": "success", "source": "local_fallback", "destination": dest_data}


def search_destinations(query: str) -> list[dict]:
    """Searches for travel destinations by keyword in name, country, or category.

    Args:
        query: Keyword to search for.

    Returns:
        List of matching destination dictionaries.
    """
    all_dests = get_destinations()
    q = query.lower()
    matches = []
    for d in all_dests:
        if (
            q in d.get("name", "").lower()
            or q in d.get("country", "").lower()
            or q in d.get("category", "").lower()
            or q in d.get("description", "").lower()
        ):
            matches.append(d)
    return matches


def calculate_trip_budget(
    destination_name: str,
    duration_days: int,
    travelers_count: int = 1,
    travel_tier: str = "moderate",
) -> dict:
    """Calculates estimated trip budget and itemized cost breakdown for a destination.

    Args:
        destination_name: Name or keyword of the destination (e.g. 'Kyoto', 'Santorini').
        duration_days: Number of days for the trip.
        travelers_count: Number of travelers (default: 1).
        travel_tier: Travel style ('budget', 'moderate', or 'luxury').

    Returns:
        Dictionary with itemized costs and total estimated budget in USD.
    """
    matches = search_destinations(destination_name)
    base_daily = matches[0].get("avg_daily_budget_usd", 200) if matches else 200

    tier_multipliers = {"budget": 0.7, "moderate": 1.0, "luxury": 1.8}
    multiplier = tier_multipliers.get(travel_tier.lower(), 1.0)

    daily_per_person = int(base_daily * multiplier)
    total_cost = daily_per_person * duration_days * travelers_count

    return {
        "destination": destination_name,
        "duration_days": duration_days,
        "travelers_count": travelers_count,
        "travel_tier": travel_tier,
        "daily_per_person_usd": daily_per_person,
        "total_estimated_budget_usd": total_cost,
        "breakdown_usd": {
            "accommodation": int(total_cost * 0.45),
            "food_and_dining": int(total_cost * 0.30),
            "activities_and_tours": int(total_cost * 0.15),
            "transport_and_misc": int(total_cost * 0.10),
        },
    }


def fetch_live_weather(city_name: str) -> dict:
    """Fetches real-time weather and forecast data for any city worldwide using the free Open-Meteo public API.

    Args:
        city_name: Name of the city (e.g. 'Kyoto', 'Paris', 'San Francisco').

    Returns:
        Dictionary with live temperature, wind speed, and weather details.
    """
    try:
        # Check for optional API key in environment if custom provider is used (otherwise Open-Meteo is free)
        api_key = os.getenv("OPEN_METEO_API_KEY", "")

        # 1. Geocode city name to lat/lon
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city_name)}&count=1"
        geo_req = urllib.request.Request(geo_url, headers={"User-Agent": "GlobeTrotterAI/1.0"})
        with urllib.request.urlopen(geo_req, timeout=5) as response:
            geo_data = json.loads(response.read().decode())

        if not geo_data.get("results"):
            return {"error": f"City '{city_name}' not found."}

        loc = geo_data["results"][0]
        lat, lon = loc["latitude"], loc["longitude"]
        city, country = loc.get("name", city_name), loc.get("country", "")

        # 2. Fetch live weather forecast
        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        if api_key:
            weather_url += f"&apikey={api_key}"

        weather_req = urllib.request.Request(weather_url, headers={"User-Agent": "GlobeTrotterAI/1.0"})
        with urllib.request.urlopen(weather_req, timeout=5) as response:
            weather_data = json.loads(response.read().decode())

        cw = weather_data.get("current_weather", {})
        temp_c = cw.get("temperature")
        temp_f = round(temp_c * 9 / 5 + 32, 1) if temp_c is not None else None

        return {
            "city": city,
            "country": country,
            "temperature_celsius": temp_c,
            "temperature_fahrenheit": temp_f,
            "windspeed_kmh": cw.get("windspeed"),
            "is_daytime": bool(cw.get("is_day", 1)),
            "api_provider": "Open-Meteo Public API",
        }
    except Exception as e:
        return {"error": f"Failed to fetch live weather for {city_name}: {str(e)}"}


def geocode_address(address: str) -> dict:
    """Converts an address or location name into geographic coordinates (latitude, longitude) using Google Maps Geocoding API.

    Args:
        address: Street address or location name (e.g. 'Kiyomizu-dera, Kyoto' or '1600 Amphitheatre Pkwy, Mountain View, CA').

    Returns:
        Dictionary with formatted address, location coordinates, and place_id.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if not api_key or api_key == "PASTE_KEY_HERE":
        return {
            "status": "error",
            "message": "GOOGLE_MAPS_API_KEY not configured. Set a valid key in .env",
        }

    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(address)}&key={api_key}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GlobeTrotterAI/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())

        if data.get("status") == "OK" and data.get("results"):
            first = data["results"][0]
            loc = first["geometry"]["location"]
            return {
                "formatted_address": first.get("formatted_address"),
                "location": {"latitude": loc.get("lat"), "longitude": loc.get("lng")},
                "place_id": first.get("place_id"),
            }
        return {
            "status": data.get("status"),
            "message": data.get("error_message", "No results found"),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def search_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "tourist_attraction",
    radius_meters: float = 1000.0,
) -> dict:
    """Finds nearby points of interest of a given type around coordinates using Google Places API (New).

    Args:
        latitude: Center latitude coordinate.
        longitude: Center longitude coordinate.
        place_type: Type of place to search for (e.g. 'tourist_attraction', 'restaurant', 'museum', 'lodging').
        radius_meters: Search radius around center coordinates in meters (default: 1000).

    Returns:
        Dictionary containing list of nearby places with name, formatted address, and location coordinates.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if not api_key or api_key == "PASTE_KEY_HERE":
        return {
            "status": "error",
            "message": "GOOGLE_MAPS_API_KEY not configured. Set a valid key in .env",
        }

    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location,places.types,places.rating",
        "User-Agent": "GlobeTrotterAI/1.0",
    }

    payload = {
        "includedTypes": [place_type],
        "maxResultCount": 5,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": latitude, "longitude": longitude},
                "radius": radius_meters,
            }
        },
    }

    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), headers=headers
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())

        results = []
        for place in data.get("places", []):
            results.append({
                "name": place.get("displayName", {}).get("text"),
                "address": place.get("formattedAddress"),
                "location": place.get("location"),
                "rating": place.get("rating"),
                "types": place.get("types"),
            })
        return {"count": len(results), "places": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def generate_destination_image(
    prompt: str,
    tool_context: ToolContext,
) -> dict:
    """Generates an image for a travel destination using gemini-3.1-flash-lite-image in the global region.

    Saves the image as an artifact via tool_context.save_artifact and uploads it to public Cloud Storage, returning its public https URL.

    Args:
        prompt: Visual description of the travel destination or attraction to generate (e.g. 'Fushimi Inari shrine torii gates in Kyoto').
        tool_context: ADK tool execution context for artifact management.

    Returns:
        Dictionary with public GCS URL and artifact details.
    """
    try:
        # 1. Generate image using gemini-3.1-flash-lite-image in the global region
        genai_client = genai.Client(vertexai=True, location="global")
        full_prompt = f"A vivid, high quality travel photography image of {prompt}. Cinematic lighting, photorealistic."
        res = genai_client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=full_prompt,
        )

        image_bytes = None
        mime_type = "image/jpeg"
        if res.candidates and res.candidates[0].content.parts:
            for part in res.candidates[0].content.parts:
                if part.inline_data:
                    image_bytes = part.inline_data.data
                    if part.inline_data.mime_type:
                        mime_type = part.inline_data.mime_type
                    break

        if not image_bytes:
            return {
                "status": "error",
                "message": "Failed to extract image bytes from generated response.",
            }

        # 2. Save image with tool_context.save_artifact for Playground Artifacts panel
        ext = mime_type.split('/')[-1] if '/' in mime_type else 'jpg'
        filename = f"destination_{uuid.uuid4().hex[:8]}.{ext}"
        artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        artifact_version = tool_context.save_artifact(
            filename=filename,
            artifact=artifact_part,
        )

        # 3. Upload same image bytes to public GCS bucket
        gcs_client = storage.Client(project=FIRESTORE_PROJECT)
        bucket = gcs_client.bucket(STATIC_ASSETS_BUCKET)
        blob = bucket.blob(f"generated_images/{filename}")
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{STATIC_ASSETS_BUCKET}/generated_images/{filename}"

        return {
            "status": "success",
            "filename": filename,
            "artifact_version": artifact_version,
            "public_url": public_url,
            "prompt": prompt,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def generate_memories_callback(callback_context: CallbackContext):
    """Callback executed after turn to extract and store durable facts into Memory Bank."""
    await callback_context.add_session_to_memory()
    return None


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

a2ui_instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are GlobeTrotter AI, a helpful travel concierge assistant. You help users discover travel destinations, "
        "search the catalog, add places, calculate trip budgets, fetch live weather, geocode addresses, find nearby places of interest, "
        "generate destination imagery, remember user travel preferences and facts across sessions, "
        "and execute Python code for data analysis or calculations in a secure sandbox."
    ),
    workflow_description="Analyze the request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        "{\"Image\": {\"url\": {\"literalString\": \"https://...\"}}}. Never point an "
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    code_executor=code_executor,
    instruction=a2ui_instruction,
    tools=[
        PreloadMemoryTool(),
        get_destinations,
        add_destination,
        search_destinations,
        calculate_trip_budget,
        fetch_live_weather,
        geocode_address,
        search_nearby_places,
        generate_destination_image,
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
)


def memory_service_builder():
    """Memory service builder for deployed Agent Runtime instances."""
    return VertexAiMemoryBankService(
        project=FIRESTORE_PROJECT,
        location="us-central1",
        agent_engine_id="7460449727495012352",
    )


memory_service = memory_service_builder()

app = App(
    root_agent=root_agent,
    name="app",
)
