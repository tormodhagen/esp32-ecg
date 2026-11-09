"""Run: python -m unittest test_signal.py"""
import unittest
import numpy as np
from ecg_signal import Decoder, analyze

class SignalTests(unittest.TestCase):
    def test_polarity_and_large_t_wave(self):
        t = np.arange(0, 12, 1/860)
        v = np.zeros(len(t))
        for beat in np.arange(.5, 12, .8):
            v += .15*np.exp(-((t-beat)/.012)**2) + .10*np.exp(-((t-beat-.25)/.08)**2)
        for sign in [1, -1]:
            bpm, _, _ = analyze(t, 2.15+sign*v)
            self.assertIsNotNone(bpm)
            self.assertAlmostEqual(bpm, 75, delta=1)
    def test_flatline_and_gap(self):
        t = np.arange(0, 12, 1/860)
        self.assertIsNone(analyze(t, np.full(len(t), 2.15))[0])
        t[len(t)//2:] += .1
        self.assertIsNone(analyze(t, np.sin(t))[0])
    def test_counter_wrap_loss_and_reset(self):
        d = Decoder()
        d.feed('E,4294967295,4294967000,17000')
        r = d.feed('E,0,864,17001')
        self.assertAlmostEqual(r[0], .001160)
        self.assertEqual(r[5], 0); self.assertFalse(r[6])
        self.assertEqual(d.feed('E,3,4352,17002')[5], 2)
        self.assertTrue(d.feed('E,1,1200,17002')[6])

if __name__ == '__main__': unittest.main()
