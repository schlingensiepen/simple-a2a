# The runtime image. Stage one builds a wheel; the final image contains the
# installed package and nothing else — no source tree, no build tools.
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

USER simplea2a
EXPOSE 8251 8252 8253

# The image's own claim about itself. It asks the participant surface, which
# is the one an operator publishes; `healthy` means the process answers, and
# deliberately nothing more.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8251/health', timeout=3).status==200 else 1)"

# Inside the container the boundary is the container, so bind all interfaces:
# no port is published unless the operator publishes it. Set as environment
# rather than as arguments — an argument would win over the operator's compose
# file and make the binding impossible to change or a surface impossible to
# switch off.
ENV SIMPLE_A2A_BIND="0.0.0.0" \
    SIMPLE_A2A_DATA_DIR="/var/lib/simple-a2a"

ENTRYPOINT ["simple-a2a"]
