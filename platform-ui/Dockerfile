# Build context: REPO ROOT (not platform-ui/). The image needs the
# sibling sdk-ts/ to build the in-repo SDK before bundling platform-ui.
# The CI build matrix sets `context: .` for this image.
#
# Mirror of math-ui/Dockerfile in spirit (Next 16 standalone output).
# PORT 7861 (math-ui owns 7860).

# ---------- sdk build ----------
FROM node:20-alpine AS sdk
WORKDIR /sdk

RUN apk add --no-cache libc6-compat

COPY sdk-ts/package.json sdk-ts/package-lock.json* ./
# `--ignore-scripts` skips the SDK's `prepare` (tsc), which would
# otherwise run before src/ has been COPYd and fail. The explicit
# `npm run build` below does the compile once everything's in place.
RUN \
  if [ -f package-lock.json ]; then npm ci --ignore-scripts; \
  else npm i --ignore-scripts; \
  fi

COPY sdk-ts/tsconfig.json ./
COPY sdk-ts/scripts ./scripts
COPY sdk-ts/src ./src
RUN npm run build

# ---------- deps ----------
FROM node:20-alpine AS deps
WORKDIR /app

RUN apk add --no-cache libc6-compat

# `.npmrc` pins install-links so file: deps are hard-copied (Turbopack
# can't resolve symlinked file: deps). The directory layout has to
# place sdk-ts alongside platform-ui for the `file:../sdk-ts` ref.
COPY platform-ui/package.json platform-ui/package-lock.json* platform-ui/.npmrc* ./platform-ui/
COPY --from=sdk /sdk ./sdk-ts

WORKDIR /app/platform-ui
# Same `--ignore-scripts` rationale as the SDK stage above: with
# `install-links=true` (pinned in .npmrc), `npm ci` would hard-copy
# sdk-ts/ and re-run its `prepare` (tsc) against the copy. The SDK's
# dist/ was already built one stage up and copied in via --from=sdk;
# we don't want it overwritten or fail-looped here.
RUN \
  if [ -f package-lock.json ]; then npm ci --ignore-scripts; \
  else npm i --ignore-scripts; \
  fi

# ---------- next build ----------
FROM node:20-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/platform-ui/node_modules ./platform-ui/node_modules
COPY --from=sdk /sdk ./sdk-ts
COPY platform-ui ./platform-ui

WORKDIR /app/platform-ui
# Skip the `predev`/`prebuild` SDK rebuild — sdk-ts/dist is already
# copied above via --from=sdk.
RUN npm run build --ignore-scripts

# ---------- run ----------
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=7861

EXPOSE 7861

# Standalone output collapses node_modules into .next/standalone, so
# we don't need to copy sdk-ts separately at runtime. Next's standalone
# bundler emits the bootstrap `server.js` at the workspace tracing
# root (/app/) and the app's server-side payload under its subdir
# (/app/platform-ui/.next/server). Static assets are NOT copied by
# standalone — we copy them ourselves to the path the bootstrap
# serves `/_next/static/*` from, which (for a monorepo-style standalone
# build) is the workspace root's `.next/static`, not the subdir.
COPY --from=builder /app/platform-ui/.next/standalone ./
COPY --from=builder /app/platform-ui/.next/static ./.next/static

HEALTHCHECK CMD wget -qO- http://127.0.0.1:7861/ || exit 1

CMD ["node", "server.js"]
