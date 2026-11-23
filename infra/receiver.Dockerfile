FROM node:22-bookworm-slim
WORKDIR /srv/receiver
COPY examples/node-integration/package.json examples/node-integration/package-lock.json ./
RUN npm ci --omit=dev
COPY examples/node-integration/app.mjs ./
USER node
CMD ["node", "app.mjs"]
