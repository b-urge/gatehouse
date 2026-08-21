"""D1 smoke test: proves Gemini 3.5 Flash + ADK + Vertex AI are wired.

If the model id 404s, confirm region us-central1 and check the exact Flash
model name in Vertex Model Garden — the hackathon requires Gemini 3.5+.
"""

from google.adk.agents import Agent

root_agent = Agent(
    name="hello_gatehouse",
    model="gemini-3.5-flash",
    description="D1 smoke-test agent for the Gatehouse build.",
    instruction=(
        "You are the Gatehouse hello-world. Reply in one short sentence "
        "and mention you are running on Vertex AI."
    ),
)
