FROM node:20-alpine

WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .

# Expose Vite dev port
EXPOSE 3000

CMD ["pnpm", "run", "dev", "--", "--host"]
