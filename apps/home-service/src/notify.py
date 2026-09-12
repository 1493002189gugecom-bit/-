"""Multi-target notification planning (design section 7).

Rules enforced here, not by the LLM:
- Look up each target's simulated location.
- Targets whose location is unknown are reported as not notified, and the
  caller is expected to ask. No whole-house broadcast is ever issued silently.
- Targets in the same room are merged into one task.
- Different rooms are queued in order; the state service plays them serially.
- Wording never claims the target heard or arrived.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from state import HomeState
from tools import ToolResult, ToolService


@dataclass
class NotificationPlan:
    targets: list[str]
    notified: list[dict] = field(default_factory=list)
    unknown: list[dict] = field(default_factory=list)
    merged: list[dict] = field(default_factory=list)
    tasks: list[dict] = field(default_factory=list)
    phrase: str = ""
    needs_clarification: bool = False

    def to_dict(self) -> dict:
        return {
            "targets": self.targets,
            "notified": self.notified,
            "unknown": self.unknown,
            "merged": self.merged,
            "tasks": self.tasks,
            "phrase": self.phrase,
            "needs_clarification": self.needs_clarification,
        }


def plan_notification(
    service: ToolService,
    targets: list[str],
    text: str,
    operation_id: str | None = None,
) -> ToolResult:
    """Resolve targets, dedupe by room, queue one broadcast task per room."""
    state: HomeState = service.state
    if not targets:
        return ToolResult(False, error="没有指定要通知的人", error_code="invalid_params")
    if not text or not text.strip():
        return ToolResult(False, error="播报内容不能为空", error_code="invalid_params")

    plan = NotificationPlan(targets=list(targets))
    by_room: dict[str, dict] = {}

    for name in targets:
        person = state.resolve_person(name)
        if person is None:
            plan.unknown.append({"target": name, "reason": "无法确定是谁"})
            continue
        if not person.location_known:
            # Deliberately no fallback to a whole-house broadcast.
            plan.unknown.append(
                {"target": name, "person_id": person.id, "display_name": person.display_name, "reason": "位置未知"}
            )
            continue
        room = state.rooms[person.room_id]
        entry = by_room.setdefault(
            room.id,
            {"room_id": room.id, "room_name": room.name, "person_ids": [], "display_names": []},
        )
        if person.id in entry["person_ids"]:
            plan.merged.append({"person_id": person.id, "reason": "同一目标重复出现"})
            continue
        entry["person_ids"].append(person.id)
        entry["display_names"].append(person.display_name)
        plan.notified.append(
            {"target": name, "person_id": person.id, "display_name": person.display_name, "room_name": room.name}
        )

    # Queue in the order the rooms were first mentioned, merged per room.
    op_id = operation_id
    for index, entry in enumerate(by_room.values()):
        result = service.broadcast_to_room(
            entry["room_name"],
            text,
            person_ids=entry["person_ids"],
            # Only the first task reuses the caller's operation id; later rooms
            # get their own so a retry never double-queues.
            operation_id=op_id if index == 0 else None,
        )
        if not result.ok:
            return ToolResult(
                False,
                error=result.error,
                error_code=result.error_code,
                operation_id=result.operation_id,
                data=plan.to_dict(),
            )
        entry["task_id"] = result.data["task_id"]
        entry["state"] = result.data["state"]
        plan.tasks.append(
            {
                "task_id": result.data["task_id"],
                "room_id": entry["room_id"],
                "room_name": entry["room_name"],
                "display_names": entry["display_names"],
                "state": result.data["state"],
            }
        )

    plan.phrase = _phrase(plan)
    plan.needs_clarification = bool(plan.unknown)
    if not plan.tasks and plan.unknown:
        return ToolResult(True, data=plan.to_dict(), phrase=plan.phrase)
    return ToolResult(
        True,
        data=plan.to_dict(),
        operation_id=plan.tasks[0]["task_id"] if plan.tasks else None,
        phrase=plan.phrase,
    )


def _phrase(plan: NotificationPlan) -> str:
    """Build wording that only claims what actually happened."""
    parts: list[str] = []
    for task in plan.tasks:
        names = "、".join(task["display_names"])
        parts.append(f"已安排在{task['room_name']}播报给{names}")
    if plan.unknown:
        missing = "、".join(item["target"] for item in plan.unknown)
        parts.append(f"没有{missing}的位置，未通知，需要全屋播报吗")
    if not parts:
        return "没有可通知的目标"
    return "；".join(parts)
