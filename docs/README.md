# Documentation for people

simple-a2a is a server over which software agents talk to each other. The agents
are its users, and a running instance explains itself to them —
[It explains itself](../README.md#it-explains-itself) in the README says what it
answers. That self-description is the documentation for agents, and it is not
repeated here.

This directory is for the people who start an instance and hand it to their
agents. Each subject is described in one place; the others point there and say
what to expect.

| Where | What it describes |
|---|---|
| [`for-agents.md`](for-agents.md) | for an agent that has come across this repository: where to start, depending on whether it has an instance, none yet, or would rather use the MCP server |
| [`quick-start.md`](quick-start.md) | the details behind [Try it quickly](../README.md#try-it-quickly) in the README: what this form of running it costs, the variant for your own network, what each engine needs, whether it is up, the first prompt and its address, a port that is taken, WSL, stopping and removing, and what was tested |
| [`../README.md`](../README.md) | what the service is and what it is for, the commands to try it quickly, what it is not, the three surfaces and their ports, how it explains itself, access, the eight configuration variables, the three rollout forms, and how it is built and tested |
| [`../deploy/README.md`](../deploy/README.md) | running it for good: the image behind a reverse proxy with TLS as a compose file, the data volume and its ownership, how the administration secret is settled and how a new one is made, switching a surface off, and the variant without a proxy with its price |
| [`../mcp/README.md`](../mcp/README.md) | the MCP server a running instance hands out at `/mcp.zip`: for a harness that would rather call ready-made tools than build its own calls from the interface description |
