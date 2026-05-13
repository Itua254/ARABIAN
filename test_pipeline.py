import asyncio
from odds_fetcher import fetch_all_odds
from arb_detector import process_events
from edge_classifier import classify
from notifier import send_telegram_alert

async def main():
    print("1. Fetching odds...")
    events = await fetch_all_odds()
    print(f"Fetched {len(events)} events.")
    
    if events:
        print("2. Detecting arbs...")
        arbs = process_events(events)
        print(f"Detected {len(arbs)} raw arbs.")

        for arb in arbs:
            print("\nChecking arb:")
            print(arb)
            edge = classify(arb)
            print(f"Edge class: {edge}")
    else:
        print("No live events returned (check Odds API key). Proceeding to test Telegram anyway...")
        
    print("\n3. Testing Telegram Notification with synthetic arb...")
    synthetic_arb = {
        "event_id": "test_pipeline_001",
        "sport": "soccer",
        "match": "Pipeline Test vs Validated System",
        "margin_pct": 3.45,
        "profit": 34.50,
        "bankroll": 1000,
        "age_sec": 1.2,
        "legs": [
            {"outcome": "Pipeline Test", "bookmaker": "betway", "odds": 2.10, "stake": 490.5},
            {"outcome": "Validated System", "bookmaker": "pinnacle", "odds": 2.05, "stake": 509.5}
        ]
    }
    
    success = await send_telegram_alert(synthetic_arb)
    if success:
        print("✅ Telegram alert sent successfully! Check your phone.")
    else:
        print("❌ Telegram alert failed.")

if __name__ == "__main__":
    asyncio.run(main())
