"""
trs398_page.py — Micro QA
============================================================
TRS-398 Absorbed Dose Calibration page.

Wraps pylinac's TRS398Photon and TRS398Electron into a guided
Streamlit form with live results and optional DB logging.

Includes a user-supplied **k_vol_fff** correction factor for
Farmer-type chambers in FFF beams (IAEA TRS-398 §6.5).
For non-Farmer chambers or non-FFF beams it defaults to 1.000.
"""

import warnings
import streamlit as st
import pandas as pd
from datetime import date, datetime

from crud import log_calibration, get_calibration_logs

# ── Chamber lists from pylinac ────────────────────────────────────────────────
# These are used to populate the selectbox and must stay in sync with pylinac.
# We import them lazily inside functions so the page can still load even if
# pylinac is missing (the import guard in app.py will warn the user first).

# Farmer-type chambers are 0.6 cc cylindrical chambers.  The FFF volume
# correction factor (k_vol_fff) is only physically relevant for these.
FARMER_CHAMBERS = {
    "PR-06C/G", "PR06C", "A12",
    "2571", "2581",
    "30001", "30010",
    "30002", "30011",
    "30004", "30012",
    "30006", "30013",
    "FC65-P", "FC65-G",
    "30-751", "30-752",
    "2505", "2505/A", "2505/3, 3A", "2505/3, 3B",
}


def _is_farmer(chamber: str) -> bool:
    """Return True if the chamber model is a Farmer-type chamber."""
    return chamber in FARMER_CHAMBERS


# ===========================================================================
# Helper — pretty results card
# ===========================================================================

def _result_card(label: str, value, fmt: str = ".6f") -> None:
    """Display a single metric inside a styled container."""
    if value is None:
        st.metric(label, "N/A")
    else:
        st.metric(label, f"{value:{fmt}}")


def _show_results(results: dict, k_vol_fff: float) -> None:
    """
    Display the calculated results in a grid of metric cards.
    `results` is a dict of attribute names → values from the pylinac object.
    """
    st.markdown("---")
    st.subheader("📊 Calibration Results")

    # ── Row 1: Correction factors ─────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        _result_card("kQ", results.get("kq"))
    with c2:
        _result_card("k_pol", results.get("k_pol"))
    with c3:
        _result_card("k_s", results.get("k_s"))
    with c4:
        _result_card("k_tp", results.get("k_tp"))
    with c5:
        _result_card("k_vol (FFF)", k_vol_fff)

    # ── Row 2: Corrected reading & dose ───────────────────────────────────
    st.markdown("")
    d1, d2, d3 = st.columns(3)

    m_corr_pylinac = results.get("m_corrected")
    # Apply the FFF volume correction to the corrected reading
    m_corr_final = m_corr_pylinac * k_vol_fff if m_corr_pylinac is not None else None

    dose_zref = results.get("dose_mu_zref")
    dose_zmax = results.get("dose_mu_zmax")

    # Scale dose values by k_vol_fff as well (dose is proportional to M_corrected)
    if k_vol_fff != 1.0:
        dose_zref = dose_zref * k_vol_fff if dose_zref is not None else None
        dose_zmax = dose_zmax * k_vol_fff if dose_zmax is not None else None

    with d1:
        _result_card("M_corrected (nC)", m_corr_final, ".4f")
    with d2:
        _result_card("Dose/MU at z_ref (cGy/MU)", dose_zref, ".4f")
    with d3:
        _result_card("Dose/MU at z_max (cGy/MU)", dose_zmax, ".4f")

    if k_vol_fff != 1.0:
        st.info(
            f"ℹ️ The **FFF volume correction factor k_vol = {k_vol_fff:.4f}** "
            "has been applied to M_corrected and the dose values above."
        )

    # Store adjusted values so the save button can access them
    st.session_state["_trs398_dose_zref"] = dose_zref
    st.session_state["_trs398_dose_zmax"] = dose_zmax
    st.session_state["_trs398_m_corrected"] = m_corr_final


