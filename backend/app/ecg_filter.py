"""
ecg_filter.py -- the training notebook's ECG preprocessing, reproduced for
inference without a scipy dependency.

GlucoSentry_D1NAMO_Training.ipynb filters every recording with
`filtfilt(butter(4, [0.5, 40] Hz, "band"))` and then `filtfilt(iirnotch(50 Hz,
Q=30))` at 250 Hz before windowing. The bench ECG firmware does not filter
(it only decimates), so the model would otherwise see a signal it was never
trained on. OnnxRiskModel applies `clean_ecg` to each 30 s window after
resampling to the model's rate.

filtfilt's result is the input filtered with |H|^2 at zero phase. That is
computed here in the frequency domain, from the same pole/zero designs scipy
uses, on a reflection-padded copy so the window edges don't wrap around.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np


def _butter_bandpass_zpk(order: int, low_hz: float, high_hz: float, fs: float):
    """Digital Butterworth band-pass as zeros/poles/gain, the way
    scipy.signal.butter(order, [low, high], "band", fs=fs) designs it:
    analog prototype -> pre-warped lp2bp -> bilinear transform."""
    k = np.arange(-order + 1, order, 2)
    proto = -np.exp(1j * np.pi * k / (2 * order))  # analog low-pass poles, unit cutoff

    fs2 = 2.0 * fs
    w_lo = fs2 * np.tan(np.pi * low_hz / fs)
    w_hi = fs2 * np.tan(np.pi * high_hz / fs)
    bw, w0 = w_hi - w_lo, np.sqrt(w_lo * w_hi)

    # lp2bp: every prototype pole becomes a pair; `order` zeros land at s = 0.
    half = proto * bw / 2
    root = np.sqrt(half ** 2 - w0 ** 2)
    poles_s = np.concatenate([half + root, half - root])
    gain_s = bw ** order

    # Bilinear transform: s = 0 zeros -> z = 1, the zeros at infinity -> z = -1.
    poles_z = (fs2 + poles_s) / (fs2 - poles_s)
    zeros_z = np.concatenate([np.ones(order), -np.ones(order)])
    # The `order` analog zeros at s = 0 contribute fs2 each to the gain.
    gain_z = gain_s * np.real(fs2 ** order / np.prod(fs2 - poles_s))
    return zeros_z, poles_z, gain_z


def _notch_ba(f0_hz: float, q: float, fs: float):
    """scipy.signal.iirnotch(f0, Q, fs) coefficients."""
    w0 = 2 * np.pi * f0_hz / fs
    beta = np.tan(w0 / q / 2)
    gain = 1.0 / (1.0 + beta)
    b = gain * np.array([1.0, -2.0 * np.cos(w0), 1.0])
    a = np.array([1.0, -2.0 * gain * np.cos(w0), 2.0 * gain - 1.0])
    return b, a


def frequency_response(freqs_hz: np.ndarray, fs: float) -> np.ndarray:
    """|H| of one pass (band-pass x notch) at the given frequencies."""
    z = np.exp(1j * 2 * np.pi * np.asarray(freqs_hz, dtype=np.float64) / fs)
    zeros, poles, k = _butter_bandpass_zpk(4, 0.5, 40.0, fs)
    h_bp = k * np.prod(z[:, None] - zeros[None, :], axis=1) / np.prod(z[:, None] - poles[None, :], axis=1)
    b, a = _notch_ba(50.0, 30.0, fs)
    zi = 1.0 / z
    h_notch = (b[0] + b[1] * zi + b[2] * zi ** 2) / (a[0] + a[1] * zi + a[2] * zi ** 2)
    return np.abs(h_bp * h_notch)


@lru_cache(maxsize=8)
def _zero_phase_gain(n: int, fs: float) -> np.ndarray:
    """|H|^2 on the rfft grid of an n-sample signal: forward plus backward
    pass, which is what filtfilt applies."""
    return frequency_response(np.fft.rfftfreq(n, d=1.0 / fs), fs) ** 2


def clean_ecg(x: np.ndarray, fs: float) -> np.ndarray:
    """Zero-phase band-pass (0.5-40 Hz) + 50 Hz notch, matching the notebook."""
    x = np.asarray(x, dtype=np.float64)
    pad = min(len(x) - 1, int(2 * fs))  # 2 s of reflection on each side
    padded = np.concatenate([x[pad:0:-1], x, x[-2:-pad - 2:-1]])
    spectrum = np.fft.rfft(padded) * _zero_phase_gain(len(padded), float(fs))
    return np.fft.irfft(spectrum, n=len(padded))[pad:pad + len(x)]
