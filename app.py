"""
app.py — Micro QA
============================================================
Main Streamlit application.

Navigation (sidebar):
  1. 🏥 Dashboard
  2. 📋 QA Data Entry
  3. 📈 Trending & Reports
  4. 🔧 Service & Downtime Log
  5. ⚙️ Admin / Settings

Run with:
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date

# ── Initialise the database on first run ─────────────────────────────────────
from db_setup import init_db, seed_db
from crud import (
    get_units, get_unit_by_id,
    get_tests, get_tests_for_unit, get_test_by_id,
    add_unit, update_unit, add_test, assign_test_to_unit,
    log_result, get_historical_data, get_recent_results,
    add_service_log, get_service_logs,
    get_status_summary,
)

# TRS-398 page (pylinac required)
try:
    from trs398_page import page_trs398
    _HAS_PYLINAC = True
except ImportError:
    _HAS_PYLINAC = False

init_db()
seed_db()


# ===========================================================================
# Page Configuration
# ===========================================================================
st.set_page_config(
    page_title="Micro QA",
    page_icon="⚕️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ===========================================================================
# Custom CSS — clean, clinical look
# ===========================================================================
st.markdown(
    """
    <style>
        /* ── Global ── */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

        /* ── Sidebar ── */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0d1b2a 0%, #1b263b 100%);
        }
        [data-testid="stSidebar"] * { color: #e0e6f0 !important; }
        [data-testid="stSidebar"] .stRadio label { font-size: 0.95rem; padding: 4px 0; }

        /* ── Metric cards ── */
        [data-testid="metric-container"] {
            background: #f0f4f8;
            border-radius: 10px;
            padding: 16px 20px;
            border-left: 4px solid #415a77;
        }

        /* ── Status badges ── */
        .badge-ok       { color:#fff; background:#2d9e5f; padding:3px 10px; border-radius:12px; font-size:0.82rem; font-weight:600; }
        .badge-tol      { color:#fff; background:#e58b00; padding:3px 10px; border-radius:12px; font-size:0.82rem; font-weight:600; }
        .badge-action   { color:#fff; background:#c0392b; padding:3px 10px; border-radius:12px; font-size:0.82rem; font-weight:600; }

        /* ── Section headers ── */
        .section-header {
            font-size: 1.5rem; font-weight: 700; color: #1b263b;
            margin-bottom: 1rem; border-bottom: 2px solid #415a77; padding-bottom: 6px;
        }

        /* ── Data table tweaks ── */
        .stDataFrame { border-radius: 8px; overflow: hidden; }

        /* ── Form inputs ── */
        textarea, input[type="text"], input[type="number"] { border-radius: 6px !important; }

        /* ── Status alert box ── */
        .status-box {
            padding: 12px 18px; border-radius: 8px; font-size: 1rem;
            font-weight: 600; margin-top: 12px;
        }
        .status-ok     { background:#d4edda; color:#155724; border:1px solid #c3e6cb; }
        .status-tol    { background:#fff3cd; color:#856404; border:1px solid #ffc107; }
        .status-action { background:#f8d7da; color:#721c24; border:1px solid #f5c6cb; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ===========================================================================
# Sidebar Navigation
# ===========================================================================
with st.sidebar:
    st.markdown("## ⚕️ Micro QA")
    st.markdown("---")
    page = st.radio(
        "Navigation",
        options=[
            "🏥 Dashboard",
            "📋 QA Data Entry",
            "📈 Trending & Reports",
            "☢️ TRS-398 Calibration",
            "🔧 Service & Downtime Log",
            "⚙️ Admin / Settings",
        ],
        label_visibility="collapsed",
    )
    st.markdown("---")
    st.caption("v1.1.0 — Local SQLite Edition")


# ===========================================================================
# Helpers
# ===========================================================================

def status_badge_html(status: str) -> str:
    """Return an HTML badge string for a given status."""
    cls = {"OK": "badge-ok", "Tolerance": "badge-tol", "Action": "badge-action"}.get(status, "badge-ok")
    return f'<span class="{cls}">{status}</span>'


def status_box_html(status: str, value: float, unit: str) -> str:
    """Return a coloured status announcement box."""
    messages = {
        "OK":        f"✅ Value {value:.3f} {unit} is within tolerance. All clear.",
        "Tolerance": f"⚠️  Value {value:.3f} {unit} is outside tolerance — review required.",
        "Action":    f"🚨  Value {value:.3f} {unit} has exceeded the ACTION level! Immediate action required.",
    }
    css_class = {"OK": "status-ok", "Tolerance": "status-tol", "Action": "status-action"}.get(status, "status-ok")
    return f'<div class="status-box {css_class}">{messages.get(status, "")}</div>'


def build_control_chart(df: pd.DataFrame, test: dict) -> go.Figure:
    """
    Build a Plotly control chart for a float-type test.
    Plots measured values with colour-coded markers and overlays
    the Reference, Tolerance, and Action limit lines.
    """
    # Colour-map each point by status
    color_map = {"OK": "#2d9e5f", "Tolerance": "#e58b00", "Action": "#c0392b"}
    marker_colors = df["status"].map(color_map).fillna("#415a77")

    fig = go.Figure()

    # ── Measured values ───────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=df["performed_at"],
        y=df["value_float"],
        mode="lines+markers",
        name="Measured",
        line=dict(color="#415a77", width=1.5),
        marker=dict(color=marker_colors.tolist(), size=8, line=dict(width=1, color="#fff")),
        hovertemplate="<b>%{x|%Y-%m-%d %H:%M}</b><br>Value: %{y:.3f}<extra></extra>",
    ))

    # ── Reference line ────────────────────────────────────────────────────
    ref = test.get("reference_value")
    if ref is not None:
        fig.add_hline(
            y=ref, line=dict(color="#2d9e5f", width=2, dash="dash"),
            annotation_text=f"Reference ({ref})", annotation_position="top left",
            annotation_font_color="#2d9e5f",
        )

    # ── Tolerance band ────────────────────────────────────────────────────
    tol_lo = test.get("tolerance_low")
    tol_hi = test.get("tolerance_high")
    if tol_lo is not None and tol_hi is not None:
        fig.add_hrect(
            y0=tol_lo, y1=tol_hi,
            fillcolor="rgba(45,158,95,0.08)", line_width=0,
            annotation_text="Tolerance Zone", annotation_position="top right",
            annotation_font_color="#2d9e5f",
        )
        fig.add_hline(y=tol_lo, line=dict(color="#e58b00", width=1.5, dash="dot"),
                      annotation_text=f"Tol Low ({tol_lo})", annotation_position="bottom left",
                      annotation_font_color="#e58b00")
        fig.add_hline(y=tol_hi, line=dict(color="#e58b00", width=1.5, dash="dot"),
                      annotation_text=f"Tol High ({tol_hi})", annotation_position="top left",
                      annotation_font_color="#e58b00")

    # ── Action limit lines ────────────────────────────────────────────────
    act_lo = test.get("action_low")
    act_hi = test.get("action_high")
    if act_lo is not None:
        fig.add_hline(y=act_lo, line=dict(color="#c0392b", width=1.5, dash="dashdot"),
                      annotation_text=f"Action Low ({act_lo})", annotation_position="bottom left",
                      annotation_font_color="#c0392b")
    if act_hi is not None:
        fig.add_hline(y=act_hi, line=dict(color="#c0392b", width=1.5, dash="dashdot"),
                      annotation_text=f"Action High ({act_hi})", annotation_position="top left",
                      annotation_font_color="#c0392b")

    unit_label = test.get("unit_of_measure") or ""
    fig.update_layout(
        title=dict(text=f"<b>{test['name']}</b> — Control Chart", font=dict(size=18)),
        xaxis_title="Date / Time",
        yaxis_title=f"Value ({unit_label})" if unit_label else "Value",
        plot_bgcolor="#fafcff",
        paper_bgcolor="#ffffff",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        margin=dict(l=60, r=40, t=80, b=60),
        height=480,
    )
    fig.update_xaxes(showgrid=True, gridcolor="#e8edf3")
    fig.update_yaxes(showgrid=True, gridcolor="#e8edf3")

    return fig


# ===========================================================================
# Page: Dashboard
# ===========================================================================
def page_dashboard():
    st.markdown('<div class="section-header">🏥 Today\'s QA Dashboard</div>', unsafe_allow_html=True)
    today = date.today().strftime("%B %d, %Y")
    st.caption(f"Date: {today}")

    units_df = get_units()
    if units_df.empty:
        st.info("No units found. Add a unit in Admin / Settings.")
        return

    summary_df = get_status_summary()

    # ── Top-level status metrics ──────────────────────────────────────────
    total_ok  = int(summary_df.loc[summary_df["status"] == "OK",        "count"].sum()) if not summary_df.empty else 0
    total_tol = int(summary_df.loc[summary_df["status"] == "Tolerance", "count"].sum()) if not summary_df.empty else 0
    total_act = int(summary_df.loc[summary_df["status"] == "Action",    "count"].sum()) if not summary_df.empty else 0
    total_all = total_ok + total_tol + total_act

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Results Today",  total_all)
    c2.metric("✅ OK",                 total_ok,  delta=None)
    c3.metric("⚠️ Tolerance",          total_tol, delta=None)
    c4.metric("🚨 Action Level",       total_act, delta=None)

    st.markdown("---")

    # ── Per-unit summary table ────────────────────────────────────────────
    st.subheader("Per-Unit Status Breakdown (Today)")
    if summary_df.empty:
        st.info("No QA data has been recorded today yet.")
    else:
        pivot = summary_df.pivot_table(index="unit_name", columns="status", values="count", fill_value=0).reset_index()
        st.dataframe(pivot, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── Equipment overview ────────────────────────────────────────────────
    st.subheader("Equipment Overview")
    st.dataframe(
        units_df[["name", "modality", "manufacturer", "model", "location"]],
        use_container_width=True,
        hide_index=True,
    )


# ===========================================================================
# Page: QA Data Entry
# ===========================================================================
def page_qa_entry():
    st.markdown('<div class="section-header">📋 QA Data Entry</div>', unsafe_allow_html=True)

    units_df = get_units()
    if units_df.empty:
        st.warning("No units registered. Please add a unit in ⚙️ Admin / Settings first.")
        return

    # ── Selectors ──────────────────────────────────────────────────────────
    col_unit, col_test = st.columns(2)

    with col_unit:
        unit_names = units_df["name"].tolist()
        selected_unit_name = st.selectbox("Select Unit", unit_names, key="entry_unit")
        selected_unit_id   = int(units_df.loc[units_df["name"] == selected_unit_name, "id"].values[0])

    tests_for_unit = get_tests_for_unit(selected_unit_id)

    with col_test:
        if tests_for_unit.empty:
            st.warning("No tests assigned to this unit. Assign tests in ⚙️ Admin / Settings.")
            return
        test_names       = tests_for_unit["name"].tolist()
        selected_test_name = st.selectbox("Select Test", test_names, key="entry_test")
        selected_test_id   = int(tests_for_unit.loc[tests_for_unit["name"] == selected_test_name, "id"].values[0])

    test = get_test_by_id(selected_test_id)

    # ── Test metadata info box ─────────────────────────────────────────────
    with st.expander("ℹ️ Test Definition Details", expanded=False):
        info_cols = st.columns(4)
        info_cols[0].metric("Frequency",  test.get("frequency") or "—")
        info_cols[1].metric("Reference",  f"{test.get('reference_value')} {test.get('unit_of_measure') or ''}".strip() if test.get('reference_value') is not None else "—")
        info_cols[2].metric("Tolerance",  f"{test.get('tolerance_low')} / {test.get('tolerance_high')}" if test.get('tolerance_low') is not None else "—")
        info_cols[3].metric("Action",     f"{test.get('action_low')} / {test.get('action_high')}"     if test.get('action_low')     is not None else "—")
        if test.get("description"):
            st.caption(test["description"])

    st.markdown("---")

    # ── Data-entry form ────────────────────────────────────────────────────
    with st.form("qa_entry_form", clear_on_submit=True):
        st.subheader("Enter Result")

        data_type = test.get("data_type", "float")
        value_float   = None
        value_bool    = None
        value_choice  = None

        if data_type == "float":
            ref = test.get("reference_value") or 0.0
            value_float = st.number_input(
                f"Measured Value ({test.get('unit_of_measure') or 'units'})",
                value=float(ref),
                format="%.4f",
                step=0.01,
            )

        elif data_type == "boolean":
            value_bool = st.selectbox("Result", options=["Pass", "Fail"]) == "Pass"

        elif data_type == "choice":
            choices_raw = test.get("choices") or ""
            options = [c.strip() for c in choices_raw.split(",") if c.strip()]
            if options:
                value_choice = st.selectbox("Result", options=options)
            else:
                st.warning("No choices defined for this test. Edit via ⚙️ Admin / Settings.")

        fcol1, fcol2 = st.columns(2)
        with fcol1:
            performed_by = st.text_input("Performed By", placeholder="Your name or initials")
        with fcol2:
            performed_at_date = st.date_input("Date of Measurement", value=date.today())
            performed_at_time = st.time_input("Time of Measurement", value=datetime.now().time())

        comment = st.text_area("Comment / Notes", placeholder="Optional observations…", height=80)

        submitted = st.form_submit_button("💾 Submit Result", use_container_width=True, type="primary")

    # ── Process submission ─────────────────────────────────────────────────
    if submitted:
        performed_at_dt = datetime.combine(performed_at_date, performed_at_time).isoformat(timespec="seconds")

        status = log_result(
            unit_id       = selected_unit_id,
            test_id       = selected_test_id,
            value_float   = value_float,
            value_boolean = value_bool,
            value_choice  = value_choice,
            performed_by  = performed_by,
            comment       = comment,
            performed_at  = performed_at_dt,
        )

        # ── Visual feedback based on status ───────────────────────────────
        unit_label = test.get("unit_of_measure") or ""

        if data_type == "float" and value_float is not None:
            st.markdown(status_box_html(status, value_float, unit_label), unsafe_allow_html=True)
        else:
            # Boolean / choice always shows success
            st.success("✅ Result recorded successfully.")

        st.balloons() if status == "OK" else None

    # ── Recent results for this unit ───────────────────────────────────────
    st.markdown("---")
    st.subheader(f"Recent Entries — {selected_unit_name}")
    recent = get_recent_results(selected_unit_id, limit=10)
    if recent.empty:
        st.info("No results recorded yet for this unit.")
    else:
        # Colour the status column
        st.dataframe(recent, use_container_width=True, hide_index=True)


# ===========================================================================
# Page: Trending & Reports
# ===========================================================================
def page_trending():
    st.markdown('<div class="section-header">📈 Trending & Reports</div>', unsafe_allow_html=True)

    units_df = get_units()
    if units_df.empty:
        st.info("No units available.")
        return

    col_u, col_t, col_n = st.columns([2, 2, 1])

    with col_u:
        unit_names       = units_df["name"].tolist()
        sel_unit_name    = st.selectbox("Unit", unit_names, key="trend_unit")
        sel_unit_id      = int(units_df.loc[units_df["name"] == sel_unit_name, "id"].values[0])

    tests_df = get_tests_for_unit(sel_unit_id)

    with col_t:
        if tests_df.empty:
            st.warning("No tests for this unit.")
            return
        # Allow only float tests for the chart (boolean/choice don't make sense on a control chart)
        float_tests = tests_df[tests_df["data_type"] == "float"]
        if float_tests.empty:
            st.warning("No numeric (float) tests assigned to this unit.")
            return
        sel_test_name = st.selectbox("Test", float_tests["name"].tolist(), key="trend_test")
        sel_test_id   = int(float_tests.loc[float_tests["name"] == sel_test_name, "id"].values[0])

    with col_n:
        n_points = st.number_input("Max Points", min_value=10, max_value=500, value=90, step=10,
                                   help="Limit the number of historical data points displayed.")

    df = get_historical_data(sel_unit_id, sel_test_id)

    if df.empty:
        st.info("No historical data recorded for this unit/test combination yet.")
        return

    # Limit to most recent N points
    if len(df) > n_points:
        df = df.tail(int(n_points))

    test = get_test_by_id(sel_test_id)

    # ── Summary statistics ─────────────────────────────────────────────────
    valid = df["value_float"].dropna()
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("N Points",  len(valid))
    s2.metric("Mean",      f"{valid.mean():.3f}")
    s3.metric("Std Dev",   f"{valid.std():.3f}")
    s4.metric("Min",       f"{valid.min():.3f}")
    s5.metric("Max",       f"{valid.max():.3f}")

    # ── Status distribution ────────────────────────────────────────────────
    status_counts = df["status"].value_counts()
    pct_ok  = status_counts.get("OK", 0) / max(len(df), 1) * 100
    pct_tol = status_counts.get("Tolerance", 0) / max(len(df), 1) * 100
    pct_act = status_counts.get("Action", 0) / max(len(df), 1) * 100

    b1, b2, b3 = st.columns(3)
    b1.metric("% OK",        f"{pct_ok:.1f}%")
    b2.metric("% Tolerance", f"{pct_tol:.1f}%", delta=None)
    b3.metric("% Action",    f"{pct_act:.1f}%", delta=None)

    st.markdown("---")

    # ── Control chart ─────────────────────────────────────────────────────
    fig = build_control_chart(df, test)
    st.plotly_chart(fig, use_container_width=True)

    # ── Raw data table (toggleable) ────────────────────────────────────────
    with st.expander("📄 Raw Data Table", expanded=False):
        display_df = df[["performed_at", "value_float", "status", "performed_by", "comment"]].copy()
        display_df.columns = ["Date/Time", "Value", "Status", "Performed By", "Comment"]
        st.dataframe(display_df, use_container_width=True, hide_index=True)

    # ── Download CSV ───────────────────────────────────────────────────────
    csv_data = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download CSV",
        data=csv_data,
        file_name=f"{sel_unit_name}_{sel_test_name}_{date.today()}.csv".replace(" ", "_"),
        mime="text/csv",
    )


# ===========================================================================
# Page: Service & Downtime Log
# ===========================================================================
def page_service_log():
    st.markdown('<div class="section-header">🔧 Service & Downtime Log</div>', unsafe_allow_html=True)

    units_df = get_units()
    if units_df.empty:
        st.warning("No units registered. Add a unit in ⚙️ Admin / Settings first.")
        return

    # ── Log new event ──────────────────────────────────────────────────────
    st.subheader("Log New Service Event")

    with st.form("service_form", clear_on_submit=True):
        sc1, sc2 = st.columns(2)

        with sc1:
            unit_names   = units_df["name"].tolist()
            sel_unit     = st.selectbox("Unit", unit_names, key="svc_unit")
            sel_unit_id  = int(units_df.loc[units_df["name"] == sel_unit, "id"].values[0])
            event_type   = st.selectbox(
                "Event Type",
                ["Downtime", "Preventive Maintenance", "Repair", "Inspection", "Note"],
            )
            performed_by = st.text_input("Performed By", placeholder="Engineer / Physicist name")

        with sc2:
            start_date = st.date_input("Start Date", value=date.today())
            start_time = st.time_input("Start Time", value=datetime.now().replace(minute=0, second=0).time())
            end_date   = st.date_input("End Date (optional)", value=date.today())
            end_time   = st.time_input("End Time (optional)", value=datetime.now().replace(minute=0, second=0).time())
            still_ongoing = st.checkbox("Machine still down / event ongoing")

        description = st.text_area("Description / Notes", placeholder="Details of the event…", height=100)

        submitted_svc = st.form_submit_button("📝 Log Event", use_container_width=True, type="primary")

    if submitted_svc:
        start_dt = datetime.combine(start_date, start_time).isoformat(timespec="seconds")
        end_dt   = None if still_ongoing else datetime.combine(end_date, end_time).isoformat(timespec="seconds")

        add_service_log(
            unit_id       = sel_unit_id,
            event_type    = event_type,
            start_datetime = start_dt,
            end_datetime   = end_dt,
            performed_by  = performed_by,
            description   = description,
        )
        st.success(f"✅ Service event logged for **{sel_unit}**.")

    st.markdown("---")

    # ── Filter & display logs ──────────────────────────────────────────────
    st.subheader("Service Log Records")

    fc1, fc2 = st.columns(2)
    with fc1:
        filter_unit = st.selectbox(
            "Filter by Unit",
            options=["All Units"] + units_df["name"].tolist(),
            key="svc_filter",
        )
    with fc2:
        filter_type = st.selectbox(
            "Filter by Event Type",
            options=["All Types", "Downtime", "Preventive Maintenance", "Repair", "Inspection", "Note"],
            key="svc_type_filter",
        )

    # Fetch logs
    if filter_unit == "All Units":
        logs_df = get_service_logs()
    else:
        uid = int(units_df.loc[units_df["name"] == filter_unit, "id"].values[0])
        logs_df = get_service_logs(unit_id=uid)

    if filter_type != "All Types" and not logs_df.empty:
        logs_df = logs_df[logs_df["event_type"] == filter_type]

    if logs_df.empty:
        st.info("No service log entries found.")
    else:
        # Format for display
        disp = logs_df[["unit_name", "event_type", "start_datetime", "end_datetime", "performed_by", "description"]].copy()
        disp.columns = ["Unit", "Event Type", "Start", "End", "Performed By", "Description"]
        disp["End"] = disp["End"].fillna("Ongoing ⚠️")
        st.dataframe(disp, use_container_width=True, hide_index=True)

        # ── Download ───────────────────────────────────────────────────────
        csv = logs_df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download Log CSV", data=csv,
                           file_name=f"service_log_{date.today()}.csv", mime="text/csv")


# ===========================================================================
# Page: Admin / Settings
# ===========================================================================
def page_admin():
    st.markdown('<div class="section-header">⚙️ Admin / Settings</div>', unsafe_allow_html=True)

    tab_units, tab_tests, tab_assign = st.tabs(["🏭 Manage Units", "🧪 Manage Tests", "🔗 Assign Tests to Units"])

    # ── Tab 1: Units ──────────────────────────────────────────────────────
    with tab_units:

        # ── Existing units table ─────────────────────────────────────────
        st.subheader("Existing Units")
        units_df = get_units()
        if units_df.empty:
            st.info("No units yet — add one below.")
        else:
            st.dataframe(
                units_df[["id", "name", "modality", "manufacturer", "model", "serial_no", "location"]],
                use_container_width=True, hide_index=True,
            )

        st.markdown("---")

        # ── Edit existing unit ───────────────────────────────────────────
        if not units_df.empty:
            st.subheader("✏️ Edit Existing Unit")
            unit_options = units_df["name"].tolist()
            edit_unit_name = st.selectbox("Select unit to edit", unit_options, key="edit_unit_select")
            edit_unit_row  = units_df[units_df["name"] == edit_unit_name].iloc[0]
            edit_unit_id   = int(edit_unit_row["id"])

            MODALITIES = ["LINAC", "CT", "MRI", "PET/CT", "Cobalt", "kV Imaging", "Other"]
            current_modality = edit_unit_row["modality"] if edit_unit_row["modality"] in MODALITIES else "Other"

            with st.form("edit_unit_form"):
                eu1, eu2 = st.columns(2)
                with eu1:
                    e_name     = st.text_input("Unit Name *",   value=edit_unit_row["name"])
                    e_modality = st.selectbox("Modality *", MODALITIES,
                                              index=MODALITIES.index(current_modality))
                    e_mfr      = st.text_input("Manufacturer",  value=edit_unit_row["manufacturer"] or "")
                    e_model    = st.text_input("Model",          value=edit_unit_row["model"] or "")
                with eu2:
                    e_serial   = st.text_input("Serial Number", value=edit_unit_row["serial_no"] or "")
                    e_location = st.text_input("Location",      value=edit_unit_row["location"] or "")
                    e_notes    = st.text_area("Notes",          value=edit_unit_row["notes"] or "", height=80)

                save_edit = st.form_submit_button("💾 Save Changes", use_container_width=True, type="primary")

            if save_edit:
                if not e_name.strip():
                    st.error("Unit Name cannot be empty.")
                else:
                    try:
                        update_unit(
                            edit_unit_id,
                            e_name.strip(), e_modality,
                            e_mfr, e_model, e_serial, e_location, e_notes,
                        )
                        st.success(f"✅ **{e_name}** updated successfully.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error saving changes: {e}")

            st.markdown("---")

        # ── Add new unit ─────────────────────────────────────────────────
        st.subheader("➕ Add New Unit")

        with st.form("add_unit_form", clear_on_submit=True):
            u1, u2 = st.columns(2)
            with u1:
                new_name     = st.text_input("Unit Name *",    placeholder="e.g. Elekta Infinity #3")
                new_modality = st.selectbox("Modality *", ["LINAC", "CT", "MRI", "PET/CT", "Cobalt", "kV Imaging", "Other"])
                new_mfr      = st.text_input("Manufacturer", placeholder="e.g. Varian / Elekta")
                new_model    = st.text_input("Model",        placeholder="e.g. Versa HD")
            with u2:
                new_serial   = st.text_input("Serial Number")
                new_location = st.text_input("Location",  placeholder="e.g. Vault 3")
                new_notes    = st.text_area("Notes", height=80)

            submit_unit = st.form_submit_button("➕ Add Unit", use_container_width=True, type="primary")

        if submit_unit:
            if not new_name.strip():
                st.error("Unit Name is required.")
            else:
                try:
                    add_unit(new_name.strip(), new_modality, new_mfr, new_model, new_serial, new_location, new_notes)
                    st.success(f"✅ Unit **{new_name}** added successfully.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error adding unit: {e}")

    # ── Tab 2: Tests ──────────────────────────────────────────────────────
    with tab_tests:
        st.subheader("Define New Test")

        with st.form("add_test_form", clear_on_submit=True):
            t1, t2 = st.columns(2)

            with t1:
                t_name     = st.text_input("Test Name *",   placeholder="e.g. Daily Output Constancy")
                t_desc     = st.text_area("Description",    height=70, placeholder="What does this test measure?")
                t_dtype    = st.selectbox("Data Type *",    ["float", "boolean", "choice"])
                t_unit_msr = st.text_input("Unit of Measure", placeholder="e.g. %, mm, cGy (leave blank if N/A)")
                t_freq     = st.selectbox("Frequency",      ["Daily", "Weekly", "Monthly", "Annual", "Ad-hoc"])

            with t2:
                t_ref      = st.number_input("Reference Value",  value=0.0, format="%.4f",
                                             help="Expected / baseline value (float tests only)")
                t_tol_lo   = st.number_input("Tolerance Low",    value=-3.0, format="%.4f",
                                             help="Value below this triggers a Tolerance warning")
                t_tol_hi   = st.number_input("Tolerance High",   value=3.0,  format="%.4f",
                                             help="Value above this triggers a Tolerance warning")
                t_act_lo   = st.number_input("Action Low",       value=-5.0, format="%.4f",
                                             help="Value below this triggers an Action alert")
                t_act_hi   = st.number_input("Action High",      value=5.0,  format="%.4f",
                                             help="Value above this triggers an Action alert")
                t_choices  = st.text_input("Choices (CSV)",     placeholder="Option A, Option B, Option C",
                                           help="For 'choice' type tests only — comma-separated list")

            submit_test = st.form_submit_button("➕ Add Test", use_container_width=True, type="primary")

        if submit_test:
            if not t_name.strip():
                st.error("Test Name is required.")
            else:
                try:
                    ref_val = float(t_ref)   if t_dtype == "float" else None
                    tl      = float(t_tol_lo) if t_dtype == "float" else None
                    th      = float(t_tol_hi) if t_dtype == "float" else None
                    al      = float(t_act_lo) if t_dtype == "float" else None
                    ah      = float(t_act_hi) if t_dtype == "float" else None
                    choices = t_choices.strip() if t_dtype == "choice" else None

                    add_test(
                        name=t_name.strip(), data_type=t_dtype, description=t_desc,
                        unit_of_measure=t_unit_msr, reference_value=ref_val,
                        tolerance_low=tl, tolerance_high=th,
                        action_low=al, action_high=ah,
                        choices=choices, frequency=t_freq,
                    )
                    st.success(f"✅ Test **{t_name}** added successfully.")
                except Exception as e:
                    st.error(f"Error adding test: {e}")

        st.markdown("---")
        st.subheader("Existing Tests")
        tests_df = get_tests()
        if not tests_df.empty:
            st.dataframe(
                tests_df[["id", "name", "data_type", "unit_of_measure", "reference_value",
                           "tolerance_low", "tolerance_high", "action_low", "action_high", "frequency"]],
                use_container_width=True, hide_index=True,
            )

    # ── Tab 3: Assign Tests to Units ──────────────────────────────────────
    with tab_assign:
        st.subheader("Assign a Test to a Unit")
        st.caption("Creates a link so the test appears in the QA Entry form for that unit.")

        units_df = get_units()
        tests_df = get_tests()

        if units_df.empty or tests_df.empty:
            st.warning("You need at least one unit and one test before you can create assignments.")
        else:
            with st.form("assign_form", clear_on_submit=True):
                a1, a2 = st.columns(2)
                with a1:
                    sel_unit_name = st.selectbox("Unit", units_df["name"].tolist(), key="assign_unit")
                    sel_unit_id   = int(units_df.loc[units_df["name"] == sel_unit_name, "id"].values[0])
                with a2:
                    sel_test_name = st.selectbox("Test", tests_df["name"].tolist(), key="assign_test")
                    sel_test_id   = int(tests_df.loc[tests_df["name"] == sel_test_name, "id"].values[0])

                submit_assign = st.form_submit_button("🔗 Assign", use_container_width=True, type="primary")

            if submit_assign:
                try:
                    assign_test_to_unit(sel_unit_id, sel_test_id)
                    st.success(f"✅ **{sel_test_name}** is now assigned to **{sel_unit_name}**.")
                except Exception as e:
                    st.error(f"Error creating assignment: {e}")


# ===========================================================================
# Router
# ===========================================================================
if page == "🏥 Dashboard":
    page_dashboard()
elif page == "📋 QA Data Entry":
    page_qa_entry()
elif page == "📈 Trending & Reports":
    page_trending()
elif page == "☢️ TRS-398 Calibration":
    if _HAS_PYLINAC:
        page_trs398()
    else:
        st.error(
            "⚠️ **pylinac is not installed.** "
            "Install it with `pip install pylinac` and restart the app."
        )
elif page == "🔧 Service & Downtime Log":
    page_service_log()
elif page == "⚙️ Admin / Settings":
    page_admin()
