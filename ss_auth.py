import streamlit as st
from requests_oauthlib import OAuth2Session
import smartsheet

AUTH_URL = "https://app.smartsheet.com/b/authorize"
TOKEN_URL = "https://api.smartsheet.com/2.0/token"
REDIRECT_URI = "http://localhost"
SCOPE = ["READ_SHEETS", "WRITE_SHEETS"]

CLIENT_ID = st.secrets["smartsheet"]["client_id"]
CLIENT_SECRET = st.secrets["smartsheet"]["client_secret"]

def get_client():
    if "smartsheet_token" not in st.session_state:
        oauth = OAuth2Session(
            CLIENT_ID,
            redirect_uri=REDIRECT_URI,
            scope=SCOPE
        )
        auth_url, _ = oauth.authorization_url(AUTH_URL)
        st.markdown("### Step 1: Authenticate with Smartsheet")
        st.markdown(f"[Click here to authorize]({auth_url})")
        code = st.text_input("Step 2: Paste the code here")
        if not code:
            st.stop()
        try:
            token = oauth.fetch_token(
                TOKEN_URL,
                code=code,
                client_secret=CLIENT_SECRET,
                include_client_id=True
            )
        except Exception as e:
            st.error(f"Failed to fetch token: {e}")
            st.stop()
        st.session_state.smartsheet_token = token

    token = st.session_state.smartsheet_token
    client = smartsheet.Smartsheet(token["access_token"])
    client.errors_as_exceptions(True)
    return client
