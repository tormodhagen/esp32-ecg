"""Experimental QRS-energy detector. Not a clinical rhythm classifier."""
import numpy as np
from scipy import signal

def analyze(t, v):
    """Detect within continuous sections; never calculate RR across missing data."""
    t, v = np.asarray(t), np.asarray(v)
    if len(t) < 100 or t[-1]-t[0] < 1:
        return None, np.array([]), 'Collecting samples'
    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(v)) or np.any(np.diff(t) <= 0):
        return None, np.array([]), 'Invalid samples or timestamps'
    cuts = np.r_[0, np.flatnonzero(np.diff(t) > .020)+1, len(t)]
    groups, intervals = [], []
    for start, stop in zip(cuts[:-1], cuts[1:]):
        _, beats, _ = _analyze_continuous(t[start:stop], v[start:stop])
        if len(beats): groups.append(beats)
        if len(beats) > 1: intervals.extend(np.diff(beats).tolist())
    beats = np.concatenate(groups) if groups else np.array([])
    gap_note = ' · gaps excluded' if len(cuts) > 2 else ''
    if len(intervals) < 3 or not len(beats) or t[-1]-beats[-1] > 2.5:
        return None, beats, 'Waiting for enough continuous beat intervals'+gap_note
    rr = np.asarray(intervals[-8:])
    if np.any((rr < .30) | (rr > 2.0)):
        return None, beats, 'Uncertain beat detection'+gap_note
    med = np.median(rr)
    if np.median(abs(rr-med))/med > .20:
        return None, beats, 'Large interval variation — BPM hidden'+gap_note
    return float(60/med), beats, 'BPM estimate · continuous intervals only'+gap_note

def _analyze_continuous(t, v):
    t, v = np.asarray(t), np.asarray(v)
    if len(t) < 100 or t[-1] - t[0] < .85:
        return None, np.array([]), 'Collecting samples'
    dt = np.diff(t)
    if np.any(dt <= 0) or np.max(dt) > .020:
        return None, np.array([]), 'Data gap — waiting for continuous samples'
    fs = 1 / np.median(dt)
    if not 100 < fs < 3000:
        return None, np.array([]), 'Unexpected sample rate'
    # Uniform grid removes small interrupt timestamp jitter. No long gaps interpolated.
    u = np.arange(t[0], t[-1], 1 / fs)
    y = np.interp(u, t, v)
    if np.ptp(y) < .001:
        return None, np.array([]), 'Signal too small'
    q = signal.sosfiltfilt(signal.butter(3, [8, 25], fs=fs, btype='bandpass', output='sos'), y)
    energy = np.convolve(q*q, np.ones(max(1, int(.080*fs))) / max(1, int(.080*fs)), 'same')
    core = energy[(u > u[0]+.4) & (u < u[-1]-.4)]
    base, top = np.percentile(core, [30, 99])
    if top - base < 1e-10:
        return None, np.array([]), 'No clear beats'
    p, _ = signal.find_peaks(energy, distance=int(.30*fs), height=base+.30*(top-base), prominence=.20*(top-base))
    p = p[(u[p] > u[0]+.4) & (u[p] < u[-1]-.25)]
    beats = u[p]
    if len(beats) < 4 or u[-1]-beats[-1] > 2.5:
        return None, beats, 'No stable beat detection'
    rr = np.diff(beats)[-8:]
    if np.any((rr < .30) | (rr > 2.0)):
        return None, beats, 'Uncertain beat detection'
    med = np.median(rr)
    if np.median(abs(rr-med))/med > .20:
        return None, beats, 'Large interval variation — BPM hidden'
    return float(60/med), beats, 'BPM estimate · median of up to 8 intervals'

def display_filter(t, v):
    fs = 1 / np.median(np.diff(t))
    return signal.sosfiltfilt(signal.butter(3, [.5, 40], fs=fs, btype='bandpass', output='sos'), v)

class Decoder:
    """Unsigned counter wrapping and board reset handling."""
    def __init__(self):
        self.prev_seq = self.prev_us = None
        self.seconds = 0.
    def feed(self, line):
        parts = line.strip().split(',')
        if len(parts) != 4 or parts[0] != 'E': return None
        seq, us, raw = map(int, parts[1:])
        if not (0 <= seq < 2**32 and 0 <= us < 2**32 and -32768 <= raw <= 32767):
            raise ValueError('Out of range')
        reset, lost = False, 0
        if self.prev_seq is not None:
            ds = (seq-self.prev_seq) & 0xffffffff
            du = (us-self.prev_us) & 0xffffffff
            if ds == 0: return None
            if ds > 2**31 or du > 2**31:
                reset = True
                self.seconds += .001
            else:
                self.seconds += du*1e-6
                lost = ds-1
        self.prev_seq, self.prev_us = seq, us
        return (self.seconds, raw*.000125, seq, us, raw, lost, reset)
