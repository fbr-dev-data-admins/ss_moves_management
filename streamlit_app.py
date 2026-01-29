import streamlit as st
import pandas as pd
import time
from datetime import datetime
import importlib.util

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

SHEETS = st.secrets["sheets"]
DATE_CFG = st.secrets["date_update"]

st.set_page_config(page_title="Smartsheet Moves Management Upload", layout="wide")
st.title("Smartsheet Moves Management Upload")

spec = importlib.util.spec_from_file_location("ss_auth", "ss_auth.py")
ss_auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss_auth)
client = ss_auth.get_client()

location = st.radio("Location", ["Denver", "Western Slope"], horizontal=True)
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

def format_smartsheet_date(val):
    dt = pd.to_datetime(val, errors="coerce")
    return None if pd.isna(dt) else dt.strftime("%Y-%m-%d")

def format_currency(val):
    try:
        return round(float(str(val).replace("$","").replace(",","")), 2)
    except:
        return None

def clear_non_blank_rows(client, sheet_name, sheet_id, log_fn):
    log_fn(f"Checking {sheet_name} sheet for existing rows...")
    sheet = client.Sheets.get_sheet(sheet_id)
    primary_col_id = next(c.id for c in sheet.columns if c.primary)
    rows = [r.id for r in sheet.rows if any(c.value not in [None,""] for c in r.cells if c.column_id == primary_col_id)]
    log_fn(f"Found {len(rows)} non-blank rows in {sheet_name} sheet.")
    if not rows:
        log_fn(f"No rows to delete in {sheet_name}.")
        return
    for i in range(0, len(rows), 300):
        client.Sheets.delete_rows(sheet_id, rows[i:i+300])
        log_fn(f"Deleted {min(300, len(rows)-i)} rows from {sheet_name}...")
        time.sleep(1)
    log_fn(f"✅ Finished clearing {sheet_name} sheet.")

def write_rows_to_sheet(client, sheet_name, sheet_id, df, log_fn, primary_column_name=None):
    from smartsheet import models as sm
    if df is None or df.empty:
        log_fn(f"⚠ No rows to write to sheet {sheet_name}.")
        return 0
    sheet = client.Sheets.get_sheet(sheet_id)
    col_map = {c.title.lower(): c.id for c in sheet.columns}
    col_types = {c.title.lower(): c.type for c in sheet.columns}
    created_rows = []
    for i, row in df.iterrows():
        r = sm.Row()
        r.to_bottom = True
        if primary_column_name and primary_column_name.lower() in col_map:
            val = row.get(primary_column_name) or f"Row {i+1}"
            r.cells.append(sm.Cell(column_id=col_map[primary_column_name.lower()], value=val))
        for col in df.columns:
            key = col.lower()
            if key not in col_map or (primary_column_name and key == primary_column_name.lower()):
                continue
            val = row[col]
            if val in [None,""]:
                continue
            if col_types.get(key) == "DATE":
                val = format_smartsheet_date(val)
            r.cells.append(sm.Cell(column_id=col_map[key], value=val))
        if r.cells:
            created_rows.append(r)
    if not created_rows:
        log_fn(f"⚠ No valid rows to add to sheet {sheet_name}.")
        return 0
    added = 0
    batch_size = 200
    for i in range(0, len(created_rows), batch_size):
        batch = created_rows[i:i+batch_size]
        client.Sheets.add_rows(sheet_id, batch)
        added += len(batch)
        log_fn(f"  • Added {len(batch)} rows to sheet {sheet_name}.")
        time.sleep(0.5)
    log_fn(f"✅ Finished writing {added} rows to sheet {sheet_name}.")
    return added

def transform_actions(df):
    df = df.copy()
    df["Action Unique ID"] = (df.get("Action Import ID","").astype(str) + " " + df.get("Solicitor Name","").astype(str)).str.strip()
    return df

def transform_gifts(df):
    df = df.copy()
    if "Gift Amount" in df.columns:
        df["Gift Amount"] = df["Gift Amount"].apply(format_currency)
    return df

def transform_proposals(df):
    df = df.copy()
    df["Proposal Name"] = df.get("Proposal Name","").fillna("No Proposals")
    if "Proposal Import ID" in df.columns:
        df["Proposal Import ID"] = df["Proposal Import ID"].fillna(df["Constituent ID"].astype(str) + " - " + df["Proposal Name"])
    def fill_solicitor(row):
        if not row.get("Primary Solicitor"):
            return "No Primary Solicitor - Capital Campaign" if row.get("Campaign")=="CCDEN" else "No Primary Solicitor - Annual Giving"
        return row["Primary Solicitor"]
    df["Primary Solicitor"] = df.apply(fill_solicitor, axis=1)
    base_cols = ["Constituent ID","Name","Primary Solicitor"]
    proposal_cols = [c for c in df.columns if c.startswith("Proposal Import ID")]
    rows=[]
    for _,row in df.iterrows():
        for col in proposal_cols:
            if not row[col]:
                continue
            r = row[base_cols].to_dict()
            r["Proposal Import ID"]=row[col]
            rows.append(r)
    return pd.DataFrame(rows)

def update_date_cell(client):
    sheet = client.Sheets.get_sheet(DATE_CFG["sheet_id"], include="rows")
    col_id = next(c.id for c in sheet.columns if c.title == DATE_CFG["column_name"])
    today = datetime.now().strftime("%Y-%m-%d")
    prev = next(c.value for r in sheet.rows if r.id==DATE_CFG["target_row_id"] for c in r.cells if c.column_id==col_id)
    client.Sheets.update_rows(DATE_CFG["sheet_id"], [
        {"id": DATE_CFG["target_row_id"], "cells":[{"columnId":col_id,"value":today}]},
        {"id": DATE_CFG["old_row_id"], "cells":[{"columnId":col_id,"value":prev}]},
    ])

if run:
    if not uploaded_files:
        st.warning("Please upload at least one CSV.")
        st.stop()

    gifts_sheet_key = "gifts_denver" if location=="Denver" else "gifts_wslope"

    log("Clearing target sheets...")
    for name,key in [("Actions","actions"),("Proposals","proposals"),("Gifts",gifts_sheet_key)]:
        clear_non_blank_rows(client,name,SHEETS[key],log)

    for file in uploaded_files:
        df = pd.read_csv(file,dtype=str,encoding="cp1252").fillna("")
        name_lower=file.name.lower()
        if "action" in name_lower:
            write_rows_to_sheet(client,"Actions",SHEETS["actions"],transform_actions(df),log,primary_column_name="Action Unique ID")
        elif "proposal" in name_lower:
            write_rows_to_sheet(client,"Proposals",SHEETS["proposals"],transform_proposals(df),log)
        elif "gift" in name_lower:
            write_rows_to_sheet(client,"Gifts",SHEETS[gifts_sheet_key],transform_gifts(df),log)

    if update_dates:
        update_date_cell(client)

    st.success("🎉 Smartsheet successfully updated!")
