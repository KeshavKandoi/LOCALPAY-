FROM node:22-bookworm-slim AS dependencies
WORKDIR /srv/dashboard
COPY apps/dashboard/package.json apps/dashboard/package-lock.json ./
RUN npm ci

FROM dependencies AS build
COPY apps/dashboard ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build -- --webpack

FROM node:22-bookworm-slim
WORKDIR /srv/dashboard
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build --chown=node:node /srv/dashboard/.next/standalone ./
COPY --from=build --chown=node:node /srv/dashboard/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