# ===========================================================================
# PHOTON TAB
# ===========================================================================

def _photon_tab() -> None:
    """Render the TRS-398 Photon calibration form and results."""
    from pylinac.calibration.trs398 import TRS398Photon, KQ_PHOTON_CHAMBERS

    chambers = list(KQ_PHOTON_CHAMBERS.keys())

    st.markdown("#### 📝 Measurement Parameters")

    # ── Row 1: general info ───────────────────────────────────────────────
    g1, g2, g3 = st.columns(3)
    with g1:
        institution = st.text_input("Institution", value="", key="ph_inst")
        physicist   = st.text_input("Physicist",   value="", key="ph_phys")
    with g2:
        unit_name    = st.text_input("Unit / Machine", value="", key="ph_unit")
        meas_date    = st.date_input("Measurement Date", value=date.today(), key="ph_date")
    with g3:
        electrometer = st.text_input("Electrometer", value="", key="ph_elec")
        setup        = st.selectbox("Setup", ["SSD", "SAD"], key="ph_setup")

    st.markdown("---")

    # ── Row 2: chamber & beam parameters ──────────────────────────────────
    p1, p2, p3 = st.columns(3)
    with p1:
        chamber     = st.selectbox("Ion Chamber", chambers, index=chambers.index("30013") if "30013" in chambers else 0, key="ph_chamber")
        n_dw        = st.number_input("N_D,w (cGy/nC)", value=5.400, format="%.4f", step=0.001, key="ph_ndw")
        k_elec      = st.number_input("k_elec", value=1.000, format="%.4f", step=0.001, key="ph_kelec",
                                       help="Electrometer calibration factor")
    with p2:
        energy      = st.number_input("Nominal Energy (MV)", min_value=1, max_value=25, value=6, step=1, key="ph_energy")
        tpr2010     = st.number_input("TPR₂₀,₁₀", value=0.672, format="%.4f", step=0.001, key="ph_tpr",
                                       help="Tissue-phantom ratio at 20cm / 10cm depths")
        fff         = st.checkbox("FFF (Flattening Filter Free) beam", value=False, key="ph_fff")
    with p3:
        mu          = st.number_input("Monitor Units (MU)", min_value=1, value=200, step=10, key="ph_mu")
        clinical_pdd = st.number_input("Clinical PDD at z_ref (%)", value=66.4, format="%.2f", step=0.1, key="ph_pdd",
                                        help="Clinical percentage depth dose at the reference depth")
        tissue_corr  = st.number_input("Tissue Correction", value=1.000, format="%.4f", step=0.001, key="ph_tissue",
                                        help="Set to 1.0 for water; use other values if measuring in non-water phantom")

    st.markdown("---")

    # ── Row 3: environmental conditions & voltages ────────────────────────
    e1, e2 = st.columns(2)
    with e1:
        st.markdown("**Environmental Conditions**")
        temp   = st.number_input("Temperature (°C)", value=22.0, format="%.1f", step=0.1, key="ph_temp")
        press  = st.number_input("Pressure (kPa)", value=101.325, format="%.3f", step=0.1, key="ph_press")
    with e2:
        st.markdown("**Voltage Settings**")
        v_ref  = st.number_input("V_reference (V)", value=-300, step=1, key="ph_vref",
                                  help="Reference voltage (sign matters — use negative for negative polarity)")
        v_red  = st.number_input("V_reduced (V)", value=-150, step=1, key="ph_vred",
                                  help="Reduced voltage for ion recombination. V_ref/V_red ratio must be 2, 2.5, 3, 3.5, 4, or 5")

    st.markdown("---")

    # ── Row 4: electrometer readings ──────────────────────────────────────
    st.markdown("**Electrometer Readings (nC)** — enter up to 3 readings each")
    r1, r2, r3 = st.columns(3)
    with r1:
        st.caption("M_reference (at V_ref)")
        m_ref1 = st.number_input("M_ref 1", value=20.10, format="%.4f", key="ph_mr1")
        m_ref2 = st.number_input("M_ref 2", value=20.20, format="%.4f", key="ph_mr2")
        m_ref3 = st.number_input("M_ref 3", value=20.00, format="%.4f", key="ph_mr3")
    with r2:
        st.caption("M_reduced (at V_red)")
        m_red1 = st.number_input("M_red 1", value=19.90, format="%.4f", key="ph_md1")
        m_red2 = st.number_input("M_red 2", value=19.80, format="%.4f", key="ph_md2")
        m_red3 = st.number_input("M_red 3", value=20.00, format="%.4f", key="ph_md3")
    with r3:
        st.caption("M_opposite (at +V_ref)")
        m_opp1 = st.number_input("M_opp 1", value=20.00, format="%.4f", key="ph_mo1")
        m_opp2 = st.number_input("M_opp 2", value=20.10, format="%.4f", key="ph_mo2")
        m_opp3 = st.number_input("M_opp 3", value=19.90, format="%.4f", key="ph_mo3")

    st.markdown("---")

    # ── FFF Volume Correction (Farmer chamber specific) ───────────────────
    st.markdown("**FFF Volume Correction Factor (k_vol)**")
    is_farmer = _is_farmer(chamber)

    if fff and is_farmer:
        st.caption(
            "Per IAEA TRS-398, Farmer-type chambers may require a chamber-specific "
            "volume correction factor when measuring FFF beams due to the non-uniform "
            "beam profile across the chamber volume. Enter the appropriate k_vol below."
        )
        k_vol_fff = st.number_input(
            "k_vol (FFF Farmer correction)",
            value=1.000, min_value=0.900, max_value=1.100,
            format="%.4f", step=0.001, key="ph_kvol",
            help="Chamber-specific volume correction for Farmer chambers in FFF beams. "
                 "Consult your chamber manufacturer or IAEA TRS-398 for the appropriate value."
        )
    else:
        k_vol_fff = 1.000
        if fff and not is_farmer:
            st.info("ℹ️ k_vol = 1.000 — The selected chamber is not a Farmer-type; no FFF volume correction needed.")
        elif not fff:
            st.info("ℹ️ k_vol = 1.000 — FFF is not selected; volume correction is not applicable.")

    st.markdown("---")

    notes = st.text_area("Notes", key="ph_notes", placeholder="Optional comments…", height=70)

    # ── Calculate button ──────────────────────────────────────────────────
    if st.button("▶  Calculate", key="ph_calc", use_container_width=True, type="primary"):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                t = TRS398Photon(
                    institution      = institution,
                    physicist        = physicist,
                    unit             = unit_name,
                    measurement_date = meas_date.strftime("%Y-%m-%d"),
                    electrometer     = electrometer,
                    setup            = setup,
                    chamber          = chamber,
                    n_dw             = float(n_dw),
                    mu               = int(mu),
                    tpr2010          = float(tpr2010),
                    energy           = int(energy),
                    fff              = bool(fff),
                    press            = float(press),
                    temp             = float(temp),
                    voltage_reference = int(v_ref),
                    voltage_reduced   = int(v_red),
                    m_reference       = (m_ref1, m_ref2, m_ref3),
                    m_reduced         = (m_red1, m_red2, m_red3),
                    m_opposite        = (m_opp1, m_opp2, m_opp3),
                    k_elec            = float(k_elec),
                    clinical_pdd_zref = float(clinical_pdd),
                    tissue_correction = float(tissue_corr),
                )

            results = {
                "kq": t.kq, "k_pol": t.k_pol, "k_s": t.k_s, "k_tp": t.k_tp,
                "m_corrected": t.m_corrected,
                "dose_mu_zref": t.dose_mu_zref, "dose_mu_zmax": t.dose_mu_zmax,
            }

            _show_results(results, k_vol_fff)

            # Store in session for the save button
            st.session_state["_trs398_last"] = {
                "beam_type": "photon",
                "unit_name": unit_name,
                "institution": institution,
                "physicist": physicist,
                "chamber": chamber,
                "energy": str(energy),
                "setup": setup,
                "n_dw": float(n_dw),
                "k_vol_fff": k_vol_fff,
                "notes": notes,
                "date": meas_date.isoformat(),
                **results,
            }

        except (ValueError, TypeError) as exc:
            st.error(f"⚠️ Calculation error: {exc}")
        except Exception as exc:
            st.error(f"🚨 Unexpected error: {exc}")

    # ── Save button (appears only when results are available) ─────────────
    if "_trs398_last" in st.session_state and st.session_state["_trs398_last"].get("beam_type") == "photon":
        st.markdown("---")
        if st.button("💾 Save to Calibration Log", key="ph_save", use_container_width=True):
            data = st.session_state["_trs398_last"]
            log_calibration(
                beam_type    = data["beam_type"],
                unit_name    = data["unit_name"],
                institution  = data["institution"],
                physicist    = data["physicist"],
                chamber      = data["chamber"],
                energy       = data["energy"],
                setup        = data["setup"],
                n_dw         = data["n_dw"],
                kq           = data.get("kq"),
                k_pol        = data.get("k_pol"),
                k_s          = data.get("k_s"),
                k_tp         = data.get("k_tp"),
                k_vol_fff    = data.get("k_vol_fff"),
                m_corrected  = st.session_state.get("_trs398_m_corrected"),
                dose_mu_zref = st.session_state.get("_trs398_dose_zref"),
                dose_mu_zmax = st.session_state.get("_trs398_dose_zmax"),
                notes        = data.get("notes", ""),
                performed_at = data.get("date"),
            )
            st.success("✅ Calibration result saved to log.")


