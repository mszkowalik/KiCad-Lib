"""Centralized configuration. Everything overridable via environment variables."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ../.env covers dev mode (uvicorn run from api reads .env)
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+psycopg://kicadlib:kicadlib@127.0.0.1:5434/kicadlib"

    # The existing library repo (mounted read-only at /repo in Docker).
    # The import station reads Sources/, Symbols/base_library.kicad_symdir/,
    # Footprints/7Sigma.pretty/ and 3DModels/ from here.
    repo_dir: Path = Path("/repo")

    # Writable data root: file mirror + render cache live here.
    data_dir: Path = Path("./data")

    # "http"  -> POST to the render container (RENDER_URL)
    # "local" -> invoke kicad-cli directly (handy for dev on the Mac)
    render_mode: str = "http"
    render_url: str = "http://localhost:8100"
    kicad_cli: str = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"

    # kicad-cli color themes for SVG previews. Theme names as shown in the
    # KiCad editors; the JSON files must exist where the renderer runs
    # (mac: ~/Library/Preferences/kicad/10.0/colors/, container: baked in
    # from render/themes/). Empty string = KiCad default theme.
    symbol_theme: str = "Skyline-7S"
    footprint_theme: str = ""  # board previews already use KiCad Default (dark)

    # Public URL of this API as seen by KiCad users — used to build links to
    # locally stored datasheets injected into generated symbols.
    public_base_url: str = "http://localhost:8020"

    # Browser origins allowed to call this API, comma-separated. The deployed
    # web image serves the SPA from the same origin as the API (nginx proxies
    # both), so CORS only matters for a dev server aimed at a remote API.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Jaravis: key read from env or .env; model per user preference
    # (Sonnet by default, set JARAVIS_MODEL=claude-opus-4-8 for harder tasks).
    anthropic_api_key: str = ""
    jaravis_model: str = "claude-sonnet-5"

    # Fetch missing datasheet PDFs in the background on startup.
    datasheet_autofetch: bool = True

    # Approving a symbol/footprint version files a DRAFT component version per
    # affected part, so components never stay pinned to superseded geometry
    # (services/repoint.py). Still draft-gated — this creates proposals, it
    # never publishes. Turn off to approve geometry without the follow-up.
    auto_repoint_components: bool = True

    # Nightly re-check of EVERY datasheet source URL: conditional GETs
    # (ETag / Last-Modified) ask the supplier whether the document changed and
    # only download when it did — a new PDF becomes a new DatasheetVersion and
    # bumps the component version. Hour is server local time (containers run
    # UTC unless TZ is set).
    datasheet_recheck_nightly: bool = True
    datasheet_recheck_hour: int = 3
    # Extract per-page text for documents stored before the page index existed
    # (services/datasheet_pages.py). Self-limiting — it only claims versions
    # with pages_indexed_at IS NULL — but the FIRST run is ~40 minutes of
    # background CPU on ~9400 pages, so a deployment that would rather run it
    # by hand (POST /api/datasheets/index) can turn the sweep off.
    datasheet_page_index_on_startup: bool = True

    # Token expected in "Authorization: Token <...>" on /kicad/v1/* endpoints.
    httplib_token: str = "dev-token"

    # Bearer token required on /api/agent/* (the tool surface the external MCP
    # server / Claude Code drives). Empty = open, which is fine on localhost;
    # set a value before the platform is reachable remotely so the agent
    # endpoints (which can create draft proposals) are not left public.
    #
    # LEGACY once auth_enabled is on: both this and httplib_token above are
    # SHARED secrets that predate per-user tokens. They keep working so an
    # already-installed .kicad_httplib and the MCP server survive the cutover,
    # and `auth_legacy_tokens` turns them off once every client carries a
    # personal token.
    mcp_token: str = ""

    # ------------------------------------------------------------------- auth
    # Default-deny gate in front of the whole API (main.py::auth_middleware).
    # Set to false ONLY for a single-user localhost dev box — the platform is
    # reachable from the internet in production and the API can approve
    # proposals, edit money records and drive the agent.
    auth_enabled: bool = True

    # Keep accepting the pre-auth SHARED tokens (httplib_token, mcp_token).
    # Turn off once every KiCad install and MCP client carries a personal one.
    auth_legacy_tokens: bool = True

    # First admin, created at startup only when the users table is EMPTY. It is
    # the bootstrap for a fresh deployment and nothing else: once a user
    # exists, these are ignored, so leaving them in the environment cannot
    # resurrect or re-password an account.
    admin_username: str = "admin"
    admin_password: str = ""

    # Browser session cookie. `session_cookie_secure` must be true wherever the
    # platform is served over HTTPS; it is false by default because dev runs on
    # plain http://localhost and a Secure cookie is silently dropped there.
    session_cookie_name: str = "kicadlib_session"
    session_cookie_secure: bool = False
    session_lifetime_days: int = 30
    # Sessions idle longer than this are refused even inside their lifetime.
    session_idle_days: int = 7

    # Sign-in lockout: after this many consecutive failures a username is
    # locked for `login_lockout_minutes`. A successful sign-in clears it.
    login_max_failures: int = 8
    login_lockout_minutes: int = 15

    # ------------------------------------------------------------- projects
    # MinIO object storage: project snapshot archives, cached renders
    # (board layer SVGs, schematic SVGs, GLB/STEP, gerber bundles) and
    # production-run attachments. Dev mode: docker compose up -d db minio.
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "kicadlib"
    minio_secret_key: str = "kicadlib-secret"
    minio_bucket: str = "kicadlib"
    minio_secure: bool = False

    # Encrypts stored git tokens at rest (Fernet key derived via SHA-256).
    secret_key: str = "dev-secret-change-me"

    # Display currency for cost totals when a project has no override.
    default_currency: str = "USD"

    # Exchange-rate auto-refresh (frankfurter.app — ECB daily rates, no key).
    fx_autofetch: bool = True

    # Refresh LCSC price ladders older than this many days on startup.
    price_ladder_max_age_days: int = 30
    price_ladder_autofetch: bool = True

    # Touch the stored jlcpcb.com browser session this often (minutes; 0 = off).
    # The session's short-lived pieces — `secretkey` (25 min) and `XSRF-TOKEN`
    # (Max-Age 1800) — are already renewed by the client itself, so this exists
    # for the session handle, whose real lifetime JLC does not publish. If they
    # expire on inactivity a periodic touch keeps it alive indefinitely; if the cap
    # is absolute it cannot, but `died_at - updated_at` then measures it exactly.
    jlc_session_keepalive_min: float = 20.0

    # JLCPCB OpenAPI (https://api.jlcpcb.com — apply for access, create an
    # app). Enables the private parts library (consigned stock) integration.
    jlc_app_id: str = ""
    jlc_access_key: str = ""
    jlc_secret_key: str = ""
    jlc_endpoint: str = "https://open.jlcpcb.com"

    # How the KiCad HTTP library references local geometry — must match the
    # client's library-table nicknames. Defaults assume the PCM install:
    # symbolIdStr points at the component's BASE drawing in the deduplicated
    # base library (adding components then needs no library update at all);
    # footprint refs are remapped to the PCM footprint nickname.
    httplib_symbol_lib: str = "PCM_7Sigma_Base"
    footprint_lib_nickname: str = "PCM_7Sigma"

    # How long KiCad may reuse its OWN in-process copy of the catalog, written
    # into the .kicad_httplib as source.timeout_categories_seconds /
    # source.timeout_parts_seconds. KiCad's defaults are 600 and 30, and the
    # category one is the expensive path: `EnumerateSymbolLib` re-fetches the
    # part list of EVERY category once it expires, so with the default the
    # first "Add Symbol" click in any 10-minute window pays the whole catalog.
    # Raised because approval is the only thing that changes the catalog, and
    # a client that must see a new part sooner can reopen the project.
    httplib_timeout_categories_s: int = 3600
    httplib_timeout_parts_s: int = 600

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def mirror_dir(self) -> Path:
        return self.data_dir / "mirror"

    @property
    def render_cache_dir(self) -> Path:
        return self.data_dir / "render-cache"

    @property
    def git_dir(self) -> Path:
        """Bare mirror clones of project repos: git/<project_id>.git"""
        return self.data_dir / "git"

    @property
    def checkouts_dir(self) -> Path:
        """Materialized snapshot worktrees: checkouts/<project_id>/<sha>/
        (shared volume — the render container reads these at /data/...)."""
        return self.data_dir / "checkouts"

    def ensure_dirs(self) -> None:
        self.mirror_dir.mkdir(parents=True, exist_ok=True)
        self.render_cache_dir.mkdir(parents=True, exist_ok=True)
        self.git_dir.mkdir(parents=True, exist_ok=True)
        self.checkouts_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()

# The anthropic SDK resolves credentials from the environment — propagate a
# key found in .env so dev mode works without exporting it manually.
if settings.anthropic_api_key:
    import os

    os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)
