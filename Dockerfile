# syntax=docker/dockerfile:1
#
# Layers are ordered from least to most frequently changing, so that in a registry (e.g. Harbor)
# a new release usually only adds the small app-code layer:
#   1. wolfi-base                minimal glibc distro, patched daily (no util-linux/perl/ncurses CVE baggage)
#   2. python + runtime libs     changes only when the base is bumped or apk packages are patched
#   3. Python virtualenv         changes only when uv.lock changes
#   4. models + feature lists    changes only when the models are retrained
#   5. app code and images       changes every release
#
# Rebuild regularly (and bump the digest below) to pick up security fixes.

FROM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv

FROM cgr.dev/chainguard/wolfi-base@sha256:360896efb0753a5701c48f860e17130c205eae5a264797aa3e7ea126ee2923a7 AS runtime
# RDKit's drawing module links against libXrender, libXext, libX11 and libexpat
# The user is added by hand rather than with adduser, and the ldconfig cache is dropped, so this
# layer is byte-identical across rebuilds (adduser stamps /etc/shadow with the current date)
RUN apk add --no-cache python-3.12 libxrender libxext libx11 expat \
    && rm -f /var/cache/ldconfig/aux-cache \
    && echo "streamlit:x:1000:1000::/home/streamlit:/bin/sh" >> /etc/passwd \
    && echo "streamlit:x:1000:" >> /etc/group \
    && mkdir -p /home/streamlit && chown 1000:1000 /home/streamlit

FROM runtime AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_PYTHON=/usr/bin/python3.12 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-dev --no-install-project \
    # Test suites are never imported at runtime
    && find /opt/venv -depth -type d \( -name tests -o -name __pycache__ \) -exec rm -rf {} + \
    # pyarrow (a streamlit dependency) ships optional Flight RPC and S3 filesystem support (~45 MB) that
    # nothing else links against; pyarrow treats them as optional imports
    && cd /opt/venv/lib/python3.12/site-packages/pyarrow \
    && rm -f libarrow_flight.so* libarrow_python_flight.so* _flight.*.so libarrow_s3.so* _s3fs.*.so _pyarrow_cpp_tests.*.so

FROM runtime
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

COPY --link --from=builder /opt/venv /opt/venv

WORKDIR /home/streamlit/app
COPY --link models/ models/
COPY --link features/ features/
COPY --link Logo.png schema.png Flowchart.png ./
COPY --link Homepage.py ./
COPY --link pages/ pages/

USER 1000
EXPOSE 8501
CMD ["streamlit", "run", "Homepage.py", "--server.port=8501", "--server.address=0.0.0.0"]