# ===========================================================================
# ELECTRON TAB
# ===========================================================================

def _electron_tab() -> None:
    """Render the TRS-398 Electron calibration form and results."""
    from pylinac.calibration.trs398 import TRS398Electron, KQ_ELECTRON_CHAMBERS

    chambers = list(KQ_ELECTRON_CHAMBERS.keys())

    st.markdown("#### 📝 Measurement Parameters")

    # ── Row 1: general info ───────────────────────────────────────────────
    g1, g2, g3 = st.columns(3)
    with g1:
        institution = st.text_input("Institution", value="", key="el_inst")
        physicist   = st.text_input("Physicist",   value="", key="el_phys")
    with g2:
        unit_name    = st.text_input("Unit / Machine", value="", key="el_unit")
        meas_date    = st.date_input("Measurement Date", value=date.today(), key="el_date")
    with g3:
        electrometer = st.text_input("Electrometer", value="", key="el_elec_name")
        energy_str   = st.text_input("Energy (e.g. '9 MeV')", value="9 MeV", key="el_energy")

    st.markdown("---")

    # ── Row 2: chamber & beam parameters ──────────────────────────────────
    p1, p2, p3 = st.columns(3)
    with p1:
        chamber     = st.selectbox("Ion Chamber", chambers, index=chambers.index("30013") if "30013" in chambers else 0, key="el_chamber")
        n_dw        = st.number_input("N_D,w (cGy/nC)", value=5.400, format="%.4f", step=0.001, key="el_ndw")
        k_elec      = st.number_input("k_elec", value=1.000, format="%.4f", step=0.001, key="el_kelec",
                                       help="Electrometer calibration factor")
    with p2:
        cone        = st.text_input("Cone / Applicator", value="15x15", key="el_cone",
                                     help="Applicator size used, e.g. '10x10', '15x15'")
        i_50        = st.number_input("I₅₀ (cm)", value=3.60, format="%.2f", step=0.01, key="el_i50",
                                       help="Depth of 50% ionisation in water (cm)")
        clinical_pdd = st.number_input("Clinical PDD at z_ref (%)", value=99.0, format="%.2f",
                                        step=0.1, key="el_pdd")
    with p3:
        mu          = st.number_input("Monitor Units (MU)", min_value=1, value=200, step=10, key="el_mu")
        tissue_corr = st.number_input("Tissue Correction", value=1.000, format="%.4f", step=0.001, key="el_tissue",
                                       help="Set to 1.0 for water")

    st.markdown("---")

    # ── Row 3: environmental conditions & voltages ────────────────────────
    e1, e2 = st.columns(2)
    with e1:
        st.markdown("**Environmental Conditions**")
        temp   = st.number_input("Temperature (°C)", value=22.0, format="%.1f", step=0.1, key="el_temp")
        press  = st.number_input("Pressure (kPa)", value=101.325, format="%.3f", step=0.1, key="el_press")
    with e2:
        st.markdown("**Voltage Settings**")
        v_ref  = st.number_input("V_reference (V)", value=-300, step=1, key="el_vref")
        v_red  = st.number_input("V_reduced (V)", value=-150, step=1, key="el_vred")

    st.markdown("---")

    # ── Row 4: electrometer readings ──────────────────────────────────────
    st.markdown("**Electrometer Readings (nC)** — enter up to 3 readings each")
    r1, r2, r3 = st.columns(3)
    with r1:
        st.caption("M_reference")
        m_ref1 = st.number_input("M_ref 1", value=20.10, format="%.4f", key="el_mr1")
        m_ref2 = st.number_input("M_ref 2", value=20.20, format="%.4f", key="el_mr2")
        m_ref3 = st.number_input("M_ref 3", value=20.00, format="%.4f", key="el_mr3")
    with r2:
        st.caption("M_reduced")
        m_red1 = st.number_input("M_red 1", value=19.90, format="%.4f", key="el_md1")
        m_red2 = st.number_input("M_red 2", value=19.80, format="%.4f", key="el_md2")
        m_red3 = st.number_input("M_red 3", value=20.00, format="%.4f", key="el_md3")
    with r3:
        st.caption("M_opposite")
        m_opp1 = st.number_input("M_opp 1", value=20.00, format="%.4f", key="el_mo1")
        m_opp2 = st.number_input("M_opp 2", value=20.10, format="%.4f", key="el_mo2")
        m_opp3 = st.number_input("M_opp 3", value=19.90, format="%.4f", key="el_mo3")

    st.markdown("---")

    notes = st.text_area("Notes", key="el_notes", placeholder="Optional comments…", height=70)

    # ── Calculate button ──────────────────────────────────────────────────
    if st.button("▶  Calculate", key="el_calc", use_container_width=True, type="primary"):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                t = TRS398Electron(
                    institution      = institution,
                    physicist        = physicist,
                    unit             = unit_name,
                    measurement_date = meas_date.strftime("%Y-%m-%d"),
                    electrometer     = electrometer,
                    energy           = energy_str,
                    cone             = cone,
                    chamber          = chamber,
                    n_dw             = float(n_dw),
                    mu               = int(mu),
                    i_50             = float(i_50),
                    press            = float(press),
                    temp             = float(temp),
                    voltage_reference = int(v_ref),
                    voltage_reduced   = int(v_red),
                    m_reference       = (m_ref1, m_ref2, m_ref3),
                    m_reduced         = (m_red1, m_red2, m_red3),
                    m_opposite        = (m_opp1, m_opp2, m_opp3),
                    k_elec            = float(k_elec),
                    clinical_pdd_zref = float(clinical_pdd),
                    tissue_correction = float(tissue_corr),
                )

            results = {
                "kq": t.kq, "k_pol": t.k_pol, "k_s": t.k_s, "k_tp": t.k_tp,
                "m_corrected": t.m_corrected,
                "dose_mu_zref": t.dose_mu_zref, "dose_mu_zmax": t.dose_mu_zmax,
            }

            # Electron beams: k_vol_fff is always 1.0 (FFF is a photon concept)
            _show_results(results, k_vol_fff=1.0)

            st.session_state["_trs398_last"] = {
                "beam_type": "electron",
                "unit_name": unit_name,
                "institution": institution,
                "physicist": physicist,
                "chamber": chamber,
                "energy": energy_str,
                "setup": "SSD",
                "n_dw": float(n_dw),
                "k_vol_fff": 1.0,
                "notes": notes,
                "date": meas_date.isoformat(),
                **results,
            }

        except (ValueError, TypeError) as exc:
            st.error(f"⚠️ Calculation error: {exc}")
        except Exception as exc:
            st.error(f"🚨 Unexpected error: {exc}")

    # ── Save button ───────────────────────────────────────────────────────
    if "_trs398_last" in st.session_state and st.session_state["_trs398_last"].get("beam_type") == "electron":
        st.markdown("---")
        if st.button("💾 Save to Calibration Log", key="el_save", use_container_width=True):
            data = st.session_state["_trs398_last"]
            log_calibration(
                beam_type    = data["beam_type"],
                unit_name    = data["unit_name"],
                institution  = data["institution"],
                physicist    = data["physicist"],
                chamber      = data["chamber"],
                energy       = data["energy"],
                setup        = data.get("setup", "SSD"),
                n_dw         = data["n_dw"],
                kq           = data.get("kq"),
                k_pol        = data.get("k_pol"),
                k_s          = data.get("k_s"),
                k_tp         = data.get("k_tp"),
                k_vol_fff    = data.get("k_vol_fff", 1.0),
                m_corrected  = st.session_state.get("_trs398_m_corrected"),
                dose_mu_zref = st.session_state.get("_trs398_dose_zref"),
                dose_mu_zmax = st.session_state.get("_trs398_dose_zmax"),
                notes        = data.get("notes", ""),
                performed_at = data.get("date"),
            )
            st.success("✅ Calibration result saved to log.")


