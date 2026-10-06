"""Write the OpenAPI schema to apps/api/openapi.json (input for TS type generation)."""

import json
import sys
from pathlib import Path

from amap_api.main import create_app
from amap_api.settings import Settings

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "openapi.json"


def main(out: Path = DEFAULT_OUT) -> None:
    isolated = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    schema = create_app(settings=isolated).openapi()
    out.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(f"wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
