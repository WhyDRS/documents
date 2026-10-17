# Documents

This is the WhyDRS Documents repo for various forms, templates, and useful information.

## Serve the documents

This temporary host uses Nginx to serve the existing Markdown and PDF files as a
read-only file browser, keeping the repository's document structure intact. Markdown
opens as plain text and PDFs use the browser's PDF viewer. Markdown and PDF remain unchanged. EML email messages are rendered as static HTML during the build; there is no client-side framework, upload feature, or account system.

Some existing links, URLs, and Markdown anchors may break behind this interim host.
That is knowingly acceptable at this stage; compatibility redirects and full link
preservation are outside the scope of this hosting step.

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
port. Only Markdown and PDF source documents plus generated correspondence pages are served; original EML files, Git metadata, and hosting configuration are not published.


## Publish correspondence (.eml)

Add an .eml file anywhere in the documents directory and rebuild the Docker image.
Email is converted **at build time** to a polished, read-only HTML page; the original
.eml is never made public. The filename becomes its external URL slug:

- Board Letter.eml → /board-letter/
- Letters/Follow up.eml → /letters/follow-up/

The site has a [correspondence index](http://localhost:8080/_mail/) linking to
conversations. Each email has its own permalink. Related messages are displayed
together as a chronological thread using standard Message-ID, In-Reply-To, and
References headers; replies sharing an absent root can also be grouped. Subject
similarity alone will not merge unrelated correspondence.

Both HTML and plain-text emails work. The renderer preserves common inline formatting,
tables, addresses, dates, linked inline cid: images, and downloadable attachments.
Plain-text quoted replies can be collapsed. Active email HTML, remote images, and
remote resources are stripped for privacy and safety. Scripts are never served, and
attachments are forced to download rather than execute. No client-side JS is needed.

If two filenames normalize to the same slug, the later one gets a stable filename hash.
Generated pages and attachments are built into the read-only Nginx image; there is no
mail upload endpoint or mail-sending capability.

Run the regression suite locally with:

    python -m unittest discover -s tests -v
