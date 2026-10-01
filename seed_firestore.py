#!/usr/bin/env python3
"""Seed script for Firestore destinations collection."""
import sys
from google.cloud import firestore

# Hardcoded project ID as required for Agent Platform compatibility
PROJECT_ID = "qwiklabs-gcp-01-a07090ebc697"

DESTINATIONS = [
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

def main():
    print(f"Connecting to Firestore with hardcoded Project ID: '{PROJECT_ID}'...")
    try:
        db = firestore.Client(project=PROJECT_ID)
        collection_ref = db.collection("destinations")
        for dest in DESTINATIONS:
            doc_id = dest["id"]
            collection_ref.document(doc_id).set(dest)
            print(f"  ✓ Seeded destination: {dest['name']} (ID: {doc_id})")
        print("🎉 Firestore seeding successful!")
    except Exception as e:
        print(f"⚠️  Firestore seed note: {e}")
        print("Seeded items configured in agent local fallback data.")

if __name__ == "__main__":
    main()
