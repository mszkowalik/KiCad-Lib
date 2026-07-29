# Two targets from one file:
#   dev  — the Vite dev server, used by compose.yaml (which mounts ./web over
#          /srv and keeps the image's linux node_modules via an anonymous volume)
#   prod — the built SPA served by nginx, which ALSO reverse-proxies the API so
#          the browser only ever talks to one origin. That is what makes a
#          prebuilt image portable: Vite inlines env vars at build time, so an
#          image with a baked-in API URL would only work on one hostname.

FROM node:22-alpine AS deps
WORKDIR /srv
COPY package.json package-lock.json ./
# ci, not install: builds from the lockfile exactly and fails when it drifts
# out of sync with package.json. --no-audit --no-fund drop two network round
# trips that a build has no use for.
RUN npm ci --no-audit --no-fund

FROM deps AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]

FROM deps AS build
COPY . .
# `prebuild` copies the occt-import-js runtime into public/occt/ (STEP viewer),
# then `vite build` runs tsc --noEmit first — a type error fails the image.
RUN npm run build

FROM nginx:1.27-alpine AS prod
# host:port of the FastAPI app. A stack sharing a docker network with others
# cannot use a name as generic as `api`, so this is substituted at startup.
ENV API_UPSTREAM=api:8000
# Path prefix this app is mounted under: "" for the root, "/lib" behind a
# shared reverse proxy that strips the prefix before forwarding.
ENV APP_BASE=""
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY nginx-api-proxy.inc /etc/nginx/nginx-api-proxy.inc
COPY --from=build /srv/dist /usr/share/nginx/html
# index.html becomes a template: 40-app-base.sh regenerates it on every start
# with APP_BASE stamped in. Removing the built copy makes a missing or failed
# entrypoint loud instead of silently serving unsubstituted placeholders.
RUN mv /usr/share/nginx/html/index.html /usr/share/nginx/html/index.html.template
COPY 40-app-base.sh /docker-entrypoint.d/40-app-base.sh
RUN chmod +x /docker-entrypoint.d/40-app-base.sh
EXPOSE 80
