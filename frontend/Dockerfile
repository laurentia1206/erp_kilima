# syntax=docker/dockerfile:1
# Contexte de construction : racine du dépôt (ex: docker build -f frontend/Dockerfile .)

# ------------------------------------------------------------------------------
# 1. Étape de Build
# ------------------------------------------------------------------------------
FROM node:24-bookworm-slim AS build
WORKDIR /app

# Arguments de build pour récurer les URL d'API au moment de la compilation Next.js
ARG APP_URL=https://kilimaholdings.com
ARG NEXT_PUBLIC_API_URL=https://erp.votre-domaine.com

ENV APP_URL=$APP_URL \
    NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_TELEMETRY_DISABLED=1

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# Inclut l'étape prebuild (copie des assets historiques) et la compilation Next.js
RUN npm run build

# ------------------------------------------------------------------------------
# 2. Étape d'installation des dépendances de production uniquement
# ------------------------------------------------------------------------------
FROM node:24-bookworm-slim AS dependencies
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

# ------------------------------------------------------------------------------
# 3. Image finale de Runtime
# ------------------------------------------------------------------------------
FROM node:24-bookworm-slim AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME="0.0.0.0"

# Récupération des dépendances de prod et du build Next.js
COPY --from=dependencies --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/.next ./.next
COPY --from=build --chown=node:node /app/public ./public
COPY --from=build --chown=node:node /app/package.json ./package.json
COPY --from=build --chown=node:node /app/next.config.mjs ./next.config.mjs

USER node

EXPOSE 3000

CMD ["node", "node_modules/next/dist/bin/next", "start", "--hostname", "0.0.0.0", "--port", "3000"]