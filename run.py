"""Start the MVP dashboard: python run.py"""

import os
import asyncio
import sys
import uvicorn

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run(
        "app.main:app",
        host=os.getenv("SOMAS_HOST", "127.0.0.1"),
        port=int(os.getenv("SOMAS_PORT", "8000")),
        loop="asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto",
        proxy_headers=False,
        access_log=False,
        reload=False,
    )
