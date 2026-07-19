# Official KiCad image -> pixel-exact previews. Match your desktop major
# version (you run KiCad 10) so source files parse identically.
ARG KICAD_IMAGE=kicad/kicad:10.0
FROM ${KICAD_IMAGE}

USER root
RUN apt-get update \
    # gerbv: renders production gerbers to SVG for the gerber viewer
    && apt-get install -y --no-install-recommends python3-pip gerbv \
    && rm -rf /var/lib/apt/lists/* \
    # --ignore-installed: pydantic upgrades typing_extensions, but the image's
    # Debian-installed copy has no pip RECORD and cannot be uninstalled
    && pip3 install --no-cache-dir --break-system-packages --ignore-installed \
        fastapi uvicorn pydantic

COPY server.py project_ops.py board_template.kicad_pcb /srv/
# Custom color themes (e.g. Skyline-7S) so themed renders match the desktop.
# Server runs as root, KiCad 10 config path:
COPY themes/*.json /root/.config/kicad/10.0/colors/

EXPOSE 8100
CMD ["python3", "-m", "uvicorn", "server:app", "--app-dir", "/srv", "--host", "0.0.0.0", "--port", "8100"]
