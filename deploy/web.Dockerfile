# Build from the repo root:  docker build -f deploy/web.Dockerfile --build-arg VITE_API_BASE=https://api.example.in .
FROM node:20.18-alpine AS build
WORKDIR /repo
COPY package.json package-lock.json ./
COPY packages ./packages
COPY apps/web ./apps/web
COPY apps/mobile/package.json ./apps/mobile/package.json
COPY apps/capacitor/package.json ./apps/capacitor/package.json
RUN npm ci --workspace apps/web --include-workspace-root --no-audit --no-fund
ARG VITE_API_BASE=http://localhost:8000
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build -w apps/web

FROM nginx:1.27-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/apps/web/dist /usr/share/nginx/html
EXPOSE 80
