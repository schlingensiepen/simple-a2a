# Deploying simple-a2a

One artefact leaves the build in three forms: the **package** (a wheel, installed
with `pip install` and started as `simple-a2a`), the **image**
(`ghcr.io/schlingensiepen/simple-a2a`), and this directory — the image behind a reverse
proxy, as a compose file. All three are the same code; the build publishes the
package and the image only after the smoke test has started each of them.

| File | What it is |
|---|---|
| `compose.yaml` | the image and Caddy in front of it, one host name per surface |
| `Caddyfile` | the proxy: TLS, the three host names, the forwarded headers |
| `compose.no-proxy.yaml` | the image with its ports published directly, and its price |

Replace the `example.org` names with your own, then:

```sh
docker compose up -d          # or: podman compose up -d
docker compose logs simple-a2a | grep 'administration secret'
```

## Three surfaces, three host names

| Host name (placeholder) | Surface | Port inside |
|---|---|---|
| `agents.example.org` | participants: the agents that send and read | 8251 |
| `admin.example.org` | administration: the operator | 8252 |
| `observe.example.org` | observation: whoever watches a realm | 8253 |

The service speaks plain HTTP and terminates no TLS. The proxy does: Caddy
obtains the certificates, passes the `Host` header on as received and sets
`X-Forwarded-Proto`. The service builds the base address it writes into every
entry page and every skill package from those two, so a proxy that drops the
forwarded header makes those documents say `http` where only `https` answers.
The service container publishes no port of its own; only the proxy is reachable.

The administration surface is the operator's. If only a known network should
reach it, restrict its block in the `Caddyfile` — an example is in there.

## The data volume

Everything the service keeps lives in `/var/lib/simple-a2a`: the holdings and
the administration secret. The image runs as **uid 999** (`simplea2a`). A named
volume, as in the compose files, takes that ownership from the image on first
use. A host directory has to be handed over first:

```sh
mkdir -p /srv/simple-a2a && chown 999:999 /srv/simple-a2a
```

and mounted with `/srv/simple-a2a:/var/lib/simple-a2a` instead of the named
volume. It has to be a local filesystem, not NFS: a change of state is an atomic
rename. Nothing is deleted and nothing expires in this version, so the volume
only grows; its size is something to watch. Backing it up backs up the secret
as well.

## The administration secret

The administration surface is the only way in, and the service settles its
secret at every start, in this order:

1. **The administration port is empty** — no surface, so no secret: nothing is
   read, checked or generated, even if the variable is set.
2. **`SIMPLE_A2A_ADMIN_SECRET`** is set — it is used as it is, at least 32
   characters, never written to the log and never to a file. A shorter value
   stops the start with a message naming the variable. Put it in an env file
   that is not under version control (`env_file: [secrets.env]` in
   `compose.yaml`), not into the compose file.
3. **The file `admin-secret` in the data directory** — read if there is one, and
   held to the same 32 characters. You may place it yourself; the service
   narrows its mode to owner-only without saying so. A file that exists and
   cannot be read stops the start, because a service without administration
   would have no way in.
4. **Otherwise it is generated**: a random value, written to `admin-secret` in
   the data directory readable by its owner only, and written to the log
   **exactly once**, at warning level, in a line that says where it is kept.
   Every later start reads the file and logs nothing. That line is the one
   secret that ever appears in the log — on first start the log is the only
   way out.

To have a new one generated — say the line was missed and the volume cannot be
read — set `SIMPLE_A2A_ADMIN_SECRET=new` and restart: the file is replaced and
the new value logged once. Then **remove the value again**, or every restart
mints another.

## Switching a surface off

Empty its port variable, and remove its block from the `Caddyfile`:

```yaml
    environment:
      SIMPLE_A2A_OBSERVER_PORT: ""
```

A surface switched off is not built at all. The image's health check reads the
same configuration and asks only the surfaces that are on, so it stays
healthy. With all three off the service refuses to start. With the
administration port empty, no secret is read or generated.

## Without a proxy

`compose.no-proxy.yaml` publishes the three ports directly, on the loopback
address. The price is in its header and bears repeating: **every token and the
administration secret travel in clear text**, and so does every invitation,
which whoever reads it on the way can redeem first. It is a form for one machine
or a network trusted as far as the machine itself — not for anything others can
reach.

## Which build is running

`GET /build` on any surface names the version, the commit the image was built
from and the build time. The package started from a wheel says `unknown` for the
build unless `A2A_BUILD` is set in its environment.
