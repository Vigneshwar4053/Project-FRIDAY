"""Synchronous job lifecycle boundary around a single model provider."""
from friday.models.job import JobStatus, ModelJob, utc_now
from friday.models.queue import ModelJobQueue
from friday.models.registry import ModelRegistry
from friday.sync import PythonSemaphore, Synchronization, SynchronizationError
from friday.providers.base import ModelProvider, ProviderError


class ModelManager:
    """Own a queue, registry, and provider bound to one explicit model name.

    Registry names are metadata. Phase 1 cannot rebind a provider to another
    model. Only provider execution is protected. Queue, registry, and manager
    scheduling still require single-threaded use; no background workers exist.
    """
    def __init__(self, provider: ModelProvider, model: str, *,
                 synchronization: Synchronization | None = None):
        configured_model = getattr(provider, 'model', None)
        if isinstance(configured_model, str) and configured_model != model:
            raise ValueError('Runtime model must match the configured provider model.')
        self.registry = ModelRegistry()
        self.registry.register(model)
        self.queue = ModelJobQueue()
        self.provider = provider
        self.provider_model = model
        self.last_job: ModelJob | None = None
        self.synchronization = synchronization if synchronization is not None else PythonSemaphore()
        self._owns_synchronization = synchronization is None
        self._closed = False
        self._executing = False

    def __enter__(self) -> 'ModelManager':
        self._require_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def _require_open(self) -> None:
        if self._closed:
            raise SynchronizationError('Model manager is closed.')

    def close(self) -> None:
        """Close owned synchronization only; injected resources remain caller-owned."""
        if self._closed:
            return
        if self._executing:
            raise SynchronizationError('Cannot close the model manager during execution.')
        if self._owns_synchronization:
            self.synchronization.close()
        self._closed = True

    def create_job(self, messages: list[dict[str, str]], *, model: str | None = None,
                   priority: int = 0) -> ModelJob:
        self._require_open()
        return ModelJob(model=model if model is not None else self.registry.current_model,
                        messages=messages, priority=priority)

    def submit_job(self, job: ModelJob) -> ModelJob:
        self._require_open()
        self.queue.enqueue(job)
        return job

    def execute_next(self) -> ModelJob | None:
        self._require_open()
        job = self.queue.next_job()
        return self.execute_job(job) if job is not None else None

    def execute_job(self, job: ModelJob) -> ModelJob:
        """Execute a pending supplied job immediately, bypassing queue priority.

        Ordinary generation errors are recorded and returned as failed jobs.
        Interrupts are recorded as failed, then re-raised for the CLI to exit.
        """
        self._require_open()
        if job.status != JobStatus.PENDING:
            raise ValueError('Only pending jobs can be executed; create a new job to retry.')
        self.queue.remove(job)
        self.last_job = job
        self._executing = True
        try:
            job.started_at = utc_now()
            job.status = JobStatus.RUNNING
            if job.model not in self.registry.registered_models:
                raise ProviderError('The requested model is not registered.')
            if job.model != self.provider_model:
                raise ProviderError('This runtime provider is bound to a different model.')
            with self.synchronization:
                self.registry.mark_active(job.model)
                response = self.provider.chat([dict(message) for message in job.messages])
            if not isinstance(response, str) or not response.strip():
                raise ProviderError('The model returned no final answer.')
            job.result = response.strip()
            job.status = JobStatus.COMPLETED
        except SynchronizationError as exc:
            job.error = f"Model synchronization failed: {exc}"
            job.status = JobStatus.FAILED
        except ProviderError as exc:
            job.error = str(exc)
            job.status = JobStatus.FAILED
        except Exception:
            # Unexpected provider errors must not spill response content into the UI.
            job.error = 'Model generation failed unexpectedly.'
            job.status = JobStatus.FAILED
        except BaseException:
            # KeyboardInterrupt/SystemExit must never leave the job running.
            job.error = 'Model execution was interrupted.'
            job.status = JobStatus.FAILED
            raise
        finally:
            job.finished_at = utc_now()
            self._executing = False
        return job

    def generate(self, messages: list[dict[str, str]]) -> str:
        """Run this conversational request immediately; leave unrelated jobs queued.

        This convenience path explicitly executes its supplied job. Use
        execute_next() to drain queued jobs in priority/FIFO order.
        """
        job = self.submit_job(self.create_job(messages))
        self.execute_job(job)
        if job.status == JobStatus.FAILED:
            raise ProviderError(job.error)
        return job.result
