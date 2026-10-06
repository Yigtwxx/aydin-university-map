"""Vercel entrypoint: the platform imports a module-level ASGI ``app``.

Settings come from the project's environment variables; ``create_app`` stays
the factory everywhere else (tests, ``uvicorn --factory``).
"""

from amap_api.main import create_app

app = create_app()
