import streamlit as st
import pandas as pd
import time
from datetime import datetime
import importlib.util
import math

# ---------------- UI Password ----------------
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return True

    st.title("Secure Access")
    password = st.text_input("Enter password", type="password")
    if st.button("Login"):
        if password == st.secrets["app_password"]:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password")
    return False

if not check_password():
    st.stop()

# ---------------- Config ----------------
SHEETS = st.secrets["sheets"]
DATE_CFG = st.secrets["date_update"]

st.set_page_config(page_title="Smartsheet Moves Management Upload", layout="wide")
st.title("Smartsheet Moves Management Upload")

# ---------------- Auth ----------------
spec = importlib.util.spec_from_file_location("ss_auth", "ss_auth.py")
ss_auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss_auth)
client = ss_auth.get_client()

# ---------------- UI ----------------
location = st.radio("Location", ["Denver", "Western Slope"], horizontal=True)
gifts_sheet_id = SHEETS["gifts_denver"] if location == "Denver" else SHEETS["gifts_wslope"]
update_dates = location == "Denver" and st.checkbox("Update last meeting date")

uploaded_files = st.file_uploader(
    "Upload Actions / Proposals / Gifts CSVs",
    type="csv",
    accept_multiple_files=True
)

run = st.button("🚀 Run Upload")
log_box = st.empty()
def log(msg):
    log_box.code(msg)

# ---------------- Helpers ----------------
def format_smartsheet_date(val):
    try:
        dt = pd.to_datetime(val, errors="coerce")
        return None if pd.isna(dt) else dt.strftime("%Y-%m-%d")
    except Exception:
        return None

def format_currency(val):
    try:
        return round(float(str(val).replace("$","").replace(",","")), 2)
    except Exception:
        return None

def clear_non_blank_rows(client, sheet_name, sheet_id, log):
    log(f"Checking {sheet_name} sheet for existing rows...")
    sheet = client.Sheets.get_sheet(sheet_id)
    rows = [r.id for r in sheet.rows if any(c.value not in [None, ""] and str(c.value).strip() != "" for c in r.cells)]
    log(f"Found {len(rows)} non-blank rows in {sheet_name} sheet.")
    if not rows:
        return

    batch_size = 300
    progress_bar = st.progress(0)
    deleted_total = 0
    num_batches = math.ceil(len(rows) / batch_size)
    
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i+batch_size]
        client.Sheets.delete_rows(sheet_id, batch)
        deleted_total += len(batch)
        
        # update progress bar
        progress = (i + len(batch)) / len(rows)
        progress_bar.progress(progress)
        
        log(f"🗑 Deleted {deleted_total}/{len(rows)} rows from {sheet_name}...")
        time.sleep(1)
    
    progress_bar.empty()
    log(f"✅ Finished clearing {sheet_name} sheet ({deleted_total} rows).")

    log(f"✅ Finished clearing {sheet_name} sheet.")

def write_rows_to_sheet(client, sheet_name, sheet_id, df, log_fn, primary_column_name=None):
    from smartsheet import models as sm

    if df is None or df.empty:
        log_fn(f"⚠ No rows to write to sheet {sheet_name}.")
        return 0

    sheet = client.Sheets.get_sheet(sheet_id)
    col_map = {c.title.strip().lower(): c.id for c in sheet.columns}
    col_types = {c.title.strip().lower(): c.type for c in sheet.columns}

    created_rows = []

    for i, row in df.iterrows():
        r = sm.Row()
        r.to_bottom = True

        # Primary column
        if primary_column_name and primary_column_name.lower() in col_map:
            val = row.get(primary_column_name) or f"Row {i+1}"
            cell = sm.Cell()
            cell.column_id = col_map[primary_column_name.lower()]
            cell.value = val
            r.cells.append(cell)

        for col in df.columns:
            key = col.lower()
            if key not in col_map or (primary_column_name and key == primary_column_name.lower()):
                continue
            val = row[col]
            if val in [None, ""]:
                continue
            if col_types.get(key) == "DATE":
                val = format_smartsheet_date(val)
            cell = sm.Cell()
            cell.column_id = col_map[key]
            cell.value = val
            r.cells.append(cell)

        if r.cells:
            created_rows.append(r)

    if not created_rows:
        log_fn(f"⚠ No valid rows to add to sheet {sheet_name}.")
        return 0

    added = 0
    batch_size = 200
    num_batches = math.ceil(len(created_rows) / batch_size)
    progress_bar = st.progress(0)
    
    for i in range(0, len(created_rows), batch_size):
        batch = created_rows[i:i+batch_size]
        client.Sheets.add_rows(sheet_id, batch)
        added += len(batch)
    
        # update progress bar
        progress = min((i + len(batch)) / len(created_rows), 1.0)
        progress_bar.progress(progress)
    
        log_fn(f"  • Added {added}/{len(created_rows)} rows to sheet {sheet_name}...")
    
    progress_bar.empty()
    log_fn(f"✅ Finished writing {added} rows to sheet {sheet_name}.")

