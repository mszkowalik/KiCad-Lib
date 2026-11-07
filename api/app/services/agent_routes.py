"""Agent tools generated from API routes (decision 0106).

A route with `openapi_extra={"x-agent-tool": "get_parts_stock"}` is a tool. Its
description is the route's docstring and its arguments are the route's path,
query and JSON body, all read from the OpenAPI document. There is no tool code to
write and nothing to keep in step with the route.

`routers/agent.py` serves these beside `agent_tools.TOOLS` and calls the route
through the whole app, so the gate, the company scope, the audit row and the
`dry_run` default are the browser's.

A hand-written tool in `agent_tools.py` is still right when the answer must be
shaped or a part must be named by something the route does not take.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

TOOL_KEY = "x-agent-tool"
MAX_CHARS = 40_000
_MAX_CHARS_ARG = "max_chars"
_CONFIRM_ARG = "confirm"


@dataclass(frozen=True)
class RouteTool:
    name: str
    method: str
    path: str
    description: str
    input_schema: dict
    path_params: tuple[str, ...]
    query_params: tuple[str, ...]
    body_params: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


def _resolve(spec: dict, node, seen: tuple[str, ...] = ()):
    """Inline `$ref`s and drop `title`, which only adds words to the catalog. A
    self-referring model stops at a plain object rather than recursing."""
    if isinstance(node, list):
        return [_resolve(spec, x, seen) for x in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if ref:
        if ref in seen:
            return {"type": "object"}
        target = spec
        for part in ref.removeprefix("#/").split("/"):
            target = target[part]
        return _resolve(spec, target, (*seen, ref))
    return {k: _resolve(spec, v, seen) for k, v in node.items() if k != "title"}


def _tool(spec: dict, name: str, method: str, path: str, op: dict) -> RouteTool:
    where = f"{method} {path} (tool {name!r})"
    props: dict[str, dict] = {}
    required: list[str] = []
    groups: dict[str, list[str]] = {"path": [], "query": []}

    def add(key: str, schema: dict, is_required: bool) -> None:
        if key in props:
            raise ValueError(f"{where}: two arguments are named {key!r}")
        props[key] = schema
        if is_required:
            required.append(key)

    for p in op.get("parameters", []):
        if p.get("in") not in groups:  # a header or a cookie is the caller's, never an argument
            continue
        schema = _resolve(spec, p.get("schema", {}))
        if p.get("description"):
            schema = {**schema, "description": p["description"]}
        add(p["name"], schema, p.get("required", False))
        groups[p["in"]].append(p["name"])

    body_params: list[str] = []
    content = (op.get("requestBody") or {}).get("content")
    if content:
        schema = content.get("application/json", {}).get("schema")
        if schema is None:
            raise ValueError(f"{where}: only a JSON body can be a tool. A file upload stays on api_request")
        body = _resolve(spec, schema)
        if "properties" not in body:
            raise ValueError(f"{where}: the JSON body must be an object with named fields")
        wanted = set(body.get("required", []))
        for key, sub in body["properties"].items():
            add(key, sub, key in wanted)
            body_params.append(key)

    for reserved in (_MAX_CHARS_ARG, _CONFIRM_ARG):
        if reserved in props:
            raise ValueError(f"{where}: the argument name {reserved!r} is reserved")
    props[_MAX_CHARS_ARG] = {"type": "integer", "description": f"Cut the answer at this length. Default {MAX_CHARS}."}
    if method == "DELETE":
        props[_CONFIRM_ARG] = {"type": "boolean", "description": "Must be true. Ask the user first."}
        required.append(_CONFIRM_ARG)

    doc = (op.get("description") or "").strip()
    if not doc:
        raise ValueError(f"{where}: a route tool needs a docstring, because it is the tool's description")
    return RouteTool(
        name=name, method=method, path=path,
        description=f"{doc}\n\nThis is {method} {path}. The answer is that route's JSON, as the browser gets it.",
        input_schema={"type": "object", "properties": props, "required": required, "additionalProperties": False},
        path_params=tuple(groups["path"]), query_params=tuple(groups["query"]), body_params=tuple(body_params),
    )


def build(spec: dict) -> dict[str, RouteTool]:
    """Every tagged operation of an OpenAPI document, by tool name."""
    tools: dict[str, RouteTool] = {}
    for path, ops in spec.get("paths", {}).items():
        for method, op in ops.items():
            name = op.get(TOOL_KEY) if isinstance(op, dict) else None
            if not name:
                continue
            if name in tools:
                raise ValueError(f"two routes are tagged as the tool {name!r}")
            tools[name] = _tool(spec, name, method.upper(), path, op)
    return tools


def split(tool: RouteTool, args: dict) -> tuple[str, dict, dict | None, int]:
    """(url, query, JSON body, answer limit) from a tool's arguments. A ValueError
    names the bad argument, and it costs the agent one round trip to fix."""
    args = dict(args)
    limit = int(args.pop(_MAX_CHARS_ARG, None) or MAX_CHARS)
    confirmed = args.pop(_CONFIRM_ARG, None)
    if tool.method == "DELETE" and confirmed is not True:
        raise ValueError("a delete needs confirm=true. Say what it removes, and ask the user first")
    unknown = set(args) - {*tool.path_params, *tool.query_params, *tool.body_params}
    if unknown:
        raise ValueError(f"no argument {sorted(unknown)}. It takes {sorted(tool.input_schema['properties'])}")
    url = tool.path
    for key in tool.path_params:
        if key not in args:
            raise ValueError(f"{key!r} is required")
        url = url.replace("{" + key + "}", quote(str(args[key]), safe=""))
    query = {k: args[k] for k in tool.query_params if k in args}
    body = {k: args[k] for k in tool.body_params if k in args}
    return url, query, (body if tool.body_params else None), limit
