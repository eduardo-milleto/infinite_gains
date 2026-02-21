FROM node:20-alpine

WORKDIR /app

COPY package.json /app/
RUN npm install

COPY . /app

EXPOSE 5173

CMD ["sh", "-c", "npm run build && npm run preview -- --host 0.0.0.0 --port 5173"]
