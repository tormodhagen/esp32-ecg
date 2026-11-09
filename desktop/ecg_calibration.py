"""Sine calibration of total analog gain; raw ADC volts, input mV peak-to-peak."""
import numpy as np

def estimate_gain(t, v, frequency_hz, input_mv_pp, positive_half=False):
    t, v = np.asarray(t), np.asarray(v)
    if frequency_hz <= 0 or input_mv_pp <= 0:
        raise ValueError('Frequency and input amplitude must be positive.')
    if len(t) < 100 or not np.all(np.isfinite(t)) or not np.all(np.isfinite(v)):
        raise ValueError('Not enough valid samples.')
    dt = np.diff(t)
    if np.any(dt <= 0) or np.max(dt) > .020:
        raise ValueError('Calibration contains data gaps. Improve the connection and retry.')
    if t[-1]-t[0] < max(5, 5/frequency_hz):
        raise ValueError('Collect at least five seconds and five complete cycles.')
    x = t-t[0]; angle = 2*np.pi*frequency_hz*x
    basis = np.column_stack((np.sin(angle), np.cos(angle), np.ones(len(x)), x-x.mean()))
    coef, *_ = np.linalg.lstsq(basis, v, rcond=None)
    mask = np.ones(len(x), dtype=bool)
    if positive_half:
        # Infer phase from the fundamental, then fit only the central positive lobe.
        # Offset/drift remain free parameters; selection is relative to fitted centre,
        # never to absolute 0 V. Keep a margin from the zero-crossing/clamp transition.
        for _ in range(8):
            amplitude = np.hypot(coef[0], coef[1])
            if amplitude < 1e-9:
                raise ValueError('No usable sinusoidal component.')
            phase_wave = basis[:, :2] @ coef[:2] / amplitude
            new_mask = phase_wave > .2
            if np.count_nonzero(new_mask) < 100:
                raise ValueError('Not enough positive-half samples.')
            coef, *_ = np.linalg.lstsq(basis[new_mask], v[new_mask], rcond=None)
            stable = np.array_equal(mask, new_mask)
            mask = new_mask
            if stable: break
    amplitude = np.hypot(coef[0], coef[1])
    residual = np.sqrt(np.mean((v[mask]-basis[mask]@coef)**2))/max(amplitude/np.sqrt(2), 1e-15)
    if amplitude < .001:
        raise ValueError('Calibration amplitude at ADC is too small for this estimator.')
    if residual > .10:
        raise ValueError('Poor sine fit (>10% residual). Check frequency, clipping of the selected half, noise and settling.')
    gain = 2*amplitude/(input_mv_pp/1000)
    if not .001 <= gain <= 1000000: raise ValueError('Gain is outside the supported range.')
    return float(gain), float(2*amplitude), float(residual)
