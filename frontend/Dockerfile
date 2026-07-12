# syntax=docker/dockerfile:1.7
# Bedrock Monitor Frontend — Next.js 14 standalone (Node 20 alpine, non-root)

# ---- Stage 1: 의존성 ----
FROM node:20-alpine AS deps
WORKDIR /app
# Alpine은 native module 빌드 시 libc 차이가 있을 수 있어 명시.
RUN apk add --no-cache libc6-compat
COPY package.json package-lock.json* ./
RUN npm ci

# ---- Stage 2: 빌드 ----
FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# RUM(Real User Monitoring) — NEXT_PUBLIC_*은 빌드 타임에 번들로 인라인되므로
# build-arg로 주입 (미지정 시 수집 비활성화, RumProvider가 no-op).
ARG NEXT_PUBLIC_RUM_ENDPOINT
ARG NEXT_PUBLIC_RUM_API_KEY
ENV NEXT_PUBLIC_RUM_ENDPOINT=$NEXT_PUBLIC_RUM_ENDPOINT \
    NEXT_PUBLIC_RUM_API_KEY=$NEXT_PUBLIC_RUM_API_KEY
# Next.js standalone output (next.config.mjs에 output: "standalone" 설정 필요).
RUN npm run build

# ---- Stage 3: 런타임 ----
FROM node:20-alpine AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# 보안: non-root 사용자.
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# Standalone 출력은 server.js + 필요한 node_modules만 포함.
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
# public/ 정적 자원 (v2.10.0 패리티 갤러리부터 사용).
COPY --from=build --chown=nextjs:nodejs /app/public ./public

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD wget -q -O - http://localhost:3000/ >/dev/null 2>&1 || exit 1

CMD ["node", "server.js"]
