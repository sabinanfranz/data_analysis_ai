from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .database import get_initial_dashboard_data
from .org_tables_api import router as org_tables_router

from fastapi.responses import FileResponse

app = FastAPI(title="Org Tables Dashboard API")

frontend_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins + ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(org_tables_router)

@app.get("/", include_in_schema=False)
def index():
    return FileResponse("org_tables_v2.html")

@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/initial-data")
async def initial_data() -> dict:
    try:
        return get_initial_dashboard_data()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:  # pragma: no cover - FastAPI will log details
        raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
