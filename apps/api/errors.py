"""
Shared exception types + handlers (Clinova Phase 5, Epic 5.1). One
handler per error class in main.py, never a per-route try/except --
every route can just raise and trust the shape of the response.
"""


class NotFoundError(Exception):
    """A resource genuinely doesn't exist -- e.g. `load_run()` returned
    `{}` (it does not raise on a missing run, so every service that
    calls it must check and raise this explicitly)."""
    def __init__(self, detail: str):
        self.detail = detail


class DatabaseUnavailableError(Exception):
    """Postgres isn't reachable. Carries an actionable message, not a
    generic 500 -- matches 02-ux-specification.md §7's failure-state
    requirement ("names what failed and why")."""
    def __init__(self, detail: str = (
        "Cannot reach PostgreSQL. Start it with pg_ctl before using the API "
        "(see .env.example's POSTGRES_URL comment)."
    )):
        self.detail = detail
