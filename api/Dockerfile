# Stage 1: build LibreDWG (dwg2dxf) — not packaged in Debian bookworm; used
# by /api/view/dwg2dxf to convert DWG datasheets for the browser viewer.
FROM python:3.12-slim AS libredwg
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential pkg-config curl ca-certificates xz-utils \
    && rm -rf /var/lib/apt/lists/*
RUN curl -sL https://github.com/LibreDWG/libredwg/releases/download/0.13.3/libredwg-0.13.3.tar.xz \
        -o /tmp/libredwg.tar.xz \
    && tar -xf /tmp/libredwg.tar.xz -C /tmp \
    && cd /tmp/libredwg-0.13.3 \
    # -Wno-error: 0.13.3 trips new-GCC alloc-size warnings promoted by -Werror
    && ./configure --disable-bindings --disable-shared CFLAGS="-g -O2 -Wno-error" \
    && make -j"$(nproc)" \
    && install -s -m 755 programs/dwg2dxf /usr/local/bin/dwg2dxf

FROM python:3.12-slim

# git — project mirrors are cloned/fetched with the git CLI (provider-agnostic)
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY --from=libredwg /usr/local/bin/dwg2dxf /usr/local/bin/dwg2dxf
COPY pyproject.toml ./
COPY app ./app
COPY cli ./cli
# Vendored, KiCad-10-patched kiutils (see pyproject comment)
COPY kiutils ./kiutils
RUN pip install --no-cache-dir .

# Cap glibc malloc arenas. The datasheet sweeps and read_datasheet run in
# daemon threads over ~1 GB of PDF blobs, and glibc hands every thread its own
# arena that grows in 64 MB heaps and never shrinks. Unset, this container was
# observed holding 67 heaps -- 4.2 GB of arena for ~48 MB of live objects.
# The trim half of the fix is services/memory.py; both are needed.
ENV MALLOC_ARENA_MAX=2

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
