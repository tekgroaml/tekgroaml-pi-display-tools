"""Touch-test state, independent of GTK and physical input devices."""
import math

TARGETS = ((0.5, 0.5), (0.5, 0.18), (0.82, 0.5), (0.5, 0.82), (0.18, 0.5))


class TapCycle:
    """One color change per contact gesture, with no timer or drawn overlays."""
    colors = ('black', 'white', 'red')

    def __init__(self):
        self.switches = 0
        self.active = set()
        self.input_counts = {'native_touch': 0, 'pointer_or_emulated': 0}
        self.last_input = None

    @property
    def color(self):
        return self.colors[self.switches % len(self.colors)]

    def event(self, kind, sequence, source='native_touch'):
        key = (source, sequence)
        if kind == 'begin':
            # A held finger, drag, duplicate down or extra concurrent finger must
            # not make colors race. All contacts must lift before the next tap.
            if not self.active:
                self.switches += 1
                self.input_counts[source] += 1
                self.last_input = source
            self.active.add(key)
        elif kind in ('end', 'cancel'):
            self.active.discard(key)

    def summary(self):
        return {'color': self.color, 'switches': self.switches,
                'input_counts': dict(self.input_counts), 'last_input': self.last_input}


class TouchTest:
    def __init__(self):
        self.count = 0
        self.hits = set()
        self.last = None
        self.trails = []
        self.active = {}
        self.input_counts = {'native_touch': 0, 'pointer_or_emulated': 0}
        self.last_input = None

    @staticmethod
    def reset_bounds(width, height):
        return (width * .37, height * .68, width * .26, height * .065)

    def event(self, kind, sequence, x, y, width, height, source='native_touch'):
        if kind == 'begin':
            bx, by, bw, bh = self.reset_bounds(width, height)
            if bx <= x <= bx+bw and by <= y <= by+bh:
                self.__init__()
                return
            self.count += 1
            self.input_counts[source] += 1
            self.last_input = source
            for index, (tx, ty) in enumerate(TARGETS):
                if math.hypot(x-tx*width, y-ty*height) <= min(width, height)*.06:
                    self.hits.add(index)
            self.trails.append([(x, y)])
            self.active[sequence] = self.trails[-1]
        elif kind == 'update' and sequence in self.active:
            self.active[sequence].append((x, y))
            self.active[sequence][:] = self.active[sequence][-500:]
        elif kind in ('end', 'cancel'):
            self.active.pop(sequence, None)
        if kind != 'cancel':
            self.last = (x, y)
        self.trails[:] = self.trails[-40:]

    def summary(self):
        return {'touches': self.count, 'targets_hit': len(self.hits), 'targets_total': len(TARGETS),
                'last_position': list(self.last) if self.last else None,
                'input_counts': dict(self.input_counts), 'last_input': self.last_input}
