
import asyncio
from treasury import TreasuryManager
from identity_manager import IdentityManager

async def main():
    im = IdentityManager()
    await im.start()
    tm = TreasuryManager(im)
    # This will trigger the _export_state calls
    await tm.get_balance("1xbet", force_refresh=True)
    await tm.get_balance("melbet", force_refresh=True)
    await tm.get_balance("betika", force_refresh=True)
    await tm.get_exchange_balance()
    await im.close()

if __name__ == "__main__":
    asyncio.run(main())
