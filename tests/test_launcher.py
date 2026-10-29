import threading
import uuid

from reeve import launcher
from reeve.tray import TrayApp


def test_second_start_asks_the_running_app_for_its_hub():
    name = f"Local\ReeveTest.{uuid.uuid4().hex}"
    assert launcher.signal(name) is False        # nobody listening yet
    asked = threading.Event()
    launcher.listen_for(name, asked.set)
    assert launcher.signal(name) is True
    assert asked.wait(2)


class _FakeHub:
    def __init__(self, running=True):
        self.running, self.terminated, self.pid = running, False, 0

    def poll(self):
        return None if self.running else 0

    def terminate(self):
        self.terminated, self.running = True, False


def test_quit_closes_the_hub_the_app_opened():
    app = TrayApp.__new__(TrayApp)          # no overlay or tray icon needed
    app._hub = _FakeHub()
    app._close_hub()
    assert app._hub.terminated
    app._hub = _FakeHub(running=False)      # already closed by the user: nothing to do
    app._close_hub()
    assert not app._hub.terminated
