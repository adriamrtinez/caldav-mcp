                    start_date_str.replace("Z", "+00:00")
                )

            end_date = None
            if end_date_str:
                end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))

            events = ctx.client.search_events(
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


async def run_server(transport: str = "stdio", port: int = 8000) -> None:
    """Run the MCP CalDAV server with the specified transport."""
    if transport == "sse":
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import PlainTextResponse
        from starlette.routing import Mount, Route

        class BearerAuthMiddleware:
            def __init__(self, app):
                self.app = app

            async def __call__(self, scope, receive, send):
                if scope["type"] == "http":
                    expected_key = os.getenv("MCP_API_KEY")

                    headers = dict(scope.get("headers", []))
                    authorization = headers.get(b"authorization", b"").decode()

                    if not expected_key:
                        response = PlainTextResponse(
                            "Server authentication is not configured",
                            status_code=500,
                        )
                        await response(scope, receive, send)
                        return

                    if authorization != f"Bearer {expected_key}":
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
    else:
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream, write_stream, app.create_initialization_options()
            )
