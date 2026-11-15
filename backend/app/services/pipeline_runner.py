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
from langgraph.types import StateSnapshot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.state import PipelineState
from app.core.llm import LLMError
from app.services import application_repository as apps
from app.services import cv_repository

logger = logging.getLogger(__name__)


def thread_config(app_id: uuid.UUID) -> RunnableConfig:
    return {"configurable": {"thread_id": str(app_id)}}


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
            if not snapshot.values:
                # Died before the first checkpoint: start over from the stored inputs.
                self._spawn(app_id, await self._initial_input(app_id))
            elif snapshot.next:
                self._spawn(app_id, None)  # None = continue from the checkpoint
            else:
                # Finished, but the status update was lost.
                await self._set_status(app_id, "completed")
                continue
            resumed.append(app_id)
            logger.info("resumed application %s", app_id)
        return resumed

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
        task.add_done_callback(lambda _: self._tasks.pop(app_id, None))

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
        await self._set_status(app_id, "completed")

    async def _set_status(
        self, app_id: uuid.UUID, status: apps.ApplicationStatus, error: str | None = None
    ) -> None:
        try:
            async with self._sessions() as session:
                await apps.set_status(session, app_id, status, error=error)
        except Exception:
            logger.exception("could not record status %s for application %s", status, app_id)
