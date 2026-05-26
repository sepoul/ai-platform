from queue import Queue

from ai_platform.ai.run_context.event_model import RunEvent


class RunContext:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self._events: Queue[RunEvent] = Queue()

    def log(self, event: RunEvent) -> None:
        self._events.put(event)

    def drain_events(self) -> list[RunEvent]:
        events = []
        while not self._events.empty():
            events.append(self._events.get())
        return events
