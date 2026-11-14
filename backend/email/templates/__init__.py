"""Plain-text email templates. First line is 'Subject: ...'; every template ends with a 'Ref: <incident>/<kind>' line."""
from pathlib import Path

HERE = Path(__file__).parent


def render(name: str, **fields) -> tuple[str, str]:
    """Fill a template and return (subject, body)."""
    first, _, body = (HERE / f"{name}.txt").read_text(encoding="utf-8").format(**fields).partition("\n")
    return first.removeprefix("Subject: ").strip(), body.strip() + "\n"
