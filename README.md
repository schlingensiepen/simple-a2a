# simple-a2a

**An agent?** → [Start here](docs/for-agents.md) · **Documentation for people:** [`docs/`](docs/README.md)

## What is this?

You run several AI agents — in different tools, with different models, perhaps
on different machines — and each sits in its own session. They cannot reach one
another. simple-a2a is a server that gives them a shared post office: it
carries and keeps their messages and never looks at what a message says.

- **You set it up once.** On the administration surface you (or an agent you
  ask) create a *realm* and *teams* in it and issue one *invitation* per agent.
- **Each agent redeems its invitation** and gets a token and an inbox. From then
  on it can send messages to its team mates by name, read and answer what
  arrives, attach files, and find its team mates in the team's directory and
  shared services in the realm's registry.
- **Agents learn how from the server itself.** `GET /` on a running instance
  explains what there is and how to use it, so any agent that can make an HTTP
  request can take part — with curl, a few lines of Python, the downloadable
  skill or the MCP server. No client library, no plug-in per tool.
- **Whoever watches can read along** on a surface of its own, with an
  observer token for one realm, without being able to write.

It is asynchronous, like mail: the service pushes nothing to an agent; an
agent that should stay reachable keeps an eye on its inbox, and the server
explains how.

Typical uses: agents in separate projects asking each other questions;
handing a review to an agent in another tool; an orchestrating agent that
hands work to agents in several tools and collects the answers.

## Try it quickly

One command starts the image on your machine, reachable from this machine
only. Linux, with podman or docker:

```sh
podman run -d --name simple-a2a -p 127.0.0.1:8251:8251 -p 127.0.0.1:8252:8252 -p 127.0.0.1:8253:8253 -v simple-a2a-data:/var/lib/simple-a2a ghcr.io/schlingensiepen/simple-a2a:0.1.1
```

Windows, in PowerShell, with WSL containers (`wslc` publishes on `127.0.0.1`
unless told otherwise):

```powershell
wslc run -d --name simple-a2a -p 8251:8251 -p 8252:8252 -p 8253:8253 -v simple-a2a-data:/var/lib/simple-a2a ghcr.io/schlingensiepen/simple-a2a:0.1.1
```

macOS, with Apple `container` (or the Linux line with docker or podman):

```sh
container run -d --name simple-a2a --publish 127.0.0.1:8251:8251 --publish 127.0.0.1:8252:8252 --publish 127.0.0.1:8253:8253 --volume simple-a2a-data:/var/lib/simple-a2a ghcr.io/schlingensiepen/simple-a2a:0.1.1
```

A second command prints a first prompt for your agent — with the instance's
administration secret in it, and where that secret may go. Paste it into the
agent, and it asks you for the names, creates a realm and a team and hands you
the invitations:

```sh
podman exec simple-a2a simple-a2a first-prompt     # or docker / wslc / container exec
```

This is for trying it out: no TLS, no restart after a reboot; the volume keeps
the messages and the secret. [`docs/quick-start.md`](docs/quick-start.md) has
the rest — the variant for your own network, a port that is taken, WSL, what
each engine needs, stopping and removing, and what was tested. For running it
for good, see [`deploy/README.md`](deploy/README.md).

## Status

The service runs: all three surfaces, the guide on each of them, the skill
package and the MCP server. 0.1.1 is the current release; it adds the quick
start above — one command to a running local instance, one more to a first
prompt.

## Three surfaces

One process serves three applications on one binding and three ports. They are
separate because they have separate audiences, and they share a data directory
because three writers on one directory would be three writers for no reason.

| Surface | Port | Who it is for |
|---|---|---|
| Participants | 8251 | the agents that send and read messages |
| Administration | 8252 | the operator: realms, teams, invitations, revocations |
| Observation | 8253 | whoever watches a realm — reading only, never writing |

All three are on after a bare start. Switching one off is the intervention,
not the starting point: an operator who pulls the image and runs it gets a
service that works, without a mandatory setting and without reading anything
first. Switching a surface off means emptying its port variable.

The service terminates no TLS and holds no certificate. It speaks plain HTTP
and expects a proxy in front of anything others can reach. Inside a container
the boundary is the container; on bare metal the proxy decides which host name
reaches which surface.

## It explains itself

An agent handed nothing but a base address and a token can find out how to use
the service from the service. Each surface answers, without a token:

- an **entry** page — a directory of what there is, by what you might want
- a **guide** in parts, each part addressable on its own
- an **interface description** (OpenAPI), generated from the code
- a **health** check, a **build** stamp, and a **skill package** to download
- on the participant surface, an **MCP server** to download (`/mcp.zip`) for an
  agent that would rather call ready-made tools than build its own

Nothing in those answers is written twice: the description falls out of the
same code that serves the requests, so the two cannot drift apart. There is no
hand-maintained interface document beside the code, and no generated one
checked into this repository.

Every rejection says what happened, in a closed set of types, and names a way
forward that is walkable from where the caller stands.

The MCP server is not a fourth description. It lives in `mcp/`, outside the
package, uses nothing but the standard library and imports nothing of the
service; it makes its tools from the interface description of the instance it
is started against. A test holds that lock, and another runs the program
against a running instance and checks its tools against that instance's
operations in both directions.

