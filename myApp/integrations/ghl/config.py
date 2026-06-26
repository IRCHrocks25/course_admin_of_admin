"""GoHighLevel (GHL) integration configuration.

All values are read from the environment so credentials never live in source.
V2 ONLY — OAuth 2.0 Authorization Code flow against LeadConnector services.
Do not introduce V1 / legacy API-key paths here.
"""
import os


# ─── Endpoints (V2 / LeadConnector) ───
# Where the user is sent to choose a sub-account and authorize the app.
AUTHORIZE_URL = "https://marketplace.leadconnectorhq.com/v2/oauth/chooselocation"
# Token mint + refresh, and agency->location token exchange.
TOKEN_URL = "https://services.leadconnectorhq.com/oauth/token"
LOCATION_TOKEN_URL = "https://services.leadconnectorhq.com/oauth/locationToken"
# Base for all sub-account API calls (Phase 1+).
API_BASE_URL = "https://services.leadconnectorhq.com"
# GHL requires an explicit API version header on every call.
API_VERSION = "2021-07-28"

# We target a Sub-account (Location) install, not an agency (Company) install.
USER_TYPE = "Location"

# Default scopes if GHL_SCOPES is unset. We request the full Sub-Account-
# compatible set up front so later phases (course migration, CRM sync, webhooks)
# need NO partner re-consent. Keep this in sync with
# business-center/select-subaccount-scopes.js. Sensitive-but-unused scopes
# (e.g. users.write) are deliberately excluded per the "no unused sensitive
# scopes" policy — add one only when code actually uses it.
_DEFAULT_SCOPES = (
    "contacts.readonly contacts.write "
    "opportunities.readonly opportunities.write "
    "locations.readonly "
    "locations/customValues.readonly locations/customValues.write "
    "locations/tags.readonly locations/tags.write "
    "locations/tasks.readonly "
    "calendars.readonly calendars.write "
    "calendars/events.readonly calendars/events.write "
    "conversations.readonly conversations.write "
    "conversations/message.readonly conversations/message.write "
    "users.readonly businesses.readonly forms.readonly "
    "surveys.readonly workflows.readonly"
)


def _env(name, default=""):
    return (os.getenv(name, default) or "").strip()


def client_id():
    return _env("GHL_CLIENT_ID")


def client_secret():
    return _env("GHL_CLIENT_SECRET")


def redirect_uri():
    """The ONE central redirect URI registered in the GHL marketplace app.

    Must match what is registered in GHL EXACTLY (scheme, host, path, no
    trailing slash drift). Never construct per-tenant redirect URIs.
    """
    return _env("GHL_REDIRECT_URI")


def webhook_public_key():
    """PEM public key used to verify inbound webhook signatures (Phase 2)."""
    return _env("GHL_WEBHOOK_PUBLIC_KEY")


def scopes():
    return _env("GHL_SCOPES") or _DEFAULT_SCOPES


def is_configured():
    """True when the minimum credentials for the OAuth flow are present."""
    return bool(client_id() and client_secret() and redirect_uri())
