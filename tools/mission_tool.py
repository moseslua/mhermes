#!/usr/bin/env python3
"""Mission tool — canonical mission, handoff, and checkpoint management."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from agent.handoff_packets import build_mission_bundle, record_mission_checkpoint
from agent.mission_state import MissionService
from tools.registry import registry, tool_error, tool_result


MISSION_SCHEMA = {
    "name": "mission",
    "description": (
        "Manage canonical Hermes mission state. Use for creating, approving, attaching, "
        "and reading missions; managing mission nodes and links; reading or writing "
        "mission-linked handoffs and checkpoints; and building projection-only mission bundles."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "create",
                    "approve",
                    "attach",
                    "detach",
                    "get",
                    "list",
                    "add_node",
                    "update_node",
                    "list_nodes",
                    "link",
                    "list_links",
                    "todos",
                    "handoff",
                    "checkpoint",
                    "list_checkpoints",
                    "list_handoffs",
                    "bundle",
                ],
                "description": "Mission operation to perform.",
            },
            "mission_id": {"type": "string", "description": "Mission identifier."},
            "title": {"type": "string", "description": "Human-readable title."},
            "description": {"type": "string", "description": "Optional mission description."},
            "status": {"type": "string", "description": "Status for update actions."},
            "session_id": {"type": "string", "description": "Override session id for attach/detach/todos/checkpoints."},
            "node_id": {"type": "string", "description": "Mission node identifier."},
            "parent_node_id": {"type": "string", "description": "Parent mission node identifier."},
            "node_type": {"type": "string", "description": "Mission node type (task, feature, assertion, checkpoint, note, milestone)."},
            "external_id": {"type": "string", "description": "Stable external id for a mission node, such as a todo id."},
            "content": {"type": "string", "description": "Node or todo content/title."},
            "body": {"type": "string", "description": "Optional longer node body."},
            "position": {"type": "integer", "description": "Mission node ordering position."},
            "metadata": {"type": "object", "description": "Optional metadata payload."},
            "source_node_id": {"type": "string", "description": "Link source node id."},
            "target_node_id": {"type": "string", "description": "Link target node id."},
            "link_type": {"type": "string", "description": "Mission link type."},
            "goal": {"type": "string", "description": "Canonical handoff goal text."},
            "to_session_id": {"type": "string", "description": "Optional receiving session id for a handoff packet."},
            "child_session_id": {"type": "string", "description": "Optional delegated child session id for a handoff packet."},
            "todos": {
                "type": "array",
                "description": "Todo items for attached-session mission task write-through.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "content": {"type": "string"},
                        "status": {"type": "string"},
                    },
                    "required": ["id", "content", "status"],
                },
            },
            "merge": {"type": "boolean", "default": False},
            "checkpoint_type": {"type": "string", "description": "Checkpoint classification."},
            "payload": {"type": ["object", "array", "string", "number", "boolean", "null"], "description": "Checkpoint payload."},
        },
        "required": ["action"],
    },
}


def check_mission_requirements() -> bool:
    return True


def mission_tool(
    *,
    action: str,
    mission_id: str | None = None,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    session_id: str | None = None,
    node_id: str | None = None,
    parent_node_id: str | None = None,
    node_type: str | None = None,
    external_id: str | None = None,
    content: str | None = None,
    body: str | None = None,
    position: int | None = None,
    metadata: Any = None,
    source_node_id: str | None = None,
    target_node_id: str | None = None,
    link_type: str | None = None,
    goal: str | None = None,
    to_session_id: str | None = None,
    child_session_id: str | None = None,
    todos: Optional[List[Dict[str, Any]]] = None,
    merge: bool = False,
    checkpoint_type: str | None = None,
    payload: Any = None,
    service: MissionService | None = None,
    db=None,
) -> str:
    svc = service or MissionService(db)
    if not svc.available:
        return tool_error("Session database not available")
    try:
        if action == "create":
            return tool_result(
                success=True,
                mission=svc.create_mission(
                    title=title or content or "",
                    description=description,
                    created_by_session_id=session_id,
                    metadata=metadata if isinstance(metadata, dict) else None,
                ),
            )
        if action == "approve":
            if not mission_id:
                return tool_error("mission_id is required for approve")
            return tool_result(success=True, mission=svc.approve_mission(mission_id, approved_by_session_id=session_id))
        if action == "attach":
            if not mission_id:
                return tool_error("mission_id is required for attach")
            if not session_id:
                return tool_error("session_id is required for attach")
            return tool_result(success=True, mission=svc.attach_session(session_id, mission_id))
        if action == "detach":
            if not session_id:
                return tool_error("session_id is required for detach")
            mission = svc.detach_session(session_id)
            if mission is None:
                return tool_error(f"No attached mission for session: {session_id}")
            return tool_result(success=True, mission=mission)
        if action == "get":
            target_mission_id = mission_id or svc.get_attached_mission_id(session_id)
            if not target_mission_id:
                return tool_error("mission_id or an attached session is required for get")
            mission = svc.get_mission(target_mission_id)
            if mission is None:
                return tool_error(f"Unknown mission: {target_mission_id}")
            return tool_result(success=True, mission=mission)
        if action == "list":
            return tool_result(success=True, missions=svc.list_missions(status=status))
        if action == "add_node":
            if not mission_id:
                return tool_error("mission_id is required for add_node")
            return tool_result(
                success=True,
                node=svc.create_node(
                    mission_id=mission_id,
                    node_type=node_type or "task",
                    title=content or title or "",
                    body=body,
                    status=status or "pending",
                    parent_node_id=parent_node_id,
                    external_id=external_id,
                    position=position or 0,
                    metadata=metadata if isinstance(metadata, dict) else None,
                ),
            )
        if action == "update_node":
            if not node_id:
                return tool_error("node_id is required for update_node")
            node = svc.update_node(
                node_id,
                title=content or title,
                body=body,
                status=status,
                parent_node_id=parent_node_id,
                external_id=external_id,
                position=position,
                metadata=metadata,
            )
            if node is None:
                return tool_error(f"Unknown mission node: {node_id}")
            return tool_result(success=True, node=node)
        if action == "list_nodes":
            if not mission_id:
                return tool_error("mission_id is required for list_nodes")
            return tool_result(success=True, nodes=svc.list_nodes(mission_id, node_type=node_type))
        if action == "link":
            if not mission_id or not source_node_id or not target_node_id or not link_type:
                return tool_error("mission_id, source_node_id, target_node_id, and link_type are required for link")
            return tool_result(
                success=True,
                link=svc.create_link(
                    mission_id=mission_id,
                    source_node_id=source_node_id,
                    target_node_id=target_node_id,
                    link_type=link_type,
                    metadata=metadata if isinstance(metadata, dict) else None,
                ),
            )
        if action == "list_links":
            if not mission_id:
                return tool_error("mission_id is required for list_links")
            return tool_result(success=True, links=svc.list_links(mission_id))
        if action == "todos":
            if not session_id:
                return tool_error("session_id is required for todos")
            if todos is not None:
                if svc.get_attached_mission_id(session_id):
                    return tool_result(success=True, todos=svc.write_todos_for_session(session_id, todos, merge=merge))
                return tool_result(success=True, todos=svc.set_session_local_todos(session_id, todos))
            return tool_result(success=True, todos=svc.get_todos_for_session(session_id))
        if action == "handoff":
            target_mission_id = mission_id or svc.get_attached_mission_id(session_id)
            if not target_mission_id:
                return tool_error("mission_id or an attached session is required for handoff")
            if not goal:
                return tool_error("goal is required for handoff")
            return tool_result(
                success=True,
                handoff=svc.record_handoff_packet(
                    mission_id=target_mission_id,
                    goal=goal,
                    from_session_id=session_id,
                    to_session_id=to_session_id,
                    child_session_id=child_session_id,
                    context=description or body or content,
                    summary=title,
                    status=status or "completed",
                    metadata=metadata if isinstance(metadata, dict) else None,
                ),
            )
        if action == "checkpoint":
            target_mission_id = mission_id or svc.get_attached_mission_id(session_id)
            if not target_mission_id:
                return tool_error("mission_id or an attached session is required for checkpoint")
            if not checkpoint_type:
                return tool_error("checkpoint_type is required for checkpoint")
            checkpoint = record_mission_checkpoint(
                svc,
                target_mission_id,
                checkpoint_type=checkpoint_type,
                session_id=session_id,
                title=title,
                payload=payload if payload is not None else metadata,
            )
            return tool_result(success=True, checkpoint=checkpoint)
        if action == "list_checkpoints":
            target_mission_id = mission_id or svc.get_attached_mission_id(session_id)
            if not target_mission_id:
                return tool_error("mission_id or an attached session is required for list_checkpoints")
            return tool_result(success=True, checkpoints=svc.list_checkpoints(target_mission_id, checkpoint_type=checkpoint_type))
        if action == "list_handoffs":
            target_mission_id = mission_id or svc.get_attached_mission_id(session_id)
            if not target_mission_id:
                return tool_error("mission_id or an attached session is required for list_handoffs")
            return tool_result(success=True, handoffs=svc.list_handoff_packets(target_mission_id))
        if action == "bundle":
            target_mission_id = mission_id or svc.get_attached_mission_id(session_id)
            if not target_mission_id:
                return tool_error("mission_id or an attached session is required for bundle")
            return tool_result(success=True, bundle=build_mission_bundle(svc, target_mission_id))
        return tool_error(f"Unsupported mission action: {action}")
    except Exception as exc:
        return tool_error(str(exc))


registry.register(
    name="mission",
    toolset="mission",
    schema=MISSION_SCHEMA,
    handler=lambda args, **kw: mission_tool(
        action=args.get("action", ""),
        mission_id=args.get("mission_id"),
        title=args.get("title"),
        description=args.get("description"),
        status=args.get("status"),
        session_id=args.get("session_id") or kw.get("session_id"),
        node_id=args.get("node_id"),
        parent_node_id=args.get("parent_node_id"),
        node_type=args.get("node_type"),
        external_id=args.get("external_id"),
        goal=args.get("goal"),
        to_session_id=args.get("to_session_id"),
        child_session_id=args.get("child_session_id"),
        content=args.get("content"),
        body=args.get("body"),
        position=args.get("position"),
        metadata=args.get("metadata"),
        source_node_id=args.get("source_node_id"),
        target_node_id=args.get("target_node_id"),
        link_type=args.get("link_type"),
        todos=args.get("todos"),
        merge=args.get("merge", False),
        checkpoint_type=args.get("checkpoint_type"),
        payload=args.get("payload"),
        service=kw.get("mission_service"),
        db=kw.get("db"),
    ),
    check_fn=check_mission_requirements,
    emoji="🗺️",
)
