import asyncio
import os
import shutil

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    npx_path = shutil.which("npx.cmd") or shutil.which("npx")

    if not npx_path:
        print("Could not find npx. Please check your Node.js installation.")
        return

    server_params = StdioServerParameters(
        command=npx_path,
        args=["-y", "@dangahagan/weather-mcp@latest"],
        env={
            **os.environ,
            "WEATHER_UNITS": "metric",
        },
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            print("Connected to Weather MCP successfully!")

            tools_result = await session.list_tools()

            print("\nAvailable Weather MCP Tools:")

            for tool in tools_result.tools:
                print(f"\nTool: {tool.name}")
                print(f"Description: {tool.description}")
                print(f"Arguments: {tool.inputSchema}")

            result = await session.call_tool(
                "get_current_conditions",
                arguments={
                    "city_name": "Kuala Lumpur, Malaysia"
                },
            )

            print("\nKuala Lumpur Weather Result:\n")

            for item in result.content:
                if hasattr(item, "text"):
                    print(item.text)

            if result.isError:
                print("\nThe weather tool returned an error.")


if __name__ == "__main__":
    asyncio.run(main())