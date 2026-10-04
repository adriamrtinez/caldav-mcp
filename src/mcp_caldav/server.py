"""MCP server for CalDAV calendar integration."""

import json
import logging
import os
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import mcp.types as types
from mcp.server import Server, ServerRequestContext
from mcp.types import TextContent, Tool

from .client import CalDAVClient

# Configure logging
logger = logging.getLogger("mcp-caldav")


@dataclass
class AppContext:
    """Application context for MCP CalDAV."""

    client: CalDAVClient | None = None


def get_caldav_config() -> dict[str, str | None]:
    """Get CalDAV configuration from environment variables."""
    return {
        "url": os.getenv("CALDAV_URL"),  # No default - must be configured
        "username": os.getenv("CALDAV_USERNAME")
        or os.getenv("YANDEX_USERNAME"),  # Backward compatibility
        "password": os.getenv("CALDAV_PASSWORD")
        or os.getenv("YANDEX_PASSWORD"),  # Backward compatibility
    }


@asynccontextmanager
async def server_lifespan(server: Server) -> AsyncIterator[AppContext]:  # noqa: ARG001
    """Initialize and clean up application resources."""
    config = get_caldav_config()

    try:
        client = None
        if config["url"] and config["username"] and config["password"]:
            client = CalDAVClient(
                url=config["url"],
                username=config["username"],
                password=config["password"],
            )
            client.connect()
            logger.info(
                f"Connected to CalDAV server: {config['url']} "
                f"for user: {config['username']}"
            )
        else:
            missing = []
            if not config["url"]:
                missing.append("CALDAV_URL")
            if not config["username"]:
                missing.append("CALDAV_USERNAME")
            if not config["password"]:
                missing.append("CALDAV_PASSWORD")
            logger.warning(
                f"CalDAV not configured. Missing: {', '.join(missing)}. "
                "Set these environment variables to enable calendar functionality."
            )

        yield AppContext(client=client)
    finally:
        # Cleanup if needed
        pass


