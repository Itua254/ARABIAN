import asyncio
import json
import os
from odds_fetcher import fetch_all_odds
from identity_manager import IdentityManager

async def main():
    print("Initializing Identity Manager...")
    identity_manager = IdentityManager()
    await identity_manager.start()
    
    print("Scraping odds from all active bookmakers...")
    events = await fetch_all_odds(identity_manager)
    
    print(f"\nScraping complete. Total market entries: {len(events)}")
    
    if events:
        print("\nSample Event Data:")
        print(json.dumps(events[0], indent=2))
    
    # Group by match and bookmaker
    matches = {}
    for ev in events:
        # Try different possible keys for match name
        home = ev.get('home')
        away = ev.get('away')
        if home and away:
            match_name = f"{home} vs {away}"
        else:
            match_name = ev.get('match') or ev.get('event_name') or ev.get('teams') or 'Unknown Match'
        
        if isinstance(match_name, list):
            match_name = " vs ".join(match_name)
        if match_name not in matches:
            matches[match_name] = {}
        
        bm = ev.get('bookmaker', 'unknown')
        if bm not in matches[match_name]:
            matches[match_name][bm] = 0
        matches[match_name][bm] += 1
    
    print("\nAvailable Matches (Top 10):")
    print("-" * 50)
    for i, (match, bookmakers) in enumerate(list(matches.items())[:10]):
        bm_str = ", ".join([f"{bm} ({count})" for bm, count in bookmakers.items()])
        print(f"{i+1}. {match}")
        print(f"   Bookmakers: {bm_str}")
    
    await identity_manager.close()

if __name__ == "__main__":
    asyncio.run(main())
