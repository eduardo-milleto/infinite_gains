from __future__ import annotations

import uvicorn

from src.config.settings import get_settings
from src.core.logging import configure_logging


def main() -> None:
    configure_logging()
    settings = get_settings()
    uvicorn.run(
        "src.services.web.app:create_app",
        factory=True,
        host=settings.web_api_host,
        port=settings.web_api_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()

