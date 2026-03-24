from pathlib import Path

from fastapi import FastAPI
from dotenv import load_dotenv

from app.api.routes import router
from app.api.schemas import HealthResponse
from app.services.provider_wiring import ProviderRegistry, build_provider_registry_from_env

BACKEND_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=BACKEND_ENV_PATH)


def create_app(provider_registry: ProviderRegistry | None = None) -> FastAPI:
    app = FastAPI(title="Quick Netters API", version="0.1.0")
    app.state.provider_registry = provider_registry or build_provider_registry_from_env()
    app.include_router(router)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service="quick-netters-backend", version=app.version)

    return app


app = create_app()
