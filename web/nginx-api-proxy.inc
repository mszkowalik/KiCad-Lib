# Shared proxy body for every path the FastAPI app owns. Included from
# nginx.conf; not a standalone config.

# $kicadlib_api is set in the server block (default.conf.template) from the
# API_UPSTREAM env var. Going through a variable also defers DNS to request
# time via the resolver, so nginx starts even when the api container is not up
# yet — a literal upstream name is resolved once at startup and refuses to
# start without it. The $request_uri suffix is required: proxy_pass with a
# variable does not append the matched location by itself.
proxy_pass $kicadlib_api$request_uri;

proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-Host $host;

# Jaravis streams a turn as server-sent events, and imports, renders and PCM
# builds can run for minutes. Buffering would hold the stream back and the
# default 60 s read timeout would cut the long ones off.
proxy_buffering off;
proxy_request_buffering off;
proxy_read_timeout 3600s;
proxy_send_timeout 3600s;

# The file mirror serves 3D models and gerber bundles; never spool them to a
# temp file on the way through.
proxy_max_temp_file_size 0;
