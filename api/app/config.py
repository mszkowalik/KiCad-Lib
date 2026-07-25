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

    # Jaravis: key read from env or .env; model per user preference
    # (Sonnet by default, set JARAVIS_MODEL=claude-opus-4-8 for harder tasks).
    anthropic_api_key: str = ""
    jaravis_model: str = "claude-sonnet-5"

    # Fetch missing datasheet PDFs in the background on startup.
    datasheet_autofetch: bool = True

    # Nightly re-check of EVERY datasheet source URL: conditional GETs
    # (ETag / Last-Modified) ask the supplier whether the document changed and
    # only download when it did — a new PDF becomes a new DatasheetVersion and
    # bumps the component version. Hour is server local time (containers run
    # UTC unless TZ is set).
    datasheet_recheck_nightly: bool = True
    datasheet_recheck_hour: int = 3

    # Token expected in "Authorization: Token <...>" on /kicad/v1/* endpoints.
    httplib_token: str = "dev-token"

    # Bearer token required on /api/agent/* (the tool surface the external MCP
    # server / Claude Code drives). Empty = open, which is fine on localhost;
    # set a value before the platform is reachable remotely so the agent
    # endpoints (which can create draft proposals) are not left public.
    mcp_token: str = ""

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
