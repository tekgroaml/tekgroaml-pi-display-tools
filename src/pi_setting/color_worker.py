"""GTK layer-shell surfaces: one edge-to-edge overlay per selected HDMI output."""
import fcntl
import json
import math
from pathlib import Path
import signal
import socket
import sys
import threading
import time

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell

from .common import UserError, connector_name
from .outputs import outputs
from .touch import TouchTest, TapCycle, TARGETS

COLORS = {'black': (0, 0, 0), 'white': (1, 1, 1), 'red': (1, 0, 0)}


def monitor_for(display, output):
    mode = next((m for m in output['modes'] if m['current']), None)
    if not output['enabled'] or mode is None:
        raise UserError(f"{output['name']} is disabled or has no active mode.")
    width, height = mode['width'], mode['height']
    if output['transform'] in ('90', '270', 'flipped-90', 'flipped-270'):
        width, height = height, width
    expected = (output['position'][0], output['position'][1], round(width / output['scale']), round(height / output['scale']))
    candidates = []
    for index in range(display.get_n_monitors()):
        monitor = display.get_monitor(index)
        rectangle = monitor.get_geometry()
        actual = (rectangle.x, rectangle.y, rectangle.width, rectangle.height)
        if actual == expected:
            candidates.append(monitor)
    if len(candidates) != 1:
        raise UserError(f"{output['name']}: cannot uniquely map the desktop monitor (mirrored layout or stale topology).")
    return candidates[0]


