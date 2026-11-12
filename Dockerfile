FROM nginx:1.30.5-alpine AS documents

WORKDIR /documents
COPY . .
RUN find . -type f ! -name '*.md' ! -name '*.pdf' -delete

FROM nginx:1.30.5-alpine

RUN rm /usr/share/nginx/html/index.html /usr/share/nginx/html/50x.html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=documents /documents/ /usr/share/nginx/html/

EXPOSE 8080
