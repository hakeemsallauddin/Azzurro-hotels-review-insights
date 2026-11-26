import os

import uvicorn

if __name__ == "__main__":
    # HOST/PORT come from the hosting platform when deployed (e.g. Render
    # sets PORT and expects the app on 0.0.0.0); defaults suit local use.
    uvicorn.run(
        "backend.api.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
    )
