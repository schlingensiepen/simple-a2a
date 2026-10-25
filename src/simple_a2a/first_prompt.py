"""The one helper beside the service: `simple-a2a first-prompt`.

It prints a first prompt for an agent — connect to the administration surface,
read its self-description, create a realm and a team, hand the invitations back —
with the administration secret of this instance written into it, and with where
that secret may go and where it may not. It is meant to be run inside the
running container, as `podman exec simple-a2a simple-a2a first-prompt` or the same
with docker, `wslc` or Apple's `container`: in there the environment and the data
directory are the service's own, so what this reads is what the service is using.

There is still no command line for operations. Everything an operator *does*
goes through the three surfaces or through the means of their host; this does
nothing to the service. It reads the secret, the same two places in the same order
the service reads them at its start (`core.secret.find`), and it never settles one:
it generates nothing and writes no file. Where there is no secret to be found —
administration switched off, or the service has not started yet — it says so on
standard error and exits non-zero rather than inventing one.

**The address is an argument, and it is the one argument there is.** The service's
configuration is eight environment variables and no flags, and that stays so,
because this address is not configuration of the service: it is the address the
*agent* will use, and that is something the service cannot know. Inside the
container the surface is on 8252; outside, the operator may have published it on
any host port, and only the operator knows which. The administration guide's part
on first access says it of every pair of address and secret — the address is
yours to supply. Supplying it here is where that happens. The default is the
quick start's own: the loopback address and the port the image serves on.
"""

from __future__ import annotations

import sys

from simple_a2a.core import config, secret
from simple_a2a.core.paths import Layout

#: The name under which `__main__` dispatches here.
SUBCOMMAND = "first-prompt"

#: Where the administration surface is when nothing else was said: this machine,
#: the port the image serves it on. The quick start publishes it exactly there.
DEFAULT_ADDRESS = "http://127.0.0.1:8252"

#: One address: the administration surface, as the agent will reach it.
USAGE = f"usage: simple-a2a {SUBCOMMAND} [ADMINISTRATION_ADDRESS]   (default {DEFAULT_ADDRESS})"


def address_from(arguments: list[str]) -> str:
    """The address the prompt names, from the arguments or the default.

    A trailing slash is dropped so that the paths the prompt appends read as the
    guide writes them. Anything that is not an `http` or `https` address is refused
    — a bare host and port would make the agent guess the scheme, and guessing is
    the one thing the pair of address and secret cannot survive.
    """
    if not arguments:
        return DEFAULT_ADDRESS
    if len(arguments) > 1:
        raise ValueError(f"one address at most, got {len(arguments)}")
    given = arguments[0].strip()
    if not given.startswith(("http://", "https://")):
        raise ValueError(f"{arguments[0]!r} is not an http or https address")
    given = given.rstrip("/")
    if given in ("http:", "https:"):
        raise ValueError(f"{arguments[0]!r} names no host")
    return given


def render(address: str, value: str) -> str:
    """The prompt, ready to paste.

    Written as an instruction from the operator to their own agent, and as an
    offer rather than a script: it names what to read, in which order, and what to
    hand back, and leaves the names and the purpose to a conversation — nothing
    created on the administration surface can be deleted, so a name typed from
    memory is the one mistake worth a question. The terms are the surface's own:
    realm, team, invitation, realm master.

    The secret stands in the prompt on purpose. An agent that has to administer an
    instance needs its key, and a prompt that pointed at a file instead would send
    the agent looking for it. What the prompt does instead is say where the key
    may go — the Authorization header of requests to this one address — and that
    everywhere else is out of the question.
    """
    return f"""I run a simple-a2a instance: a server over which software agents talk to each other. I would like you to set it up for me so that agents can join.

Its administration surface is at {address}

Please go about it in this order:

1. Read the surface's self-description first. GET {address}/ answers without a token and lists what the surface offers; the part {address}/guide/first-access walks from a bare start to a working team, in order. Nothing created on this surface can be deleted, so read before the first call that creates something. Where this prompt and the self-description disagree, the self-description is right — tell me if they do.

2. Create a realm (POST {address}/realms with realm_name) and one team in it (POST {address}/realms/{{realm}}/teams with team_name and team_purpose). If I have not told you the names and the team's purpose, ask me before you create them: a mistyped name stays forever.

3. Obtain one invitation into that team for each agent that should join (POST {address}/realms/{{realm}}/teams/{{team}}/invitations with member_name, member_mission and display_name). Each invitation is shown exactly once, in the answer that creates it. Hand the invitations back to me exactly as answered, each with the member name it was issued for; whoever redeems one becomes a realm master of the team. I will pass them on to the agents together with the address of the participant surface — you need not do that.

The administration secret of this instance is:

    {value}

It is the master key of this instance: whoever holds it can do anything here. Use it only as the header `Authorization: Bearer <secret>` on requests to {address}, and nowhere else. Do not put it into a message to anyone, into a file that is shared or committed, into a note, a log, a prompt for another agent, or a request to any other address. If you are unsure whether something is such a place, ask me first.
"""


def main(arguments: list[str]) -> int:
    """Print the prompt, or say on standard error why there is none."""
    try:
        address = address_from(arguments)
    except ValueError as exc:
        print(f"simple-a2a {SUBCOMMAND}: {exc}\n{USAGE}", file=sys.stderr)
        return 2

    try:
        resolved = config.load()
        found = secret.find(resolved, Layout(root=resolved.data_dir))
    except config.ConfigError as exc:
        # The service could not have started with this configuration either; the
        # parameter is named, as it would be at the start.
        print(f"simple-a2a {SUBCOMMAND}: {exc}", file=sys.stderr)
        return 2

    if found is None:
        file = Layout(root=resolved.data_dir).admin_secret
        if not resolved.administration_is_on:
            print(
                f"simple-a2a {SUBCOMMAND}: the administration surface is switched off "
                f"({config.ADMIN_PORT} is empty), so this instance has no administration "
                f"secret and no first prompt. Give {config.ADMIN_PORT} a port, or unset it "
                "for the default, and start the service again.",
                file=sys.stderr,
            )
        elif resolved.regenerate_admin_secret:
            # `new` asks the service for a secret; it is not one. The file it would
            # have written is missing, so the service has not started with it yet.
            print(
                f"simple-a2a {SUBCOMMAND}: no administration secret yet — {config.ADMIN_SECRET} "
                f"is set to {config.REGENERATE!r}, which asks the service for a new one and is "
                f"not one itself, and there is no file {file}. The service writes that file "
                "when it starts with this value; run this beside the running service, in its "
                "environment, with its data directory.",
                file=sys.stderr,
            )
        else:
            print(
                f"simple-a2a {SUBCOMMAND}: no administration secret yet — {config.ADMIN_SECRET} "
                f"is not set and there is no file {file}. The service writes that file at its "
                "first start; run this beside a running service, in its environment, with its "
                "data directory.",
                file=sys.stderr,
            )
        return 1

    sys.stdout.write(render(address, found.value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