async def list_tools(app_ctx: AppContext) -> list[Tool]:
    """List available CalDAV tools."""
    if not app_ctx or not app_ctx.client:
        return []

    tools = [
        Tool(
            name="caldav_list_calendars",
            description="List all available calendars",
            input_schema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="caldav_create_event",
            description="Create a new event in the calendar",
            input_schema={
                "type": "object",
                "properties": {
                    "calendar_index": {
                        "type": "integer",
                        "description": "Index of the calendar (default: 0)",
                        "default": 0,
                    },
                    "title": {
                        "type": "string",
                        "description": "Event title",
                    },
                    "description": {
                        "type": "string",
                        "description": "Event description",
                        "default": "",
                    },
                    "location": {
                        "type": "string",
                        "description": "Event location",
                        "default": "",
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Start time in ISO format (e.g., '2025-01-20T14:00:00'). "
                        "If not provided, defaults to tomorrow at 14:00",
                    },
                    "end_time": {
                        "type": "string",
                        "description": "End time in ISO format (e.g., '2025-01-20T15:00:00'). "
                        "If not provided, uses duration_hours from start_time",
                    },
                    "duration_hours": {
                        "type": "number",
                        "description": "Duration in hours (used if end_time not provided)",
                        "default": 1.0,
                    },
                    "reminders": {
                        "type": "array",
                        "description": "List of reminders. Each reminder is an object with: "
                        "minutes_before (integer), action ('DISPLAY', 'EMAIL', or 'AUDIO'), "
                        "and optional description (string)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "minutes_before": {"type": "integer"},
                                "action": {
                                    "type": "string",
                                    "enum": ["DISPLAY", "EMAIL", "AUDIO"],
                                },
                                "description": {"type": "string"},
                            },
                            "required": ["minutes_before", "action"],
                        },
                    },
                    "attendees": {
                        "type": "array",
                        "description": "List of attendee email addresses (strings) or objects with 'email' and 'status' (ACCEPTED/DECLINED/TENTATIVE/NEEDS-ACTION)",
                        "items": {
                            "oneOf": [
                                {"type": "string"},
                                {
                                    "type": "object",
                                    "properties": {
                                        "email": {"type": "string"},
                                        "status": {
                                            "type": "string",
                                            "enum": [
                                                "ACCEPTED",
                                                "DECLINED",
                                                "TENTATIVE",
                                                "NEEDS-ACTION",
                                            ],
                                        },
                                    },
                                    "required": ["email"],
                                },
                            ]
                        },
                    },
                    "categories": {
                        "type": "array",
                        "description": "List of category/tag strings",
                        "items": {"type": "string"},
                    },
                    "priority": {
                        "type": "integer",
                        "description": "Priority 0-9 (0 = highest, 9 = lowest)",
                        "minimum": 0,
                        "maximum": 9,
                    },
                    "recurrence": {
                        "type": "object",
                        "description": "Recurrence rule for repeating events",
                        "properties": {
                            "frequency": {
                                "type": "string",
                                "enum": ["DAILY", "WEEKLY", "MONTHLY", "YEARLY"],
                                "description": "How often the event repeats",
                            },
                            "interval": {
                                "type": "integer",
                                "description": "Interval between occurrences (default: 1)",
                                "default": 1,
                            },
                            "count": {
                                "type": "integer",
                                "description": "Number of occurrences",
                            },
                            "until": {
                                "type": "string",
                                "description": "End date in ISO format",
                            },
                            "byday": {
                                "type": "string",
                                "description": "Days of week (e.g., 'MO,WE,FR' for Monday, Wednesday, Friday)",
                            },
                            "bymonthday": {
                                "type": "integer",
                                "description": "Day of month (1-31)",
                            },
                            "bymonth": {
                                "type": "integer",
                                "description": "Month (1-12)",
                            },
                        },
                        "required": ["frequency"],
                    },
                },
                "required": ["title"],
            },
        ),
        Tool(
            name="caldav_get_event_by_uid",
            description="Get a specific event by its UID",
            input_schema={
                "type": "object",
                "properties": {
                    "uid": {
                        "type": "string",
                        "description": "Event UID",
                    },
                    "calendar_index": {
                        "type": "integer",
                        "description": "Index of the calendar (default: 0)",
                        "default": 0,
                    },
                },
                "required": ["uid"],
            },
        ),
        Tool(
            name="caldav_delete_event",
            description="Delete an event by its UID",
            input_schema={
                "type": "object",
                "properties": {
                    "uid": {
                        "type": "string",
                        "description": "Event UID to delete",
                    },
                    "calendar_index": {
                        "type": "integer",
                        "description": "Index of the calendar (default: 0)",
                        "default": 0,
                    },
                },
                "required": ["uid"],
            },
        ),
        Tool(
            name="caldav_search_events",
            description="Search events by text, attendees, or location",
            input_schema={
                "type": "object",
                "properties": {
                    "calendar_index": {
                        "type": "integer",
                        "description": "Index of the calendar (default: 0)",
                        "default": 0,
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query string",
                    },
                    "search_fields": {
                        "type": "array",
                        "description": "Fields to search in: 'title', 'description', 'location', 'attendees'. If not provided, searches in all fields",
                        "items": {
                            "type": "string",
                            "enum": ["title", "description", "location", "attendees"],
                        },
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date for search period in ISO format",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date for search period in ISO format",
                    },
                },
                "required": ["start_date", "end_date"],
            },
        ),
        Tool(
            name="caldav_get_events",
            description="Get events from calendar for a specified period",
            input_schema={
                "type": "object",
                "properties": {
                    "calendar_index": {
                        "type": "integer",
                        "description": "Index of the calendar (default: 0)",
                        "default": 0,
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date in ISO format (e.g., '2025-01-20T00:00:00'). "
                        "Defaults to today 00:00",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date in ISO format (e.g., '2025-01-27T23:59:59'). "
                        "Defaults to 7 days from start_date",
                    },
                    "include_all_day": {
                        "type": "boolean",
                        "description": "Include all-day events",
                        "default": True,
                    },
                },
            },
        ),
        Tool(
            name="caldav_get_today_events",
            description="Get all events for today",
            input_schema={
                "type": "object",
                "properties": {
                    "calendar_index": {
                        "type": "integer",
                        "description": "Index of the calendar (default: 0)",
                        "default": 0,
                    },
                },
            },
        ),
        Tool(
            name="caldav_get_week_events",
            description="Get all events for the week",
            input_schema={
                "type": "object",
                "properties": {
                    "calendar_index": {
                        "type": "integer",
                        "description": "Index of the calendar (default: 0)",
                        "default": 0,
                    },
                    "start_from_today": {
                        "type": "boolean",
                        "description": "Start from today (True) or from Monday (False)",
                        "default": True,
                    },
                },
            },
        ),
    ]

    return tools


