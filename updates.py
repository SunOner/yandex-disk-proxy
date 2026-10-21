"""Bounded, metadata-only change notifications for local browser panels."""

import threading

TOPICS = frozenset(("state", "files", "events", "requests", "operations", "recovery"))


class Updates:
    def __init__(self):
        self.condition = threading.Condition()
        self.revision = 0
        self.changed_at = dict.fromkeys(TOPICS, 0)
        self.closed = False
        self.clients = threading.BoundedSemaphore(12)

    def changed(self, *topics):
        with self.condition:
            valid = TOPICS.intersection(topics)
            if self.closed or not valid:
                return
            self.revision += 1
            for topic in valid:
                self.changed_at[topic] = self.revision
            self.condition.notify_all()

    def wait(self, cursor, topics, timeout=15):
        with self.condition:

            def ready():
                return (
                    self.closed
                    or cursor is None
                    or any(self.changed_at[topic] > cursor for topic in topics)
                )

            self.condition.wait_for(ready, timeout)
            if self.closed:
                return None
            changed = (
                topics
                if cursor is None
                else {topic for topic in topics if self.changed_at[topic] > cursor}
            )
            return {"revision": self.revision, "topics": sorted(changed)}

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
