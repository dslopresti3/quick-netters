from fastapi import FastAPI

from app.api.routes import router
from app.api.schemas import HealthResponse

app = FastAPI(title="Quick Netters API", version="0.1.0")
app.include_router(router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="quick-netters-backend", version=app.version)
