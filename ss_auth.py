import json
import keyring
from requests_oauthlib import OAuth2Session
import smartsheet
import requests

SERVICE_NAME = "smartsheet"
AUTH_URL = "https://app.smartsheet.com/b/authorize"
TOKEN_URL = "https://api.smartsheet.com/2.0/token"
REDIRECT_URI = "http://127.0.0.1:8080/"
SCOPE = ["READ_SHEETS", "WRITE_SHEETS"]

CLIENT_ID = keyring.get_password(SERVICE_NAME, "client_id")
CLIENT_SECRET = keyring.get_password(SERVICE_NAME, "client_secret")

if not CLIENT_ID or not CLIENT_SECRET:
    raise ValueError("❌ Missing Smartsheet credentials. Run setup_smartsheet_secrets.py first.")

# Load existing token (if any)
token_data = None
stored_token = keyring.get_password(SERVICE_NAME, "oauth_token")
if stored_token:
    try:
        token_data = json.loads(stored_token)
        print("🔑 Loaded existing OAuth token from Windows Secrets.")
    except json.JSONDecodeError:
        print("⚠️ Stored token is invalid. A new login will be required.")
        token_data = None


def token_saver(token):
    """Automatically called when a token is refreshed or obtained."""
    keyring.set_password(SERVICE_NAME, "oauth_token", json.dumps(token))
    print("💾 Token securely updated in Windows Secrets.")


# Initialize OAuth session (handles auto-refresh)
oauth = OAuth2Session(
    client_id=CLIENT_ID,
    token=token_data,
    redirect_uri=REDIRECT_URI,
    scope=SCOPE,
    auto_refresh_url=TOKEN_URL,
    auto_refresh_kwargs={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    },
    token_updater=token_saver,
)

# If no token exists, do manual authorization flow
if not token_data:
    print("🌐 No existing token found. Starting manual authorization...")
    authorization_url, _ = oauth.authorization_url(AUTH_URL)
    print(f"\n➡️  Go to this URL and authorize access:\n{authorization_url}\n")
    auth_code = input("Enter the authorization code: ").strip()

    token_data = oauth.fetch_token(
        TOKEN_URL,
        code=auth_code,
        client_secret=CLIENT_SECRET,
        include_client_id=True,
    )
    token_saver(token_data)
else:
    # Force a token refresh every time the script runs
    print("🔄 Refreshing token...")

    try:
        refreshed_token = oauth.refresh_token(
            TOKEN_URL,
            refresh_token=token_data.get("refresh_token"),
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
        )
        token_saver(refreshed_token)
        token_data = refreshed_token
        oauth.token = refreshed_token
    except Exception as e:
        print(f"⚠️ Token refresh failed: {e}")
        print("Attempting manual re-authentication...")
        keyring.delete_password(SERVICE_NAME, "oauth_token")

        authorization_url, _ = oauth.authorization_url(AUTH_URL)
        print(f"\n➡️  Go to this URL and authorize access:\n{authorization_url}\n")
        auth_code = input("Enter the authorization code: ").strip()

        token_data = oauth.fetch_token(
            TOKEN_URL,
            code=auth_code,
            client_secret=CLIENT_SECRET,
            include_client_id=True,
        )
        token_saver(token_data)
        oauth.token = token_data

# Get access token
access_token = token_data.get("access_token")
if not access_token:
    raise ValueError("❌ Missing access_token in OAuth token data.")

# Initialize Smartsheet client
smartsheet_client = smartsheet.Smartsheet(access_token)
smartsheet_client.errors_as_exceptions(True)

print("✅ Smartsheet client ready to use.")