# ---------------- Transformers ----------------
def transform_actions(df):
    df = df.copy()
    df["Action Unique ID"] = (df.get("Action Import ID","").astype(str) + " " + df.get("Solicitor Name","").astype(str)).str.strip()
    return df

def transform_proposals(df):
    df = df.copy()
    df["Proposal Name"] = df.get("Proposal Name", "").fillna("No Proposals")
    df["Primary Solicitor"] = df.apply(lambda r: r["Primary Solicitor"] if r.get("Primary Solicitor") else "No Primary Solicitor", axis=1)
    for col in ["Amount Asked", "Amount Expected", "Amount Funded"]:
        if col in df.columns:
            df[col] = df[col].apply(format_currency)
    return df

def transform_gifts(df):
    df = df.copy()
    if "Gift Amount" in df.columns:
        df["Gift Amount"] = df["Gift Amount"].apply(format_currency)
    return df

def update_date_cell(client):
    sheet = client.Sheets.get_sheet(DATE_CFG["sheet_id"], include="rows")
    col_id = next(c.id for c in sheet.columns if c.title == DATE_CFG["column_name"])
    prev = next(c.value for r in sheet.rows if r.id == DATE_CFG["target_row_id"] for c in r.cells if c.column_id==col_id)
    today = datetime.now().strftime("%Y-%m-%d")
    client.Sheets.update_rows(DATE_CFG["sheet_id"], [
        {"id": DATE_CFG["target_row_id"], "cells":[{"columnId": col_id, "value": today}]},
        {"id": DATE_CFG["old_row_id"], "cells":[{"columnId": col_id, "value": prev}]}
    ])

# ---------------- Run ----------------
if run:
    if not uploaded_files:
        st.warning("Please upload at least one CSV.")
        st.stop()

    log("Clearing target sheets...")

    sheets_to_clear = [
        ("Actions", SHEETS["actions"]),
        ("Proposals", SHEETS["proposals"]),
    ]
    
    gifts_sheet_key = "gifts_denver" if location == "Denver" else "gifts_wslope"
    sheets_to_clear.append(("Gifts", SHEETS[gifts_sheet_key]))
    
    for name, sheet_id in sheets_to_clear:
        clear_non_blank_rows(client, name, sheet_id, log)


    for file in uploaded_files:
        df = pd.read_csv(file, dtype=str, encoding="cp1252").fillna("")
        lower = file.name.lower()
        if "action" in lower:
            write_rows_to_sheet(
                client,
                "Actions",
                SHEETS["actions"],
                transform_actions(df),
                log_fn=log,
                primary_column_name="Action Unique ID"
            )
        elif "proposal" in lower:
            write_rows_to_sheet(
                client,
                "Proposals",
                SHEETS["proposals"],
                transform_proposals(df),
                log_fn=log
            )
        elif "gift" in lower:
            write_rows_to_sheet(
                client,
                "Gifts",
                gifts_sheet_id,
                transform_gifts(df),
                log_fn=log
            )

    if update_dates:
        update_date_cell(client)

    st.success("🎉 Smartsheet successfully updated!")
