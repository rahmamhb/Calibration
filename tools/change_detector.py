#!/usr/bin/env python3
"""
tools/change_detector.py
Pure Page-Hinkley test (Hinkley 1971) — detects upward or downward
shifts in a univariate stream using a true cumulative mean.
No exponential forgetting factor — the mean is the simple running average
of all observations since the last reset.
"""


class PageHinkley:
    """
    Parameters
    ----------
    delta    : float — tolerance margin. Deviations smaller than delta
               are not accumulated. Set to ~half the expected noise std.
               Default: 0.5
    threshold: float — alarm level λ. Fire when PH statistic exceeds this.
               Higher = fewer false alarms but slower detection.
               Default: 5.0
    burn_in  : int   — number of observations before detection is active.
               Used to let the mean stabilize before the test runs.
               Default: 3
    cooldown : int   — windows after a detection where firing is blocked.
               Observations during this window are dropped entirely — the
               mean stays frozen at its post-trigger value so a spike inside
               the blackout can't get averaged away before the test resumes.
               Default: 15
    """

    def __init__(self, delta=0.5, threshold=5.0, burn_in=3, cooldown=15):
        self.delta     = delta
        self.threshold = threshold
        self.burn_in   = burn_in
        self.cooldown  = cooldown
        self.reset()

    def reset(self):
        self._n                = 0
        self._sum              = 0.0   # sum of all values (for cumulative mean)
        self._m_up             = 0.0   # cumulative sum — upward test
        self._m_down           = 0.0   # cumulative sum — downward test
        self._min_up           = 0.0   # running minimum of m_up
        self._min_down         = 0.0   # running minimum of m_down
        self._cooldown_counter = 0

    def update(self, value):
        """
        Feed one new observation.
        Returns True if a change is detected (detector auto-resets).
        Returns False otherwise.
        """
        # During cooldown: baseline frozen at its post-trigger value —
        # observations are dropped entirely so a spike occurring inside the
        # blackout window can't get silently averaged into the new mean
        # before the test resumes.
        if self._cooldown_counter > 0:
            self._cooldown_counter -= 1
            return False

        self._n   += 1
        self._sum += value
        mean       = self._sum / self._n   # true cumulative mean

        # During burn-in: accumulate mean only
        if self._n <= self.burn_in:
            return False

        # Accumulate deviations (upward and downward tests)
        self._m_up   += value - mean - self.delta
        self._m_down += mean  - value - self.delta

        self._min_up   = min(self._min_up,   self._m_up)
        self._min_down = min(self._min_down, self._m_down)

        ph_up   = self._m_up   - self._min_up
        ph_down = self._m_down - self._min_down

        if ph_up > self.threshold or ph_down > self.threshold:
            direction = "up" if ph_up > self.threshold else "down"
            print(f"    [PageHinkley] {direction} — "
                  f"ph_up={ph_up:.2f}  ph_down={ph_down:.2f}  "
                  f"mean={mean:.3f}  value={value:.3f}")
            # Reset — start fresh with current value as first observation
            self.reset()
            self._n                = 1
            self._sum              = value
            self._cooldown_counter = self.cooldown
            return True

        return False
