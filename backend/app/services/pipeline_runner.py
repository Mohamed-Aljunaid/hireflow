"""Runs pipeline graphs as background tasks and keeps `applications.status` in sync.

The checkpointer is the source of truth for pipeline *state*; the applications row holds
the run's *status*. If the process dies mid-run, the row stays "running", and
`resume_incomplete()` (called at startup) continues each such run from its last
checkpoint. Nodes that already finished are not re-executed.
"""

import asyncio
import logging
import uuid
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StateSnapshot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.review import validate_decision
from app.agents.schemas.review import PendingReview, ReviewDecision
from app.agents.state import PipelineState
from app.core.llm import LLMError
from app.services import application_repository as apps
from app.services import cv_repository

logger = logging.getLogger(__name__)


class NotAwaitingApprovalError(Exception):
    """resume() was called on a run that is not paused at a gate."""


def thread_config(app_id: uuid.UUID) -> RunnableConfig:
    return {"configurable": {"thread_id": str(app_id)}}


def pending_review(snapshot: StateSnapshot) -> PendingReview | None:
    """The gate the run is paused at, if any."""
    for intr in snapshot.interrupts:
        if isinstance(intr.value, dict) and "gate" in intr.value:
            return PendingReview.model_validate(intr.value)
    return None


def status_from_snapshot(snapshot: StateSnapshot) -> apps.ApplicationStatus:
    """Status of a run that is not executing right now."""
    if pending_review(snapshot) is not None:
        return "awaiting_approval"
    if snapshot.next:
        return "running"  # pending nodes but no gate: interrupted mid-run
    if "rejection" in snapshot.values:
        return "rejected"
    return "completed"


class PipelineRunner:
    def __init__(
        self, graph: CompiledStateGraph, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self._graph = graph
        self._sessions = session_factory
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}

    # ---------- public API ----------

    async def start(self, app_id: uuid.UUID) -> None:
        """Start a new run for an application row that already exists."""
        self._spawn(app_id, await self._initial_input(app_id))

    async def resume_incomplete(self) -> list[uuid.UUID]:
        """Continue every run left 'running' (e.g. by a crash or restart)."""
        async with self._sessions() as session:
            ids = await apps.list_ids_with_status(session, "running")
        resumed = []
        for app_id in ids:
            if app_id in self._tasks:
                continue
            snapshot = await self.snapshot(app_id)
            status = status_from_snapshot(snapshot)
            if not snapshot.values:
                # Died before the first checkpoint: start over from the stored inputs.
                self._spawn(app_id, await self._initial_input(app_id))
            elif status == "running":
                self._spawn(app_id, None)  # None = continue from the checkpoint
            else:
                # Paused at a gate or finished, but the status update was lost
                # (e.g. crash between a resume request and the run starting).
                await self._set_status(app_id, status)
                continue
            resumed.append(app_id)
            logger.info("resumed application %s", app_id)
        return resumed

    async def resume(self, app_id: uuid.UUID, decision: ReviewDecision) -> None:
        """Answer the gate the run is paused at and continue it in the background.

        Raises NotAwaitingApprovalError (-> 409) or ReviewValidationError (-> 422).
        Validation happens here, before resuming, so a bad edit never kills the run.
        """
        snapshot = await self.snapshot(app_id)
        review = pending_review(snapshot)
        if review is None:
            raise NotAwaitingApprovalError(f"application {app_id} is not awaiting approval")
        validate_decision(review.gate, decision, snapshot.values)

        # Atomic status flip: of two concurrent resumes, exactly one wins.
        async with self._sessions() as session:
            won = await apps.transition(session, app_id, "awaiting_approval", "running")
        if not won:
            raise NotAwaitingApprovalError(f"application {app_id} is not awaiting approval")
        self._spawn(app_id, Command(resume=decision.model_dump(mode="json")))

    async def snapshot(self, app_id: uuid.UUID) -> StateSnapshot:
        return await self._graph.aget_state(thread_config(app_id))

    async def wait(self, app_id: uuid.UUID) -> None:
        """Await a run's background task, if one is in flight (tests, shutdown)."""
        task = self._tasks.get(app_id)
        if task is not None:
            await asyncio.wait({task})

    def is_active(self, app_id: uuid.UUID) -> bool:
        return app_id in self._tasks

    async def shutdown(self) -> None:
        """Cancel in-flight runs. Their status stays 'running', so they resume next start."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # ---------- internals ----------

    async def _initial_input(self, app_id: uuid.UUID) -> PipelineState:
        async with self._sessions() as session:
            application = await apps.get_application(session, app_id)
            if application is None:
                raise LookupError(f"application {app_id} not found")
            cv = await cv_repository.get_cv(session, application.cv_id)
            if cv is None:
                raise LookupError(f"CV {application.cv_id} not found")
            return {
                "application_id": str(app_id),
                "cv": cv.parsed,
                "job_text": application.job_text,
            }

    def _spawn(self, app_id: uuid.UUID, graph_input: Any) -> None:
        task = asyncio.create_task(self._run(app_id, graph_input), name=f"pipeline-{app_id}")
        self._tasks[app_id] = task

        def _forget(done: asyncio.Task[None]) -> None:
            # Only remove our own entry: a resume may already have spawned a newer task.
            if self._tasks.get(app_id) is done:
                del self._tasks[app_id]

        task.add_done_callback(_forget)

    async def _run(self, app_id: uuid.UUID, graph_input: Any) -> None:
        try:
            # durability="sync": each step's checkpoint is written before the next starts,
            # so a crash loses at most the step in progress.
            await self._graph.ainvoke(graph_input, thread_config(app_id), durability="sync")
        except asyncio.CancelledError:
            logger.info("application %s interrupted; will resume on next start", app_id)
            raise
        except LLMError as exc:
            logger.warning("application %s failed: %s", app_id, exc)
            await self._set_status(app_id, "failed", error=str(exc))
            return
        except Exception as exc:
            logger.exception("application %s crashed", app_id)
            await self._set_status(app_id, "failed", error=f"internal error: {type(exc).__name__}")
            return
        # ainvoke returns when the graph ends or pauses at a gate.
        await self._set_status(app_id, status_from_snapshot(await self.snapshot(app_id)))

    async def _set_status(
        self, app_id: uuid.UUID, status: apps.ApplicationStatus, error: str | None = None
    ) -> None:
        try:
            async with self._sessions() as session:
                await apps.set_status(session, app_id, status, error=error)
        except Exception:
            logger.exception("could not record status %s for application %s", status, app_id)
