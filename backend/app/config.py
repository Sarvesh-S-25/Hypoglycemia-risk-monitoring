"""
Central configuration for GlucoSentry backend.

Every tunable number in the system lives here, per AGENTS.md: "no magic numbers
in logic files." Controller thresholds are provisional (see UPDATES.md open
questions) and will need recalibration once the real ONNX model's score
distribution is known -- that recalibration should only ever touch this file.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Data source -------------------------------------------------------
    # simulator: synthetic data only, no hardware needed.
    # serial: real ESP32 over its USB cable (docs/API_CONTRACT.md section 2.4).
    # ble: real ESP32 hardware only, no fallback.
    # auto: try BLE, fall back to simulator after GS_BLE_SCAN_TIMEOUT_S.
    gs_source: str = "simulator"
    gs_ble_scan_timeout_s: float = 8.0

    # --- USB serial source (GS_SOURCE=serial) --------------------------------
    gs_serial_port: str = ""           # empty auto-detects /dev/ttyACM* then /dev/ttyUSB*
    gs_serial_baud: int = 921600       # must match the firmware's Serial.begin()
    serial_device_rate_hz: int = 250   # firmware's ECG sample rate
    serial_mv_per_lsb: float = 0.125   # ADS1115 at +-4.096 V; converts mV back to ADC counts
    serial_reconnect_s: float = 2.0    # wait between attempts when the port is missing
    # Std-dev of |acceleration| over one window above which the window is
    # rejected as motion artifact (SRD 3.1). Provisional: sitting still measures
    # ~0.05 m/s^2, deliberate arm movement several m/s^2.
    serial_motion_sqi_threshold_ms2: float = 1.0

    # --- Persistence ---------------------------------------------------------
    gs_db_path: str = "./data/glucosentry.db"

    # --- Simulator / demo endpoints -----------------------------------------
    gs_enable_sim: bool = True

    # --- Inference -----------------------------------------------------------
    # Empty string selects StubRiskModel (heuristic, no onnxruntime dependency
    # required at runtime). Set to a .onnx path to serve the real trained model.
    # This is the STARTUP default only -- POST /api/model/upload and
    # POST /api/model/select (docs/API_CONTRACT.md) let a model be swapped at
    # runtime from the frontend's Model page, and that runtime selection is
    # persisted to gs_model_selection_path so it survives a backend restart
    # without needing this env var edited by hand.
    gs_model_path: str = ""
    gs_models_dir: str = "./models"
    gs_model_selection_path: str = "./data/model_selection.txt"
    gs_max_model_upload_mb: int = 200

    # --- CORS ------------------------------------------------------------------
    gs_cors_origin: str = "http://localhost:5173"

    # --- BLE GATT UUIDs (placeholders until firmware bring-up fixes them) ---
    # See docs/API_CONTRACT.md section 2. Firmware changes these constants only;
    # no other file should hard-code a UUID.
    # Silence on an open BLE link longer than this is treated as a lost link
    # (firmware notifies once a second).
    ble_stall_timeout_s: float = 5.0

    ble_primary_service_uuid: str = "0000a000-0000-1000-8000-00805f9b34fb"
    ble_char_ecg_data: str = "0000a001-0000-1000-8000-00805f9b34fb"
    ble_char_sqi_flag: str = "0000a002-0000-1000-8000-00805f9b34fb"
    ble_char_device_status: str = "0000a003-0000-1000-8000-00805f9b34fb"
    ble_char_controller_cmd: str = "0000a004-0000-1000-8000-00805f9b34fb"
    ble_char_alert_cmd: str = "0000a005-0000-1000-8000-00805f9b34fb"
    ble_char_aux_wake_cmd: str = "0000a006-0000-1000-8000-00805f9b34fb"

    ble_aux_service_uuid: str = "0000b000-0000-1000-8000-00805f9b34fb"
    ble_char_aux_wake: str = "0000b001-0000-1000-8000-00805f9b34fb"
    ble_char_foot_temp_result: str = "0000b002-0000-1000-8000-00805f9b34fb"

    # --- Controller thresholds (SRD 4.4, docs/PLAN.md section 4) ------------
    # Provisional until the real model's score distribution is known.
    risk_low: float = 0.30
    risk_elevated: float = 0.55
    risk_alert: float = 0.75
    confirm_windows: int = 3          # consecutive Verify windows above risk_alert before firing
    alert_cooldown_s: float = 300.0   # no re-fire within this period unless risk drops and returns
    battery_eco_pct: int = 25         # below this, prefer Eco when risk permits
    battery_aux_min: int = 15         # below this, refuse an auxiliary wake
    sqi_stable_window: int = 5        # consecutive accepted windows required for "SQI stable"
    watch_trend_window: int = 3       # windows examined for a rising-risk trend

    # --- Foot-check scheduler (SRD 4.4) --------------------------------------
    foot_check_normal_interval_s: float = 24 * 3600.0
    foot_check_elevated_interval_s: float = 8 * 3600.0
    foot_check_invalid_retry_s: float = 1 * 3600.0
    foot_check_elevated_threshold_c: float = 2.2  # IWGDF reference threshold, background not diagnostic
    foot_check_eta_s: int = 6  # placeholder estimate for wake-to-result latency; unmeasured on real hw

    # --- Sampling ------------------------------------------------------------
    ecg_sample_rate_hz: int = 100  # decimated rate per SRD 3.1; on-device rate is 250 Hz

    # --- Signal normalization --------------------------------------------------
    # Fixed-reference divisor used to scale raw ADC-count samples before
    # inference, instead of per-window z-score normalization. Per-window
    # normalization divides by that window's own standard deviation, which
    # makes the result scale-invariant to the window's amplitude -- exactly
    # the signal an amplitude excursion (e.g. a real QRS anomaly, or the
    # simulator's induced spike) needs to show up as. This value is a
    # placeholder calibrated against the simulator's synthetic scale; it must
    # be recalibrated once real ADS1115 counts are available (see
    # UPDATES.md open question 3, alongside the ONNX input shape).
    ecg_normalize_scale: float = 1000.0

    # --- Heart rate (display only; app/heart_rate.py) -----------------------
    hr_window_s: float = 8.0         # seconds of consecutive accepted ECG per estimate
    hr_baseline_s: float = 0.2       # moving-average baseline removal width
    hr_peak_fraction: float = 0.6    # R-peak threshold, fraction of the window's max
    # R-peaks must stand this far above the signal's median absolute deviation.
    # Gaussian noise alone reaches ~5x over a few seconds; real ECG R-waves sit
    # well above 10x because most of a beat is near baseline.
    hr_min_peak_to_mad: float = 8.0
    hr_min_bpm: float = 30.0         # outside this range the estimate is reported as null
    hr_max_bpm: float = 220.0        # also sets the refractory period between peaks

    # --- WebSocket -----------------------------------------------------------
    status_push_min_interval_s: float = 1.0  # throttle unchanged-status frames

    @property
    def db_path(self) -> Path:
        p = Path(self.gs_db_path)
        if not p.is_absolute():
            p = BACKEND_ROOT / p
        return p

    @property
    def models_dir(self) -> Path:
        p = Path(self.gs_models_dir)
        if not p.is_absolute():
            p = BACKEND_ROOT / p
        return p

    @property
    def model_selection_path(self) -> Path:
        p = Path(self.gs_model_selection_path)
        if not p.is_absolute():
            p = BACKEND_ROOT / p
        return p


settings = Settings()
