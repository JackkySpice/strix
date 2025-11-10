"""FastAPI interface for Strix with a mobile-friendly Aura UI."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, root_validator

from strix.agents.StrixAgent import StrixAgent
from strix.interface.exceptions import (
    DockerImagePullError,
    DockerUnavailableError,
    EnvironmentValidationError,
    LLMWarmupError,
)
from strix.interface.main import (
    check_docker_installed,
    check_environment_variables,
    pull_docker_image,
    warm_up_llm,
)
from strix.interface.utils import assign_workspace_subdirs, generate_run_name, infer_target_type
from strix.llm.config import LLMConfig
from strix.telemetry.tracer import Tracer, set_global_tracer
from strix.tools.agents_graph.agents_graph_actions import send_user_message_to_agent

logger = logging.getLogger(__name__)

app = FastAPI(title="Strix Web Interface", version="0.1.0")

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


class ScanCreateRequest(BaseModel):
    targets: list[str] | None = Field(default=None)
    target: str | None = Field(default=None)
    instruction: str | None = Field(default=None, max_length=2_000)
    run_name: str | None = Field(default=None, max_length=120)

    @root_validator(pre=True)
    def ensure_targets(cls, values: dict[str, Any]) -> dict[str, Any]:
        targets = values.get("targets")
        target = values.get("target")
        if targets is None and target:
            targets = [target]
        if not targets:
            raise ValueError("At least one target must be provided.")
        values["targets"] = targets
        return values
class ScanMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2_000)

    @root_validator(pre=True)
    def ensure_content(cls, values: dict[str, Any]) -> dict[str, Any]:
        content = (values.get("content") or "").strip()
        if not content:
            raise ValueError("Message content cannot be empty.")
        values["content"] = content
        return values



@dataclass
class ScanRecord:
    run_id: str
    targets_info: list[dict[str, Any]]
    instruction: str | None
    status: str
    started_at: datetime
    tracer: Tracer
    scan_config: dict[str, Any]
    agent_config: dict[str, Any]
    results_path: Path
    ended_at: datetime | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    task: asyncio.Task | None = None

    @property
    def original_targets(self) -> list[str]:
        return [target["original"] for target in self.targets_info]


class ScanManager:
    def __init__(self) -> None:
        self._scans: dict[str, ScanRecord] = {}
        self._lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()
        self._initialized = False
        self._init_error: str | None = None
        self._active_run_id: str | None = None
        self._message_locks: dict[str, asyncio.Lock] = {}

    async def ensure_ready(self) -> None:
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            try:
                env_check = check_environment_variables()
                if env_check.missing_required:
                    raise EnvironmentValidationError(
                        env_check.missing_required, env_check.missing_optional
                    )

                check_docker_installed()
                await asyncio.to_thread(pull_docker_image)
                await warm_up_llm()

            except (
                EnvironmentValidationError,
                DockerUnavailableError,
                DockerImagePullError,
                LLMWarmupError,
            ) as exc:
                self._init_error = str(exc)
                logger.error("Pre-flight check failed: %s", exc, exc_info=True)
                raise
            except Exception as exc:  # noqa: BLE001
                self._init_error = str(exc)
                logger.exception("Unexpected error during pre-flight checks")
                raise
            else:
                self._initialized = True
                self._init_error = None

    async def start_scan(
        self,
        targets: list[str],
        instruction: str | None = None,
        run_name: str | None = None,
    ) -> ScanRecord:
        cleaned_targets = [target.strip() for target in targets if target and target.strip()]
        if not cleaned_targets:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provide at least one valid target.")

        await self.ensure_ready()

        async with self._lock:
            if self._active_run_id and self._scans.get(self._active_run_id):
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "A scan is already running. Please wait for it to finish."
                )

            run_id = run_name or generate_run_name()
            targets_info = self._build_targets_info(cleaned_targets)

            tracer = Tracer(run_id)
            scan_config = {
                "scan_id": run_id,
                "targets": targets_info,
                "user_instructions": instruction or "",
                "run_name": run_id,
            }
            tracer.set_scan_config(scan_config)

            agent_config: dict[str, Any] = {
                "llm_config": LLMConfig(),
                "max_iterations": 300,
                "non_interactive": True,
            }

            record = ScanRecord(
                run_id=run_id,
                targets_info=targets_info,
                instruction=instruction,
                status="starting",
                started_at=datetime.now(UTC),
                tracer=tracer,
                scan_config=scan_config,
                agent_config=agent_config,
                results_path=Path("agent_runs") / run_id,
            )

            record.task = asyncio.create_task(self._run_scan(record), name=f"strix-scan-{run_id}")
            record.task.add_done_callback(self._log_background_error)

            self._scans[run_id] = record
            self._active_run_id = run_id

            return record

    def _build_targets_info(self, targets: list[str]) -> list[dict[str, Any]]:
        targets_info: list[dict[str, Any]] = []

        for target in targets:
            try:
                target_type, details = infer_target_type(target)
            except ValueError as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

            if target_type in {"repository", "local_code"}:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Repository and local directory targets are not supported in the web interface yet. "
                    "Please use the CLI for those scans.",
                )

            display_target = details.get("target_path", target) if target_type == "local_code" else target
            targets_info.append({"type": target_type, "details": details, "original": display_target})

        assign_workspace_subdirs(targets_info)
        return targets_info

    async def send_message(self, run_id: str, content: str) -> ScanRecord:
        record = self.get_scan(run_id)
        tracer = record.tracer
        root_agent_id = tracer.root_agent_id

        if not root_agent_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Agent is not ready to receive messages yet.",
            )

        lock = self._message_locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            agent_info = tracer.agents.get(root_agent_id)
            agent_status = agent_info.get("status") if agent_info else None

            if agent_status != "waiting":
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Agent is currently processing and not awaiting input.",
                )

            tracer.log_chat_message(content, "user", agent_id=root_agent_id)

            result = send_user_message_to_agent(root_agent_id, content)
            if not result.get("success", True):
                error_message = result.get("error") or "Failed to deliver message to agent."
                raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, error_message)
            tracer.update_agent_status(root_agent_id, "running")

        return record

    def _log_background_error(self, task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return
        try:
            _ = task.result()
        except Exception:  # noqa: BLE001
            logger.exception("Background scan task failed")

    async def _run_scan(self, record: ScanRecord) -> None:
        tracer = record.tracer
        try:
            set_global_tracer(tracer)
            record.status = "running"

            agent = StrixAgent(record.agent_config)
            result = await agent.execute_scan(record.scan_config)
            record.result = result

            if isinstance(result, dict) and not result.get("success", True):
                record.status = "failed"
                record.error = result.get("error", "Scan reported failure.")
            else:
                record.status = "completed"

        except Exception as exc:  # noqa: BLE001
            record.status = "failed"
            record.error = str(exc)
            logger.exception("Scan %s failed", record.run_id)
        finally:
            try:
                tracer.cleanup()
            finally:
                record.ended_at = datetime.now(UTC)
                await self._clear_active_run(record.run_id)
                set_global_tracer(None)

    async def _clear_active_run(self, run_id: str) -> None:
        async with self._lock:
            if self._active_run_id == run_id:
                self._active_run_id = None
            self._message_locks.pop(run_id, None)

    def list_scans(self) -> list[ScanRecord]:
        return sorted(self._scans.values(), key=lambda record: record.started_at, reverse=True)

    def get_scan(self, run_id: str) -> ScanRecord:
        record = self._scans.get(run_id)
        if not record:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run '{run_id}' not found.")
        return record

    def get_status(self) -> dict[str, Any]:
        active = self._active_run_id is not None
        return {
            "initialized": self._initialized,
            "active": active,
            "active_run_id": self._active_run_id,
            "error": self._init_error,
        }


scan_manager = ScanManager()


def _serialize_scan(record: ScanRecord) -> dict[str, Any]:
    tracer = record.tracer
    waiting_for_input = False
    waiting_since: str | None = None
    root_agent_status: str | None = None
    root_agent_id = tracer.root_agent_id
    if root_agent_id:
        agent_info = tracer.agents.get(root_agent_id, {})
        root_agent_status = agent_info.get("status")
        waiting_for_input = root_agent_status == "waiting"
        waiting_since = (
            agent_info.get("waiting_since") or tracer.agent_waiting_since.get(root_agent_id)
        )
    return {
        "run_id": record.run_id,
        "targets": record.original_targets,
        "instruction": record.instruction,
        "status": record.status,
        "started_at": record.started_at.isoformat(),
        "ended_at": record.ended_at.isoformat() if record.ended_at else None,
        "vulnerability_count": len(tracer.vulnerability_reports),
        "has_report": bool(tracer.final_scan_result),
        "error": record.error,
        "waiting_for_input": waiting_for_input,
        "waiting_since": waiting_since,
        "root_agent_id": root_agent_id,
        "root_agent_status": root_agent_status,
    }


def _parse_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=UTC)

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %Z").replace(tzinfo=UTC)
        except ValueError:
            return datetime.min.replace(tzinfo=UTC)


def _serialize_events(record: ScanRecord) -> list[dict[str, Any]]:
    tracer = record.tracer
    events: list[dict[str, Any]] = []

    for message in tracer.chat_messages:
        events.append(
            {
                "id": f"chat-{message['message_id']}",
                "type": "chat",
                "role": message.get("role", "assistant"),
                "content": message.get("content", ""),
                "timestamp": message.get("timestamp"),
            }
        )

    for execution_id, execution in tracer.tool_executions.items():
        if execution.get("tool_name") != "terminal_execute":
            continue

        args = execution.get("args") or {}
        result = execution.get("result") or {}
        timestamp = execution.get("completed_at") or execution.get("timestamp")

        events.append(
            {
                "id": f"terminal-{execution_id}",
                "type": "terminal",
                "command": args.get("command") or "",
                "is_input": bool(args.get("is_input")),
                "status": execution.get("status", "unknown"),
                "exit_code": result.get("exit_code"),
                "output": result.get("content") or "",
                "error": result.get("error"),
                "terminal_id": args.get("terminal_id") or result.get("terminal_id") or "default",
                "working_dir": result.get("working_dir"),
                "timestamp": timestamp,
            }
        )

    for report in tracer.vulnerability_reports:
        events.append(
            {
                "id": report["id"],
                "type": "vulnerability",
                "title": report.get("title", "Vulnerability"),
                "content": report.get("content", ""),
                "severity": report.get("severity", "info"),
                "timestamp": report.get("timestamp"),
            }
        )

    if tracer.final_scan_result:
        events.append(
            {
                "id": f"summary-{record.run_id}",
                "type": "summary",
                "content": tracer.final_scan_result,
                "timestamp": record.ended_at.isoformat() if record.ended_at else None,
            }
        )

    events.sort(key=lambda event: (_parse_timestamp(event.get("timestamp")), event.get("id", "")))
    return events


@app.get("/", response_class=HTMLResponse)
async def render_home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("aura.html", {"request": request})


@app.get("/api/status")
async def api_status() -> dict[str, Any]:
    return scan_manager.get_status()


@app.get("/api/scans")
async def list_scans() -> list[dict[str, Any]]:
    return [_serialize_scan(record) for record in scan_manager.list_scans()]


@app.post("/api/scans", status_code=status.HTTP_201_CREATED)
async def create_scan(payload: ScanCreateRequest) -> dict[str, Any]:
    try:
        record = await scan_manager.start_scan(payload.targets, payload.instruction, payload.run_name)
    except (
        EnvironmentValidationError,
        DockerUnavailableError,
        DockerImagePullError,
        LLMWarmupError,
    ) as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc

    return _serialize_scan(record)


@app.post("/api/scans/{run_id}/messages")
async def post_scan_message(run_id: str, payload: ScanMessageRequest) -> dict[str, Any]:
    record = await scan_manager.send_message(run_id, payload.content)
    return _serialize_scan(record)


@app.get("/api/scans/{run_id}")
async def get_scan(run_id: str) -> dict[str, Any]:
    record = scan_manager.get_scan(run_id)
    data = _serialize_scan(record)
    tracer = record.tracer
    data.update(
        {
            "vulnerabilities": tracer.vulnerability_reports,
            "final_report": tracer.final_scan_result,
            "results_path": str(record.results_path),
        }
    )
    return data


@app.get("/api/scans/{run_id}/events")
async def get_scan_events(run_id: str) -> list[dict[str, Any]]:
    record = scan_manager.get_scan(run_id)
    return _serialize_events(record)


@app.get("/api/scans/{run_id}/report")
async def get_scan_report(run_id: str) -> dict[str, Any]:
    record = scan_manager.get_scan(run_id)
    tracer = record.tracer
    if not tracer.final_scan_result:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not ready yet.")
    return {
        "run_id": run_id,
        "content": tracer.final_scan_result,
        "saved_to": str(record.results_path / "penetration_test_report.md"),
    }


@app.get("/api/scans/{run_id}/vulnerabilities")
async def get_scan_vulnerabilities(run_id: str) -> dict[str, Any]:
    record = scan_manager.get_scan(run_id)
    tracer = record.tracer
    return {
        "run_id": run_id,
        "count": len(tracer.vulnerability_reports),
        "items": tracer.vulnerability_reports,
    }

