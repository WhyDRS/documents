FROM python:3.13-alpine AS correspondence
WORKDIR /source
COPY . .
RUN python -m unittest discover -s tests -v && python tools/build_eml.py /source /rendered

FROM nginx:1.30.5-alpine AS documents
WORKDIR /documents
COPY . .
RUN find . -type f ! -name '*.md' ! -name '*.pdf' -delete

FROM nginx:1.30.5-alpine
RUN rm /usr/share/nginx/html/index.html /usr/share/nginx/html/50x.html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=documents /documents/ /usr/share/nginx/html/
COPY --from=correspondence /rendered/ /usr/share/nginx/html/
EXPOSE 8080