class TestWindow(Gtk.Window):
    def __init__(self, monitor, port, output, state):
        super().__init__(title=f'Pi screen test HDMI{port}')
        self.port, self.output, self.state = port, output, state
        self.touch = TouchTest(state.get('shape', 'round'))
        self.tap_cycle = state.setdefault('_tap_cycle', TapCycle())
        self.set_decorated(False)
        self.set_accept_focus(False)
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, 'pi-setting-test')
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_monitor(self, monitor)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_exclusive_zone(self, -1)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
            GtkLayerShell.set_margin(self, edge, 0)
        area = Gtk.DrawingArea()
        area.add_events(Gdk.EventMask.TOUCH_MASK | Gdk.EventMask.BUTTON_PRESS_MASK |
                        Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        area.connect('touch-event', self.on_touch)
        area.connect('button-press-event', self.on_pointer)
        area.connect('button-release-event', self.on_pointer)
        area.connect('motion-notify-event', self.on_pointer)
        area.connect('draw', self.draw_test)
        self.add(area)
        self.connect('realize', self.hide_pointer)
        self.show_all()

    def hide_pointer(self, *_):
        self.get_window().set_cursor(Gdk.Cursor.new_for_display(self.get_display(), Gdk.CursorType.BLANK_CURSOR))

    def on_touch(self, area, event):
        if self.state['action'] not in ('touch', 'tap-cycle'):
            return True
        kinds = {Gdk.EventType.TOUCH_BEGIN: 'begin', Gdk.EventType.TOUCH_UPDATE: 'update',
                 Gdk.EventType.TOUCH_END: 'end', Gdk.EventType.TOUCH_CANCEL: 'cancel'}
        kind = kinds.get(event.type)
        if kind is not None:
            self.interact(area, kind, event.get_event_sequence(), event.x, event.y, 'native_touch')
        return True

    def interact(self, area, kind, sequence, x, y, source):
        if self.state['action'] == 'tap-cycle':
            previous = self.tap_cycle.color
            self.tap_cycle.event(kind, sequence, source)
            if self.tap_cycle.color != previous:
                area.queue_draw()
        else:
            self.touch.event(kind, sequence, x, y, area.get_allocated_width(),
                             area.get_allocated_height(), source)
            area.queue_draw()

    def on_pointer(self, area, event):
        if self.state['action'] not in ('touch', 'tap-cycle'):
            return True
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 1:
            kind = 'begin'
        elif event.type == Gdk.EventType.BUTTON_RELEASE and event.button == 1:
            kind = 'end'
        elif event.type == Gdk.EventType.MOTION_NOTIFY and event.state & Gdk.ModifierType.BUTTON1_MASK:
            kind = 'update'
        else:
            return True
        self.interact(area, kind, 'pointer', event.x, event.y, 'pointer_or_emulated')
        return True

    def draw_touch(self, context, width, height):
        context.set_source_rgb(.035, .045, .065)
        context.paint()
        context.set_line_width(2)
        context.set_source_rgb(.1, .75, 1)
        for trail in self.touch.trails:
            if not trail:
                continue
            context.move_to(*trail[0])
            for point in trail[1:]:
                context.line_to(*point)
            context.stroke()
        def label(text, x, y, size, color=(1, 1, 1)):
            context.select_font_face('Sans', 0, 1)
            context.set_font_size(size)
            context.set_source_rgb(*color)
            extent = context.text_extents(text)
            context.move_to(x-extent[2]/2-extent[0], y)
            context.show_text(text)
        centers, radius = self.touch.geometry(width, height)
        for index, (tx, ty) in enumerate(centers):
            context.set_source_rgb(*((.1, .8, .3) if index in self.touch.hits else (.9, .55, .1)))
            context.arc(tx, ty, radius, 0, math.tau)
            context.fill()
            label(str(index+1), tx, ty+radius*.3, radius, (0, 0, 0))
        size = max(12, min(width, height)*.032)
        label(f'SCREEN {self.port+1} / HDMI{self.port}', width*.5, height*.32, size)
        label('Tap targets; slide to draw', width*.5, height*.37, size*.85)
        if self.touch.last_input:
            text = 'NATIVE TOUCH' if self.touch.last_input == 'native_touch' else 'POINTER / EMULATED TOUCH'
            label(text, width*.5, height*.41, size*.65)
        label(f'Inputs: {self.touch.count}    Targets: {len(self.touch.hits)}/5',
              width*.5, height*.61, size*.9)
        if self.touch.last:
            x, y = self.touch.last
            label(f'X {x:.0f}    Y {y:.0f}', width*.5, height*.65, size*.85)
            context.set_source_rgb(1, 1, 1)
            context.arc(x, y, 7, 0, math.tau)
            context.stroke()
        bx, by, bw, bh = self.touch.reset_bounds(width, height)
        context.set_source_rgb(.2, .28, .4)
        context.rectangle(bx, by, bw, bh)
        context.fill()
        label('RESET', width*.5, by+bh*.68, size*.85)
        return False

    def draw_test(self, widget, context):
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        state = self.state
        action = state['action']
        if action == 'touch':
            return self.draw_touch(context, width, height)
        if action == 'tap-cycle':
            action = self.tap_cycle.color
        if action == 'cycle':
            index = int((time.monotonic() - state['started']) / state['interval']) % 3
            action = ('black', 'white', 'red')[index]
        if action in COLORS:
            context.set_source_rgb(*COLORS[action])
            context.paint()
            return False
        context.set_source_rgb(0.06, 0.06, 0.06)
        context.paint()
        context.set_line_width(1)
        context.set_source_rgb(0.3, 0.3, 0.3)
        for index in range(1, 10):
            context.move_to(width * index / 10, 0)
            context.line_to(width * index / 10, height)
            context.move_to(0, height * index / 10)
            context.line_to(width, height * index / 10)
        context.stroke()
        context.set_line_width(2)
        context.set_source_rgb(1, 1, 1)
        context.rectangle(1, 1, width-2, height-2)
        context.stroke()
        radius = min(width, height) / 2 - 3
        context.arc(width/2, height/2, radius, 0, math.tau)
        context.stroke()
        context.set_source_rgb(1, 0.8, 0)
        for degrees in range(0, 360, 30):
            angle = math.radians(degrees)
            for r in (radius-12, radius):
                point = (width/2 + r*math.cos(angle), height/2 + r*math.sin(angle))
                (context.move_to if r == radius-12 else context.line_to)(*point)
        context.stroke()
        context.set_source_rgb(0, 1, 0)
        context.move_to(width/2-24, height/2)
        context.line_to(width/2+24, height/2)
        context.move_to(width/2, height/2-24)
        context.line_to(width/2, height/2+24)
        context.stroke()
        context.select_font_face('Sans', 0, 1)
        context.set_font_size(max(12, min(width, height)/30))
        mode = next(m for m in self.output['modes'] if m['current'])
        labels = [(f"SCREEN {self.port+1} / HDMI{self.port}", width/2, height/2-50),
                  (f"{mode['width']} x {mode['height']}", width/2, height/2+60),
                  ('TOP', width/2, height*0.12), ('BOTTOM', width/2, height*0.88),
                  ('L', width*0.1, height/2), ('R', width*0.9, height/2)]
        context.set_source_rgb(1, 1, 1)
        for text, x, y in labels:
            extent = context.text_extents(text)
            context.move_to(x-extent[2]/2, y)
            context.show_text(text)
        return False


class App:
    def __init__(self, runtime):
        self.runtime = runtime
        self.states = {}
        self.windows = {}
        self.topology = None
        self.last_error = None
        self.last_cycle = {}
        self.display = Gdk.Display.get_default()
        if self.display is None or not GtkLayerShell.is_supported():
            raise UserError('The current desktop does not support GTK layer-shell. Use labwc/Wayland.')
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.path = runtime / 'control.sock'
        self.path.unlink(missing_ok=True)
        self.server.bind(str(self.path))
        self.path.chmod(0o600)
        self.server.listen(8)
        self.alive = True
        threading.Thread(target=self.serve, daemon=True).start()
        GLib.timeout_add(100, self.tick)
        GLib.timeout_add(1000, self.refresh)

    def serve(self):
        while self.alive:
            try:
                connection, _ = self.server.accept()
                connection.settimeout(2)
                payload = b''
                while b'\n' not in payload and len(payload) < 8192:
                    block = connection.recv(4096)
                    if not block:
                        break
                    payload += block
                message = json.loads(payload.split(b'\n', 1)[0])
                done = threading.Event()
                result = {}

                def dispatch(message=message, done=done, result=result):
                    try:
                        result.update(self.command(message))
                    except Exception as error:
                        result.update(ok=False, error=str(error))
                    done.set()
                    return False

                GLib.idle_add(dispatch)
                if not done.wait(4):
                    result = {'ok': False, 'error': 'Display command timed out'}
                connection.sendall(json.dumps(result).encode() + b'\n')
                connection.close()
            except (OSError, ValueError) as error:
                print(f'Control socket: {error}', flush=True)

    def command(self, message):
        action = message.get('action')
        if action == 'status':
            return {'ok': True, 'screens': {str(p+1): {'port': p, 'connector': connector_name(p),
                    'action': s['action'], 'interval': s.get('interval'), 'error': self.last_error,
                    **({'touch': self.windows[p].touch.summary()} if s['action'] == 'touch' and p in self.windows else {}),
                    **({'tap_cycle': s['_tap_cycle'].summary()} if s['action'] == 'tap-cycle' else {})}
                    for p, s in self.states.items()}}
        if action not in (*COLORS, 'pattern', 'touch', 'tap-cycle', 'cycle', 'stop'):
            raise UserError('Unknown test command')
        shape = message.get('shape', 'round')
        if action == 'touch' and shape not in ('round', 'rect'):
            raise UserError('Touch shape must be round or rect')
        screen = message.get('screen')
        if screen is not None and screen not in (1, 2):
            raise UserError('Screen must be 1 or 2')
        if action == 'stop':
            for port in list(self.states):
                if screen is None or port == screen-1:
                    self.states.pop(port)
                    self.windows.pop(port).destroy() if port in self.windows else None
            if not self.states:
                GLib.timeout_add(100, self.quit)
            return {'ok': True, 'message': 'Screen test stopped.'}
        interval = float(message.get('interval', 5))
        if not 0.2 <= interval <= 86400:
            raise UserError('Invalid interval')
        available = outputs()
        ports = [screen-1] if screen else [p for p in (0, 1) if available.get(connector_name(p), {}).get('enabled')]
        if not ports:
            raise UserError('No enabled HDMI outputs')
        # Validate all targets first to avoid a partial command on a missing screen.
        for port in ports:
            output = available.get(connector_name(port))
            if output is None:
                raise UserError(f'{connector_name(port)} is not connected')
            monitor_for(self.display, output)
        for port in ports:
            self.states[port] = {'action': action, 'started': time.monotonic(),
                                 'interval': None if action == 'tap-cycle' else interval}
            if action == 'touch':
                self.states[port]['shape'] = shape
            if action == 'tap-cycle':
                self.states[port]['_tap_cycle'] = TapCycle()
        self.rebuild(available)
        return {'ok': True, 'message': f"{action}: screen(s) {', '.join(str(p+1) for p in ports)}"}

    def rebuild(self, available):
        self.last_error = None
        for port in list(self.windows):
            output = available.get(connector_name(port))
            if port not in self.states or not output or not output['enabled']:
                self.windows.pop(port).destroy()
        for port, state in self.states.items():
            output = available.get(connector_name(port))
            if not output or not output['enabled']:
                continue
            try:
                monitor = monitor_for(self.display, output)
                previous = self.windows.get(port)
                if previous is not None and previous.output == output:
                    if previous.state is not state:
                        previous.touch = TouchTest(state.get('shape', 'round'))
                        previous.tap_cycle = state.setdefault('_tap_cycle', TapCycle())
                        previous.state = state
                        previous.queue_draw()
                else:
                    self.windows[port] = TestWindow(monitor, port, output, state)
                    if previous is not None:
                        previous.destroy()
            except UserError as error:
                self.last_error = str(error)
                print(error, flush=True)
        self.topology = json.dumps(available, sort_keys=True)

    def refresh(self):
        try:
            available = outputs()
            if self.topology != json.dumps(available, sort_keys=True):
                self.rebuild(available)
        except Exception as error:
            self.last_error = str(error)
        return True

    def tick(self):
        for port, window in self.windows.items():
            state = self.states[port]
            if state['action'] == 'cycle':
                index = int((time.monotonic()-state['started'])/state['interval']) % 3
                if self.last_cycle.get(port) != index:
                    window.queue_draw()
                    self.last_cycle[port] = index
        return True

    def quit(self, *_):
        self.alive = False
        Gtk.main_quit()
        return False


def main():
    runtime = Path(sys.argv[1])
    with (runtime/'worker.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        app = App(runtime)
        for number in (signal.SIGTERM, signal.SIGINT):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, number, app.quit)
        try:
            Gtk.main()
        finally:
            app.alive = False
            app.server.close()
            app.path.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
