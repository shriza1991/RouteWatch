FROM node:22-alpine
WORKDIR /app
COPY dashboard/package.json ./
RUN npm install
COPY dashboard ./
CMD ["npm","run","dev"]
