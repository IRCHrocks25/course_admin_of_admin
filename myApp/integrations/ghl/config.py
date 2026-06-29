"""GoHighLevel (GHL) integration configuration.

All values are read from the environment so credentials never live in source.
V2 ONLY — OAuth 2.0 Authorization Code flow against LeadConnector services.
Do not introduce V1 / legacy API-key paths here.
"""
import os
from urllib.parse import parse_qs, urlsplit


# ─── Endpoints (V2 / LeadConnector) ───
# Where the user is sent to choose a sub-account and authorize the app.
AUTHORIZE_URL = "https://marketplace.leadconnectorhq.com/v2/oauth/chooselocation"
DEFAULT_INSTALL_URL = (
    "https://marketplace.leadconnectorhq.com/v2/oauth/chooselocation?"
    "response_type=code&redirect_uri=https%3A%2F%2Fcourseforge.katek-ai.com%2Fleadconnector%2Fcallback"
    "&client_id=6a3c63e708b022331c8b15d5-mqspg6bj"
    "&scope=adPublishing.readonly+adPublishing.write+affiliate-manager.readonly+agent-studio.readonly+"
    "agent-studio.write+associations.write+associations.readonly+associations%2Frelation.readonly+"
    "associations%2Frelation.write+blogs%2Fpost.write+blogs%2Fpost-update.write+blogs%2Fcheck-slug.readonly+"
    "blogs%2Fcategory.readonly+blogs%2Fauthor.readonly+blogs%2Fposts.readonly+blogs%2Flist.readonly+"
    "brand-boards%2Fdesign-kit.readonly+brand-boards%2Fdesign-kit.write+brand-boards%2Fvoices.readonly+"
    "brand-boards%2Fvoices.write+businesses.readonly+businesses.write+calendars.readonly+calendars.write+"
    "calendars%2Fevents.readonly+calendars%2Fevents.write+calendars%2Fgroups.readonly+calendars%2Fgroups.write+"
    "calendars%2Fresources.readonly+calendars%2Fresources.write+campaigns.readonly+chat-widget.readonly+"
    "chat-widget.write+contacts.readonly+contacts.write+conversation-ai.readonly+conversation-ai.write+"
    "conversations.readonly+conversations.write+conversations%2Fmessage.readonly+conversations%2Fmessage.write+"
    "conversations%2Freports.readonly+conversations%2Flivechat.write+courses.write+courses.readonly+"
    "locations%2FcustomFields.readonly+locations%2FcustomFields.write+emails%2Fbuilder.write+"
    "emails%2Fbuilder.readonly+emails%2Fschedule.readonly+emails%2Fschedule.write+emails%2Ftemplates.readonly+"
    "emails%2Ftemplates.write+emails%2Fcampaigns.readonly+emails%2Fcampaigns.write+emails%2Fstats.readonly+"
    "files.readonly+forms.readonly+forms.write+funnels%2Fredirect.readonly+funnels%2Fpage.readonly+"
    "funnels%2Ffunnel.readonly+funnels%2Fpagecount.readonly+funnels%2Fredirect.write+invoices.readonly+"
    "invoices.write+invoices%2Fschedule.readonly+invoices%2Fschedule.write+invoices%2Ftemplate.readonly+"
    "invoices%2Ftemplate.write+invoices%2Festimate.readonly+invoices%2Festimate.write+knowledge-bases.write+"
    "knowledge-bases.readonly+lc-email.readonly+links.readonly+links.write+locations.readonly+"
    "locations%2FcustomValues.readonly+locations%2FcustomValues.write+locations%2Ftasks.readonly+"
    "locations%2Ftasks.write+recurring-tasks.readonly+recurring-tasks.write+locations%2Ftags.readonly+"
    "locations%2Ftags.write+locations%2Ftemplates.readonly+charges.readonly+charges.write+"
    "marketplace-installer-details.readonly+marketplace-external-auth-migration.write+medias.readonly+"
    "medias.write+oauth.write+oauth.readonly+objects%2Fschema.readonly+objects%2Fschema.write+"
    "objects%2Frecord.readonly+objects%2Frecord.write+opportunities.readonly+opportunities.write+"
    "payments%2Forders.readonly+payments%2Forders.write+payments%2Forders.collectPayment+"
    "payments%2Fintegration.readonly+payments%2Fintegration.write+payments%2Ftransactions.readonly+"
    "payments%2Fsubscriptions.readonly+payments%2Fcoupons.readonly+payments%2Fcoupons.write+"
    "payments%2Fcustom-provider.readonly+payments%2Fcustom-provider.write+phonenumbers.read+phonenumbers.write+"
    "numberpools.read+products.readonly+products.write+products%2Fprices.readonly+products%2Fprices.write+"
    "products%2Fcollection.readonly+products%2Fcollection.write+documents_contracts%2Flist.readonly+"
    "documents_contracts%2FsendLink.write+documents_contracts_template%2FsendLink.write+"
    "documents_contracts_template%2Flist.readonly+saas%2Flocation.read+saas%2Flocation.write+"
    "socialplanner%2Foauth.readonly+socialplanner%2Foauth.write+socialplanner%2Fpost.readonly+"
    "socialplanner%2Fpost.write+socialplanner%2Faccount.readonly+socialplanner%2Faccount.write+"
    "socialplanner%2Fcsv.readonly+socialplanner%2Fcsv.write+socialplanner%2Fcategory.readonly+"
    "socialplanner%2Ftag.readonly+socialplanner%2Fstatistics.readonly+socialplanner%2Fcomments.readonly+"
    "socialplanner%2Fcomments.write+socialplanner%2Fcategory.write+socialplanner%2Ftag.write+"
    "store%2Fshipping.readonly+store%2Fshipping.write+store%2Fsetting.readonly+store%2Fsetting.write+"
    "surveys.readonly+twilioaccount.read+users.readonly+voice-ai-dashboard.readonly+voice-ai-agents.readonly+"
    "voice-ai-agents.write+voice-ai-agent-goals.readonly+voice-ai-agent-goals.write+wordpress.site.readonly+"
    "workflows.readonly&version_id=6a3c63e708b022331c8b15d5"
)
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


def install_url():
    return _env("GHL_INSTALL_URL") or DEFAULT_INSTALL_URL


def webhook_public_key():
    """PEM public key used to verify inbound webhook signatures (Phase 2)."""
    return _env("GHL_WEBHOOK_PUBLIC_KEY")


def scopes():
    configured_scopes = _env("GHL_SCOPES")
    if configured_scopes:
        return configured_scopes
    parsed_scopes = parse_qs(urlsplit(install_url()).query).get("scope", [""])[0].strip()
    return parsed_scopes or _DEFAULT_SCOPES


def is_configured():
    """True when the minimum credentials for the OAuth flow are present."""
    return bool(client_id() and client_secret() and redirect_uri())