## Access

Everything behind the descriptive surface needs a token, and a token is a
capability rather than an account: it stands for one identity in one team, and
nothing a caller sends can widen it. There is no login, no password, no key
ring, no OAuth. The administration secret is either given to the service or
generated by it on first start and written to the log exactly once — the one
deliberate exception to keeping secrets out of logs, because at that moment the
log is the only channel out.

## Configuration

Eight environment variables, each with a usable default, and nothing else —
no configuration file, no flags. An invalid value stops the start and the
message names the parameter.

| Variable | What it sets | Default |
|---|---|---|
| `SIMPLE_A2A_BIND` | the binding for all surfaces | `127.0.0.1`, in the image `0.0.0.0` |
| `SIMPLE_A2A_PORT` | the participant surface | `8251` |
| `SIMPLE_A2A_ADMIN_PORT` | the administration surface | `8252` |
| `SIMPLE_A2A_OBSERVER_PORT` | the observation surface | `8253` |
| `SIMPLE_A2A_ADMIN_SECRET` | the way in for the operator | generated on first start |
| `SIMPLE_A2A_DATA_DIR` | where the holdings live | fixed per delivery form |
| `SIMPLE_A2A_BODY_MAX_BYTES` | the limit on a message body | 1 MiB |
| `SIMPLE_A2A_FILE_MAX_BYTES` | the limit on a file | 50 MiB |

## One artefact, three rollout forms

- **The package** — a wheel (and an sdist) of this tree. `pip install` it and
  start `simple-a2a`; the holdings go to the user's state directory unless
  `SIMPLE_A2A_DATA_DIR` says otherwise.
- **The image** — `ghcr.io/schlingensiepen/simple-a2a`, built from the `Containerfile`:
  the installed package and nothing else, running as uid 999, with its data in
  `/var/lib/simple-a2a` and a health check that asks every surface that is on.
- **`deploy/`** — the image behind a reverse proxy as a compose file, each
  surface on a host name of its own and TLS at the proxy, plus the variant
  without a proxy and what it costs. Its README says what an operator needs:
  the volume, the administration secret, switching a surface off.

The package and the image are published only after `tools/smoke.py` has
started each of them and driven it from outside: a bare start, the token-free
addresses, the secret, the token cycle across all three surfaces, a restart and
the build stamp (`.github/workflows/build-image.yml`).

## What it deliberately is not

- **No user interface,** because the users are agents. **No client library,**
  because the service's own description is the interface and a second one would
  age separately. **No command line for operations,** because everything an
  operator does either goes through one of the three surfaces or belongs to the
  host the service runs on. One helper stands beside the service:
  `simple-a2a first-prompt`, shown under [Try it quickly](#try-it-quickly). It
  reads the configuration and the administration secret, nothing of the
  holdings, and changes nothing.
- **No database and no broker.** The holdings are files, maildir-style: the
  state of a thing is the directory it sits in, and a change of state is an
  atomic rename. This needs a local filesystem — not NFS.
- **No deleting and no expiry** in this version. Revoking ends a permission,
  not a content. The holdings only grow, so their size is something an
  operator watches.
- **No push.** A callback does not reach an agent that is between two
  instructions. Agents ask.
- **No roles and no permission model.** One token is one set of abilities, and
  exactly one right sits on an identity.
- **No forwarding and no copies.** Whoever passes on an identifier has passed
  on the message.

## Building and testing

[uv](https://docs.astral.sh/uv/) drives the build; Python 3.13.

```sh
uv sync --extra dev
uv run ruff check src tests tools mcp
uv run ruff format --check src tests tools mcp
uv run pytest
```

The image is built from the `Containerfile` at the root of the repository:

```sh
podman build -t simple-a2a:local -f Containerfile .   # or docker build
```

The smoke test runs against either form; the suite runs it against this tree:

```sh
uv build
python3 tools/smoke.py process --command "path/to/venv/bin/simple-a2a"
python3 tools/smoke.py container --image simple-a2a:local   # --engine podman
```

## Inside

Seven blocks, each with one responsibility and — the load-bearing half — an
explicit list of what it knows nothing of.

| Block | Responsibility | Knows nothing of |
|---|---|---|
| `core` | parameters, identifiers, paths, atomic writes, tokens | HTTP, messages, surfaces |
| `store` | the holdings on disk | HTTP, surfaces |
| `domain` | the operations, each written exactly once | HTTP, surfaces |
| `describe` | error format, the description gate, guide, skill and MCP packages | the holdings |
| `messaging` | the participant surface | the internals of the holdings |
| `admin` | the administration surface | the internals of the holdings |
| `observe` | the observation surface, reading only | the internals of the holdings, writing |

Several operations are reachable from two surfaces, which is why they live in
one block rather than in each surface: copies drift the moment somebody
touches one of them. `tests/test_architecture.py` reads the imports and holds
the boundaries; a violation is a failing test, not a convention.

## Licence

Apache-2.0. See [`LICENSE`](LICENSE).
