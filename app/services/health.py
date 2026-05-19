from app.domain.health import HealthResponse


def get_health() -> HealthResponse:
    return HealthResponse()