async def call_tool(
    app_ctx: AppContext, name: str, arguments: Any
) -> Sequence[TextContent]:
    """Handle tool calls for CalDAV operations."""
    if not app_ctx or not app_ctx.client:
        config = get_caldav_config()
        missing = []
        if not config.get("url"):
            missing.append("CALDAV_URL")
        if not config.get("username"):
            missing.append("CALDAV_USERNAME")
        if not config.get("password"):
            missing.append("CALDAV_PASSWORD")

        message = "CalDAV client not configured."
        if missing:
            message += f" Missing variables: {', '.join(missing)}."
        else:
            message += (
                " Please configure CALDAV_URL, CALDAV_USERNAME, and CALDAV_PASSWORD."
            )

        return [
            TextContent(
                type="text",
                text=json.dumps({"error": message}, indent=2, ensure_ascii=False),
            )
        ]

    try:
        if name == "caldav_list_calendars":
            calendars = app_ctx.client.list_calendars()
            return [
                TextContent(
                    type="text",
                    text=json.dumps(calendars, indent=2, ensure_ascii=False),
                )
            ]

        elif name == "caldav_create_event":
            calendar_index = arguments.get("calendar_index", 0)
            title = arguments.get("title")
            description = arguments.get("description", "")
            location = arguments.get("location", "")
            start_time_str = arguments.get("start_time")
            end_time_str = arguments.get("end_time")
            duration_hours = arguments.get("duration_hours", 1.0)
            reminders = arguments.get("reminders")
            attendees = arguments.get("attendees")
            categories = arguments.get("categories")
            priority = arguments.get("priority")
            recurrence = arguments.get("recurrence")

            start_time = None
            if start_time_str:
                start_time = datetime.fromisoformat(
                    start_time_str.replace("Z", "+00:00")
                )

            end_time = None
            if end_time_str:
                end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))

            # Parse recurrence until date if provided
            if recurrence and recurrence.get("until"):
                until_str = recurrence["until"]
                try:
                    recurrence["until"] = datetime.fromisoformat(
                        until_str.replace("Z", "+00:00")
                    )
                except ValueError:
                    # Try date format
                    from contextlib import suppress

                    with suppress(ValueError):
                        recurrence["until"] = datetime.fromisoformat(until_str).date()

            result = app_ctx.client.create_event(
                calendar_index=calendar_index,
                title=title,
                description=description,
                location=location,
                start_time=start_time,
                end_time=end_time,
                duration_hours=duration_hours,
                reminders=reminders,
                attendees=attendees,
                categories=categories,
                priority=priority,
                recurrence=recurrence,
            )

            return [
                TextContent(
                    type="text",
                    text=json.dumps(result, indent=2, ensure_ascii=False),
                )
            ]

        elif name == "caldav_get_events":
            calendar_index = arguments.get("calendar_index", 0)
            start_date_str = arguments.get("start_date")
            end_date_str = arguments.get("end_date")
            include_all_day = arguments.get("include_all_day", True)

            start_date = None
            if start_date_str:
                start_date = datetime.fromisoformat(
                    start_date_str.replace("Z", "+00:00")
                )
            end_date = None
            if end_date_str:
                end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))

            events = app_ctx.client.get_events(
                calendar_index=calendar_index,
                start_date=start_date,
                end_date=end_date,
                include_all_day=include_all_day,
            )

            return [
                TextContent(
                    type="text",
                    text=json.dumps(events, indent=2, ensure_ascii=False),
                )
            ]

        elif name == "caldav_get_today_events":
            calendar_index = arguments.get("calendar_index", 0)
            events = app_ctx.client.get_today_events(calendar_index=calendar_index)

            return [
                TextContent(
                    type="text",
                    text=json.dumps(events, indent=2, ensure_ascii=False),
                )
            ]

        elif name == "caldav_get_week_events":
            calendar_index = arguments.get("calendar_index", 0)
            start_from_today = arguments.get("start_from_today", True)
            events = app_ctx.client.get_week_events(
                calendar_index=calendar_index, start_from_today=start_from_today
            )

            return [
                TextContent(
                    type="text",
                    text=json.dumps(events, indent=2, ensure_ascii=False),
                )
            ]

        elif name == "caldav_get_event_by_uid":
            uid = arguments.get("uid")
            calendar_index = arguments.get("calendar_index", 0)

            event = app_ctx.client.get_event_by_uid(uid=uid, calendar_index=calendar_index)

            if event:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(event, indent=2, ensure_ascii=False),
                    )
                ]
            else:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {"error": f"Event with UID {uid} not found"}, indent=2
                        ),
                    )
                ]

        elif name == "caldav_delete_event":
            uid = arguments.get("uid")
            calendar_index = arguments.get("calendar_index", 0)

            result = app_ctx.client.delete_event(uid=uid, calendar_index=calendar_index)

            return [
                TextContent(
                    type="text",
                    text=json.dumps(result, indent=2, ensure_ascii=False),
                )
            ]

        elif name == "caldav_search_events":
            calendar_index = arguments.get("calendar_index", 0)
            query = arguments.get("query")
            search_fields = arguments.get("search_fields")
            start_date_str = arguments.get("start_date")
            end_date_str = arguments.get("end_date")

            if not start_date_str or not end_date_str:
                raise ValueError(
                    "caldav_search_events requires both start_date and end_date arguments."
                )

            start_date = None
            if start_date_str:
                start_date = datetime.fromisoformat(
                    start_date_str.replace("Z", "+00:00")
                )

            end_date = None
            if end_date_str:
                end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))

            events = app_ctx.client.search_events(
                calendar_index=calendar_index,
                query=query,
                search_fields=search_fields,
                start_date=start_date,
                end_date=end_date,
            )

            return [
                TextContent(
                    type="text",
                    text=json.dumps(events, indent=2, ensure_ascii=False),
                )
            ]

        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": f"Unknown tool: {name}"}, indent=2),
                )
            ]

    except Exception as e:
        logger.error(f"Error calling tool {name}: {e}", exc_info=True)
        return [
            TextContent(
                type="text",
                text=json.dumps({"error": str(e)}, indent=2),
            )
        ]


