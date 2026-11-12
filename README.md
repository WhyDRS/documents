# Documents

This is the WhyDRS Documents repo for various forms, templates, and useful information.

## Serve the documents

This temporary host uses Nginx to serve the existing Markdown and PDF files as a
read-only file browser, keeping the repository's document structure intact. Markdown
opens as plain text and PDFs use the browser's PDF viewer. There is no site generator,
frontend framework, upload feature, or account system.

Some existing links, URLs, and Markdown anchors may break behind this interim host.
That is knowingly acceptable at this stage; compatibility redirects and full link
preservation are outside this hosting step's scope.

With Docker and Docker Compose installed and the Docker daemon running, start the
server from the repository root:

```sh
docker compose up --build
```

Then open the [local document browser](http://localhost:8080). Stop it with:

```sh
docker compose down
```

The image contains the documents at build time. Rebuild it after adding or changing
a document. The container listens on port 8080, published on the host at the same
port. Only Markdown and PDF documents are copied into the served directory; Git
metadata and hosting configuration are not published.
