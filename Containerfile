# The runtime image. Stage one builds a wheel; the final image contains the
# installed package and nothing else — no source tree, no build tools.
# The MCP program under mcp/ enters the build context too: the wheel build copies
# it into the package, which is how the participant surface serves /mcp.zip
# without a source tree.
FROM python:3.13-slim AS build
COPY . /src
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /wheels /src

FROM python:3.13-slim
# A fixed UID so an operator can chown a volume before handing it over, and
# predict who owns what afterwards.
RUN useradd --system --uid 999 --home-dir /var/lib/simple-a2a --shell /usr/sbin/nologin simplea2a \
    && mkdir -p /var/lib/simple-a2a \
    && chown simplea2a:simplea2a /var/lib/simple-a2a

COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

# Which build this is. The package version does not move between commits, so
# without this nobody can answer "what is running here?" — the one question
# every deployment eventually asks. Deliberately not a SIMPLE_A2A_* name:
# that namespace belongs to the operational parameters, and a build stamp is
# not one of them.
ARG A2A_BUILD="unknown"
ENV A2A_BUILD=${A2A_BUILD}
# When this image was built, ISO 8601 in UTC, passed in by whoever builds it. Left
# empty, /build says null rather than the moment the container happened to start.
ARG A2A_BUILD_AT=""
ENV A2A_BUILD_AT=${A2A_BUILD_AT}

USER simplea2a
EXPOSE 8251 8252 8253

# The image's own claim about itself. It asks every surface that is configured
# to be on, reading the configuration rather than a fixed port: wired to 8251, a
# check would call the container unhealthy forever if the operator switched the
# participant surface off — a perfectly correct configuration — and the platform
# would restart a working service in a loop. `healthy` means the process
# answers, and deliberately nothing more.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["python", "-m", "simple_a2a.probe"]

# Inside the container the boundary is the container, so bind all interfaces:
# no port is published unless the operator publishes it. Set as environment
# rather than as arguments — an argument would win over the operator's compose
# file and make the binding impossible to change or a surface impossible to
# switch off.
ENV SIMPLE_A2A_BIND="0.0.0.0" \
    SIMPLE_A2A_DATA_DIR="/var/lib/simple-a2a"

ENTRYPOINT ["simple-a2a"]
