
import asyncio
import os
import json

from dotenv import load_dotenv
from google import genai
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY is missing from .env")

client = genai.Client(api_key=api_key)
MODEL = "gemini-3.5-flash"


async def main():
    server_params = StdioServerParameters(
        command="python",
        args=["server.py"],
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tools_response = await session.list_tools()

            print("\n✈️ Welcome to Flight Search AI!")
            print("Connected to MCP server successfully.")
            print(
                "Available tools:",
                [tool.name for tool in tools_response.tools]
            )
            print("Search flights using city names or airport codes.")
            print("Examples: KUL to Bangkok, SIN to KUL")
            print("Type 'exit' to quit.")

            declarations = [
                types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description or "",
                    parameters=tool.inputSchema,
                )
                for tool in tools_response.tools
            ]

            while True:
                user_prompt = input(
                    "\nAsk about flights (type 'exit' to quit): "
                ).strip()

                if user_prompt.lower() == "exit":
                    print("Goodbye! Safe travels!")
                    break

                if not user_prompt:
                    print("Please enter a question.")
                    continue

                prompt = (
                    "You are a helpful flight-search assistant. "
                    "Use the search_flights tool whenever the user asks "
                    "about flight options or prices. "
                    "Recognize common city names and airport codes: "
                    "KL/KUL means Kuala Lumpur, SIN means Singapore, "
                    "BKK means Bangkok, and PEN means Penang. "
                    "Extract the origin and destination from the user's request. "
                    "If the origin or destination is missing or unclear, "
                    "ask a clarifying question instead of guessing.\n\n"
                    f"User request: {user_prompt}"
                )

                response = client.models.generate_content(
                    model=MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[
                            types.Tool(
                                function_declarations=declarations
                            )
                        ]
                    ),
                )

                calls = response.function_calls or []

                if not calls:
                    print("\nGemini:", response.text)
                    continue

                tool_results = []

                for call in calls:
                    if call.name != "search_flights":
                        continue

                    arguments = dict(call.args or {})

                    if (
                        not arguments.get("origin")
                        or not arguments.get("destination")
                    ):
                        print(
                            "\nGemini: Please provide both your "
                            "departure city and destination."
                        )
                        continue

                    print(f"\nCalling MCP tool: {call.name}")

                    result = await session.call_tool(
                        call.name,
                        arguments=arguments,
                    )

                    tool_results.append({
                        "tool": call.name,
                        "arguments": arguments,
                        "result": [
                            item.text if hasattr(item, "text")
                            else str(item)
                            for item in result.content
                        ],
                    })

                if not tool_results:
                    continue

                follow_up = client.models.generate_content(
                    model=MODEL,
                    contents=(
                        f"User request: {user_prompt}\n"
                        f"MCP tool results: {json.dumps(tool_results)}\n"
                        "Answer naturally using the tool results. "
                        "Identify the cheapest flight when comparing options. "
                        "If no flights are returned, clearly say no matching "
                        "flights were found. "
                        "State that these are mock results, not live prices."
                    ),
                )

                print("\nGemini:", follow_up.text)


if __name__ == "__main__":
    asyncio.run(main())
