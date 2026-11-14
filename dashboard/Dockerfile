FROM node:22-alpine
WORKDIR /app
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard ./
CMD ["npm","run","dev"]