# ===========================================================================
# CALIBRATION LOG HISTORY TAB
# ===========================================================================

def _history_tab() -> None:
    """Display all saved calibration results."""
    st.subheader("📒 Calibration Log History")

    logs = get_calibration_logs()
    if logs.empty:
        st.info("No calibration records saved yet. Run a calculation and click 💾 Save.")
        return

    display_cols = [
        "performed_at", "beam_type", "unit_name", "chamber", "energy",
        "kq", "k_pol", "k_s", "k_tp", "k_vol_fff",
        "m_corrected", "dose_mu_zref", "dose_mu_zmax",
        "physicist", "notes",
    ]
    # Only show columns that exist
    available = [c for c in display_cols if c in logs.columns]
    st.dataframe(logs[available], use_container_width=True, hide_index=True)

    csv = logs.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download Calibration Log CSV",
        data=csv,
        file_name=f"trs398_calibration_log_{date.today()}.csv",
        mime="text/csv",
    )


# ===========================================================================
# PAGE ENTRY POINT (called from app.py router)
# ===========================================================================

def page_trs398() -> None:
    """Main page function for the TRS-398 Calibration module."""
    st.markdown(
        '<div class="section-header">☢️ TRS-398 Absorbed Dose Calibration</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "IAEA TRS-398 protocol — absolute dose determination for photon and electron beams. "
        "Powered by [pylinac](https://pylinac.readthedocs.io/)."
    )

    tab_photon, tab_electron, tab_history = st.tabs([
        "☀️ Photon Beam",
        "⚡ Electron Beam",
        "📒 Calibration Log",
    ])

    with tab_photon:
        _photon_tab()

    with tab_electron:
        _electron_tab()

    with tab_history:
        _history_tab()