async def handle_list_tools(
    ctx: ServerRequestContext[AppContext],
    params: types.PaginatedRequestParams | None,  # noqa: ARG001
) -> types.ListToolsResult:
    """MCP v2-compatible list-tools handler."""
    return types.ListToolsResult(tools=await list_tools(ctx.lifespan_context))


async def handle_call_tool(
    ctx: ServerRequestContext[AppContext],
    params: types.CallToolRequestParams,
) -> types.CallToolResult:
    """MCP v2-compatible tool-call handler."""
    content = await call_tool(
        ctx.lifespan_context,
        params.name,
        params.arguments or {},
    )
    return types.CallToolResult(content=list(content))


# Create server instance using the constructor-based handler API used by MCP v2.
app = Server(
    "mcp-caldav",
    lifespan=server_lifespan,
    on_list_tools=handle_list_tools,
    on_call_tool=handle_call_tool,
)


async def run_server(transport: str = "stdio", port: int = 8000) -> None:
    """Run the MCP CalDAV server with the specified transport.

    Supported transports:
    - "stdio": local MCP over stdin/stdout
    - "sse": legacy remote MCP over Server-Sent Events
    - "streamable-http": modern remote MCP over Streamable HTTP at /mcp
    """
    if transport == "sse":
        import secrets

        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import PlainTextResponse
        from starlette.routing import Mount, Route

        class BearerAuthMiddleware:
            def __init__(self, asgi_app: Any):
                self.app = asgi_app

            async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
                # Only protect the MCP endpoints. Lifespan and unrelated HTTP
                # routes continue through unchanged.
                if scope["type"] == "http" and (
                    scope.get("path") == "/sse"
                    or scope.get("path", "").startswith("/messages/")
                ):
                    expected_key = os.getenv("MCP_API_KEY")
                    if not expected_key:
                        response = PlainTextResponse(
                            "Server authentication is not configured",
                            status_code=500,
                        )
                        await response(scope, receive, send)
                        return

                    headers = dict(scope.get("headers", []))
                    authorization = headers.get(b"authorization", b"").decode()

                    expected_authorization = f"Bearer {expected_key}"
                    if not secrets.compare_digest(
                        authorization, expected_authorization
                    ):
                        response = PlainTextResponse(
                            "Unauthorized",
                            status_code=401,
                        )
                        await response(scope, receive, send)
                        return

                await self.app(scope, receive, send)

        sse = SseServerTransport("/messages/")

        async def handle_sse(request: Request) -> None:
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await app.run(
                    streams[0], streams[1], app.create_initialization_options()
                )

        starlette_app = Starlette(
            debug=False,
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/messages/", app=sse.handle_post_message),
            ],
        )

        starlette_app = BearerAuthMiddleware(starlette_app)

        import uvicorn

        config = uvicorn.Config(starlette_app, host="0.0.0.0", port=port)
        server = uvicorn.Server(config)
        await server.serve()

    elif transport in {"streamable-http", "streamable_http", "http"}:
        import secrets

        from starlette.responses import PlainTextResponse

        class BearerAuthMiddleware:
            def __init__(self, asgi_app: Any):
                self.app = asgi_app

            async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
                # Protect only the MCP endpoint. This leaves unrelated paths
                # available for platform probes while keeping MCP private.
                if scope["type"] == "http" and (
                    scope.get("path") == "/mcp"
                    or scope.get("path", "").startswith("/mcp/")
                ):
                    expected_key = os.getenv("MCP_API_KEY")
                    if not expected_key:
                        response = PlainTextResponse(
                            "Server authentication is not configured",
                            status_code=500,
                        )
                        await response(scope, receive, send)
                        return

                    headers = dict(scope.get("headers", []))
                    authorization = headers.get(b"authorization", b"").decode()

                    expected_authorization = f"Bearer {expected_key}"
                    if not secrets.compare_digest(
                        authorization, expected_authorization
                    ):
                        response = PlainTextResponse(
                            "Unauthorized",
                            status_code=401,
                        )
                        await response(scope, receive, send)
                        return

                await self.app(scope, receive, send)

        # The current MCP Python SDK exposes Streamable HTTP directly from the
        # low-level Server instance. Stateless + JSON response is suitable for
        # a small remote MCP behind Render and does not require sticky sessions.
        try:
            starlette_app = app.streamable_http_app(
                streamable_http_path="/mcp",
                stateless_http=True,
                json_response=True,
                host="0.0.0.0",
                debug=False,
            )
        except AttributeError as exc:
            raise RuntimeError(
                "The installed 'mcp' Python SDK is too old for Streamable HTTP. "
                "Update the MCP dependency and uv.lock, then redeploy."
            ) from exc

        starlette_app = BearerAuthMiddleware(starlette_app)

        import uvicorn

        config = uvicorn.Config(starlette_app, host="0.0.0.0", port=port)
        server = uvicorn.Server(config)
        await server.serve()

    else:
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream, write_stream, app.create_initialization_options()
            )
