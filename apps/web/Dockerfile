FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/package.json
COPY packages ./packages
RUN pnpm install --frozen-lockfile
COPY tsconfig.base.json eslint.config.mjs ./
COPY apps/web ./apps/web
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm --filter @aii/web build
ENV NODE_ENV=production PYTHON_API_URL=http://api:8000
USER node
EXPOSE 3000
CMD ["node", "apps/web/node_modules/next/dist/bin/next", "start", "apps/web", "-H", "0.0.0.0", "-p", "3000"]
