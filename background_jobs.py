"""Bounded, cancellable workers for short-lived editor and gallery operations."""
from collections import deque
from threading import Condition, Thread
from types import SimpleNamespace


class BackgroundJobs:
    def __init__(self, dispatch, workers=4, max_pending=64):
        self.dispatch = dispatch
        self.workers = workers
        self.max_pending = max_pending
        self.condition = Condition()
        self.pending = deque()
        self.jobs = {}
        self.started = False

    @staticmethod
    def clear(job):
        job.work = job.done = job.failed = job.result = None

    def submit(self, work, done, failed, scope):
        with self.condition:
            if len(self.pending) >= self.max_pending:
                raise RuntimeError('Demasiadas tareas pendientes. Espera a que terminen las actuales.')
            job = SimpleNamespace(work=work, done=done, failed=failed, scope=scope,
                                  cancelled=False, result=None, error=False)
            self.pending.append(job)
            self.jobs[id(job)] = job
            if not self.started:
                self.started = True
                for index in range(self.workers):
                    Thread(target=self.run, daemon=True, name=f'estante-panel-{index}').start()
            self.condition.notify()
        return job

    def cancel(self, scope):
        with self.condition:
            for identity, job in list(self.jobs.items()):
                if job.scope == scope:
                    job.cancelled = True
                    self.clear(job)
                    del self.jobs[identity]
            self.pending = deque(job for job in self.pending if not job.cancelled)

    def deliver(self, job):
        try:
            if not job.cancelled:
                callback = job.failed if job.error else job.done
                if callback:
                    callback(job.result)
        finally:
            with self.condition:
                self.jobs.pop(id(job), None)
                self.clear(job)
        return False

    def run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: bool(self.pending))
                job = self.pending.popleft()
                work = job.work
            try:
                result, error = work(), False
            except Exception as exception:
                result, error = str(exception), True
            with self.condition:
                if not job.cancelled:
                    job.result, job.error = result, error
                job.work = work = result = None
                if not job.cancelled:
                    # Keep the result in the cancellable job, not in an idle closure.
                    self.dispatch(lambda job=job: self.deliver(job))
                self.condition.notify_all()
            # Idle workers must not retain the previous panel or image result.
            job = None
