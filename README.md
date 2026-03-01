# Micro QA

**Micro QA** is a lightweight, purely local Streamlit application designed for radiotherapy and medical physics departments to track linear accelerator Quality Assurance (QA) data without the overhead of heavy web frameworks or external database servers.

It runs entirely locally and stores all data in a single SQLite file (`qa_data.db`).

## Features
- **Dashboard:** At-a-glance view of today's QA status and equipment overview.
- **QA Data Entry:** Fast, single-page data entry with immediate pass/warn/fail feedback based on customizable tolerances.
- **Trending & Reports:** Automatically generated Plotly control charts for all numerical QA metrics.
- **TRS-398 Calibration:** Full IAEA TRS-398 absolute dose dosimetry module powered by [pylinac](https://pylinac.readthedocs.io/), with automated calculation of $k_Q$, recombination, polarity, and FFF volume correction factors.
- **Service & Downtime Log:** Track machine faults, downtime events, and engineer service visits.
- **Admin / Settings:** Easily manage your clinic's devices, customize QA tests, and link tests to specific units.

## Requirements
- Python 3.9+
- The dependencies listed in `requirements.txt`:
  - `streamlit`
  - `pandas`
  - `plotly`
  - `pylinac`

## Quick Start
1. Clone the repository to your local machine:
   ```bash
   git clone https://github.com/your-username/micro-qa.git
   cd micro-qa
   ```
2. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the application:
   ```bash
   streamlit run app.py
   ```
   *The SQLite database (`qa_data.db`) will be automatically created and seeded with dummy data on the first run.*

## Deployment on a Clinic Network (Windows)
If you want to run Micro QA on a central workstation (like a Varian Tbox or a Windows Server) and access it from other computers in the clinic:

1. Copy the code to the host machine.
2. Open **TCP Port 8501** in the Windows Defender Firewall.
3. Use a tool like **NSSM** (Non-Sucking Service Manager) to register the app as a silent background Windows Service:
   ```cmd
   nssm install MicroQAService
   ```
   Set the application path to your Python environment's `streamlit.exe` and the arguments to `run C:\path\to\micro-qa\app.py --server.headless true`.

You can now access the app from any PC in the clinic by navigating to `http://<HOST_IP_ADDRESS>:8501`.

## License
MIT License
