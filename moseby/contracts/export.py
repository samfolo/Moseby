"""Export the reviewed Python contract: python -m moseby.contracts.export."""

from pathlib import Path

import yaml

from .api import app


def main() -> None:
    destination = Path(__file__).resolve().parents[2] / "openapi.yaml"
    document = "# Generated from moseby/contracts; edit the Python source.\n"
    document += yaml.safe_dump(app.openapi(), sort_keys=False)
    destination.write_text(document, encoding="utf-8")


if __name__ == "__main__":
    main()
