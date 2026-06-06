# Build context: REPO ROOT (not math-ui/). The image needs sibling
# sdk-ts/ to build the in-repo @aiplatform/sdk before bundling math-ui.
# The CI build matrix sets `context: .` for this image.

# ---------- sdk build ----------
FROM node:20-alpine AS sdk
WORKDIR /sdk

RUN apk add --no-cache libc6-compat

COPY sdk-ts/package.json sdk-ts/package-lock.json* ./
# --ignore-scripts so SDK's `prepare`=tsc doesn't run before src/ is COPYd.
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

COPY math-ui/package.json math-ui/package-lock.json* math-ui/.npmrc* ./math-ui/
COPY --from=sdk /sdk ./sdk-ts

WORKDIR /app/math-ui
# --ignore-scripts: install-links=true makes npm re-run SDK's `prepare`
# against the hard-copied dir; SDK dist/ was already built one stage up.
RUN \
  if [ -f package-lock.json ]; then npm ci --ignore-scripts; \
  else npm i --ignore-scripts; \
  fi

# ---------- next build ----------
FROM node:20-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/math-ui/node_modules ./math-ui/node_modules
COPY --from=sdk /sdk ./sdk-ts
COPY math-ui ./math-ui

WORKDIR /app/math-ui
RUN npm run build --ignore-scripts

# ---------- run ----------
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=7860

EXPOSE 7860

# Next 16 standalone with a workspace puts bootstrap at the tracing-root
# (/app/server.js) + app payload under its own subdir (/app/math-ui/.next/server).
# Static assets are NOT copied by standalone — we copy to /app/.next/static
# which is where the bootstrap serves `/_next/static/*` from. Same with
# `/app/public`. (Lesson from PR #21 deploy: the obvious-looking subdir
# layout was wrong.)
COPY --from=builder /app/math-ui/public ./public
COPY --from=builder /app/math-ui/.next/standalone ./
COPY --from=builder /app/math-ui/.next/static ./.next/static

HEALTHCHECK CMD wget -qO- http://127.0.0.1:7860/ || exit 1

CMD ["node", "server.js"]
