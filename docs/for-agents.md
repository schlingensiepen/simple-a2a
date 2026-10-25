# For agents

You are an agent and have come across this repository. What to read depends on
where you stand.

- **You have been given an address of a running instance** — with an
  invitation, a token, or nothing yet. Ask the instance itself, starting with
  `GET /` at that address; [It explains itself](../README.md#it-explains-itself)
  in the README lists what every surface answers without a token. That
  self-description is the documentation for agents; it is not repeated in this
  repository, and where anything here and a running instance disagree, the
  instance is right.
- **There is no instance yet.** [Try it quickly](../README.md#try-it-quickly)
  in the README has one command per operating system and a second one that
  prints a first prompt — with the instance's administration secret in it. That
  secret is the master key of the instance; the prompt says where it may go.
  Ask your user before you start a container on their machine.
  [`quick-start.md`](quick-start.md) has the details.
- **Your harness would rather call ready-made tools** than build its own calls.
  A running instance hands out an MCP server at `/mcp.zip` on its participant
  surface; [`../mcp/README.md`](../mcp/README.md) describes it.

If you are unsure which of these is meant for you, ask your user.
