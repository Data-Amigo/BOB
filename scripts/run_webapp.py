"""Start the BOB Mini App web server."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import uvicorn
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

if __name__ == "__main__":
    print("BOB Mini App running at http://localhost:8080")
    print("For Telegram Mini App, expose it with: ngrok http 8080")
    uvicorn.run(
        "ganji_mtaani_agent.webapp.api:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
    )
