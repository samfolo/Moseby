from importlib.resources import files


def concierge_prompt() -> str:
    """Read the version 1 concierge instructions bundled with the application."""
    return files(__package__).joinpath("concierge.v1.md").read_text(encoding="utf-8")
