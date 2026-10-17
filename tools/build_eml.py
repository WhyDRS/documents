#!/usr/bin/env python3
"""Build read-only correspondence pages from .eml documents. No runtime service."""

import argparse
import base64
from collections import defaultdict
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import re
import unicodedata
from urllib.parse import quote

IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
ALLOWED_TAGS = set("a abbr b blockquote br caption center code col colgroup dd del details div dl dt em font h1 h2 h3 h4 h5 h6 hr i img ins li ol p pre q s small span strike strong sub summary sup table tbody td th thead tfoot tr u ul".split())
VOID_TAGS = {"br", "col", "hr", "img"}
DROP_CONTENT = {"script", "style", "iframe", "object", "embed", "svg", "math", "form", "button", "input", "textarea", "select", "template", "video", "audio", "noscript", "head"}
CSS_PROPERTIES = {"color", "background-color", "font-family", "font-size", "font-weight", "font-style", "text-align", "text-decoration", "line-height", "letter-spacing", "vertical-align", "border", "border-color", "border-width", "border-style", "border-collapse", "border-spacing", "border-radius", "padding", "padding-top", "padding-right", "padding-bottom", "padding-left", "margin", "margin-top", "margin-right", "margin-bottom", "margin-left", "width", "max-width", "height"}
ALLOWED_ATTRS = {"align", "alt", "bgcolor", "border", "cellpadding", "cellspacing", "class", "colspan", "dir", "height", "href", "id", "lang", "rowspan", "style", "title", "valign", "width"}
MSG_IDS = re.compile(r"<([^<>\s]+@[^<>\s]+)>")


def slug(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value)).strip("-") or "message"


def safe_text(value):
    return escape(str(value or ""), quote=True)


def mail_ids(value):
    # Message-ID and References are opaque identifiers, never used as paths or HTML.
    return [match.lower() for match in MSG_IDS.findall(str(value or ""))]


def email_addresses(value):
    return ", ".join((f"{name} <{address}>" if name else address) for name, address in getaddresses([str(value or "")]))


def part_text(part):
    try:
        content = part.get_content()
        if isinstance(content, str):
            return content
    except (LookupError, UnicodeError, ValueError, AttributeError):
        pass
    data = part.get_payload(decode=True) or b""
    return data.decode(part.get_content_charset() or "utf-8", "replace") if (part.get_content_charset() or "utf-8").lower() in {"utf-8", "ascii", "latin-1", "iso-8859-1", "windows-1252"} else data.decode("utf-8", "replace")


def part_bytes(part):
    payload = part.get_payload(decode=True)
    return payload if isinstance(payload, bytes) else b""


class EmailHTML(HTMLParser):
    """Conservative HTML allowlist; strips active content, remote loads, and CSS rules."""

    def __init__(self, inline_images):
        super().__init__(convert_charrefs=True)
        self.inline_images = inline_images
        self.output = []
        self.dropped = []

    def handle_starttag(self, tag, attrs):
        if tag in DROP_CONTENT:
            self.dropped.append(tag)
            return
        if self.dropped or tag not in ALLOWED_TAGS:
            return
        clean = []
        for key, val in attrs:
            if key not in ALLOWED_ATTRS or val is None:
                continue
            if key == "href":
                if not re.match(r"^(https?://|mailto:|tel:|#)", val.strip(), re.I):
                    continue
            if key == "style":
                # Email inline formatting is retained, but external loads and CSS escapes are not.
                rules = []
                for entry in val.split(";"):
                    property_name, separator, property_value = entry.partition(":")
                    if separator and property_name.strip().lower() in CSS_PROPERTIES and not re.search(r"url\s*\(|@import|expression\s*\(|[{}<>\\]", property_value, re.I):
                        rules.append(property_name.strip().lower() + ":" + property_value.strip())
                val = ";".join(rules)
                if not val:
                    continue
            if key in {"width", "height", "colspan", "rowspan", "border", "cellpadding", "cellspacing"} and not re.fullmatch(r"\d{1,4}%?", val.strip()):
                continue
            if key == "href" and tag != "a":
                continue
            if key == "src":
                continue
            clean.append(f' {key}="{safe_text(val[:4096])}"')
        if tag == "img":
            cid = next((v for k, v in attrs if k == "src"), "") or ""
            if cid.lower().startswith("cid:"):
                encoded = self.inline_images.get(cid[4:].strip("<>").lower())
                if encoded:
                    clean.append(f' src="{encoded}"')
            # No remote images or arbitrary data: URIs (tracking pixels and SVG excluded).
            if not any(x.startswith(' src=') for x in clean):
                return
            clean.append(' loading="lazy"')
        if tag == "a" and any(x.startswith(' href=') for x in clean):
            clean.append(' target="_blank" rel="noopener noreferrer nofollow"')
        self.output.append(f"<{tag}{''.join(clean)}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self.dropped:
            if tag == self.dropped[-1]:
                self.dropped.pop()
            return
        if tag in ALLOWED_TAGS and tag not in VOID_TAGS:
            self.output.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.dropped:
            self.output.append(safe_text(data))

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")


def render_plain(text):
    lines = text.splitlines()
    split = next((i for i, line in enumerate(lines) if line.lstrip().startswith(">") or re.match(r"^On .+wrote:\s*$", line)), None)
    if split is None:
        return f'<div class="plain">{safe_text(text)}</div>'
    visible = "\n".join(lines[:split]).strip()
    quoted = "\n".join(lines[split:]).strip()
    return (f'<div class="plain">{safe_text(visible)}</div>' if visible else "") + (f'<details class="quoted"><summary>Show quoted correspondence</summary><div class="plain">{safe_text(quoted)}</div></details>' if quoted else "")


def read_messages(source):
    messages = []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".eml" or any(part.startswith(".") for part in path.relative_to(source).parts):
            continue
        rel = path.relative_to(source)
        email = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        body_html, body_plain, attachments, cids = "", "", [], {}
        for part in email.walk():
            if part.is_multipart():
                continue
            kind = part.get_content_type().lower()
            disposition = part.get_content_disposition()
            filename = part.get_filename()
            cid = (part.get("Content-ID") or "").strip().strip("<>").lower()
            if (filename or disposition == "attachment" or (cid and kind in IMAGE_TYPES)):
                data = part_bytes(part)
                attachments.append({"name": filename or f"inline-{len(attachments) + 1}", "mime": kind, "data": data, "cid": cid})
                if cid and kind in IMAGE_TYPES and len(data) <= 5_000_000:
                    cids[cid] = "data:" + kind + ";base64," + base64.b64encode(data).decode("ascii")
            if disposition == "attachment":
                continue
            if kind == "text/html" and not body_html:
                body_html = part_text(part)
            elif kind == "text/plain" and not body_plain:
                body_plain = part_text(part)
        date = None
        try:
            date = parsedate_to_datetime(str(email.get("Date") or ""))
            if date is not None and date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError, IndexError, OverflowError):
            pass
        messages.append({"path": rel, "subject": str(email.get("Subject") or rel.stem), "from": email_addresses(email.get("From")), "to": email_addresses(email.get("To")), "cc": email_addresses(email.get("Cc")), "date": date, "date_raw": str(email.get("Date") or ""), "id": next(iter(mail_ids(email.get("Message-ID"))), None), "refs": mail_ids(email.get("References")) + mail_ids(email.get("In-Reply-To")), "html": body_html, "plain": body_plain, "attachments": attachments, "cids": cids})
    return messages


def assign_urls(messages):
    used = set()
    for message in messages:
        p = message["path"]
        stem = "/".join(slug(part) for part in (*p.parts[:-1], p.stem))
        candidate = stem
        if candidate in used:
            candidate = stem + "-" + sha256(str(p).encode()).hexdigest()[:8]
        used.add(candidate)
        message["slug"] = candidate
        message["url"] = "/" + "/".join(quote(part) for part in candidate.split("/")) + "/"
        message["key"] = sha256(str(p).encode()).hexdigest()[:16]


def threads(messages):
    parent = list(range(len(messages)))
    def root(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n
    def merge(a, b):
        parent[root(a)] = root(b)
    ids = {}
    for i, m in enumerate(messages):
        if m["id"] and m["id"] not in ids:
            ids[m["id"]] = i
    seen_refs = {}
    for i, m in enumerate(messages):
        for ref in m["refs"]:
            if ref in ids:
                merge(i, ids[ref])
            # Sibling replies still form a thread when the root email is absent.
            if ref in seen_refs:
                merge(i, seen_refs[ref])
            else:
                seen_refs[ref] = i
    groups = defaultdict(list)
    for i, m in enumerate(messages):
        groups[root(i)].append(m)
    for group in groups.values():
        group.sort(key=lambda m: (m["date"].astimezone(timezone.utc) if m["date"] else datetime.min.replace(tzinfo=timezone.utc), str(m["path"])))
    return groups


def chrome(title, contents):
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'self' 'unsafe-inline'; script-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'; connect-src 'none'">
<title>{safe_text(title)} · WhyDRS Documents</title><link rel="stylesheet" href="/_mail/mail.css"></head>
<body><header class="top"><a class="brand" href="/">WhyDRS <span>Documents</span></a><nav><a href="/">Files</a><a href="/_mail/">Correspondence</a></nav></header>
<main>{contents}</main><footer>Read-only archive · Messages are rendered from original EML files at build time.</footer></body></html>'''


def render_message(m, active, output):
    labels = [("From", m["from"]), ("To", m["to"]), ("Cc", m["cc"]), ("Date", m["date"].strftime("%B %-d, %Y · %H:%M %Z") if m["date"] else m["date_raw"])]
    meta = "".join(f"<dt>{safe_text(label)}</dt><dd>{safe_text(value)}</dd>" for label, value in labels if value)
    if m["html"]:
        cleaner = EmailHTML(m["cids"])
        cleaner.feed(m["html"])
        cleaner.close()
        content = '<div class="email-html">' + "".join(cleaner.output) + "</div>"
    elif m["plain"]:
        content = render_plain(m["plain"])
    else:
        content = '<p class="empty">No readable message body.</p>'
    attachment_markup = []
    for index, attachment in enumerate(m["attachments"]):
        data = attachment["data"]
        filename = slug(Path(attachment["name"]).stem) + "-" + str(index + 1) + ".bin"
        dest = output / "_mail" / "attachments" / m["key"] / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        label = safe_text(attachment["name"])
        href = "/" + quote(str(dest.relative_to(output)).replace("\\", "/"), safe="/")
        attachment_markup.append(f'<a href="{href}" download="{label}"><span aria-hidden="true">↓</span> {label} <small>({safe_text(attachment["mime"])}, {len(data):,} bytes)</small></a>')
    files = f'<section class="attachments"><h3>Attachments · {len(attachment_markup)}</h3><div>{"".join(attachment_markup)}</div></section>' if attachment_markup else ""
    badge = '<span class="current">Selected message</span>' if active else ""
    return f'''<article class="message {'active' if active else ''}" id="message-{m['key']}">
<details open><summary><span class="avatar" aria-hidden="true">✉</span><span class="summary-text"><strong>{safe_text(m['from'] or 'Unknown sender')}</strong><small>{safe_text(m['subject'])}</small></span><span class="summary-right"><time>{safe_text(m['date'].strftime('%b %d, %Y') if m['date'] else m['date_raw'])}</time>{badge}</span></summary>
<div class="message-interior"><dl class="headers">{meta}</dl><div class="mail-content">{content}</div>{files}<p class="permalink"><a href="{m['url']}">Open this message ↗</a></p></div></details></article>'''


def build(source, output):
    source, output = source.resolve(), output.resolve()
    if output == source or source in output.parents:
        # The output may be a sibling or nested build directory, but never source itself.
        raise ValueError("Output directory must be outside the source tree")
    output.mkdir(parents=True, exist_ok=True)
    messages = read_messages(source)
    assign_urls(messages)
    grouped = threads(messages)
    stylesheet = Path(__file__).with_name("mail.css").read_text(encoding="utf-8")
    styles = output / "_mail" / "mail.css"
    styles.parent.mkdir(parents=True, exist_ok=True)
    styles.write_text(stylesheet, encoding="utf-8")
    entries = []
    for group in grouped.values():
        count = len(group)
        for focused in group:
            nav = ''.join(f'<a href="#message-{m["key"]}" class="{"selected" if m is focused else ""}">{i + 1}. {safe_text(m["from"] or m["path"].stem)} <small>{safe_text(m["date"].strftime("%b %d") if m["date"] else "")}</small></a>' for i, m in enumerate(group)) if count > 1 else ""
            heading = f'<div class="heading"><p class="eyebrow">Correspondence / {count} {"messages" if count != 1 else "message"}</p><h1>{safe_text(focused["subject"])}</h1><p>Archived email, presented as a readable document. External images are blocked for privacy.</p></div>'
            items = ''.join(render_message(m, m is focused, output) for m in group)
            page = chrome(focused["subject"], heading + (f'<nav class="thread-nav" aria-label="Messages in thread"><strong>In this thread</strong><div>{nav}</div></nav>' if nav else "") + '<section class="conversation" aria-label="Email conversation">' + items + '</section>')
            dest = output / focused["slug"] / "index.html"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(page, encoding="utf-8")
        latest = group[-1]
        entries.append(f'<li><a href="{latest["url"]}">{safe_text(group[0]["subject"])}</a><span>{safe_text(latest["from"])} · {safe_text(latest["date"].strftime("%b %d, %Y") if latest["date"] else "Undated")} · {count} {"messages" if count != 1 else "message"}</span></li>')
    listing = chrome("Correspondence", '<div class="heading"><p class="eyebrow">WhyDRS archive</p><h1>Correspondence</h1><p>Readable email documents, grouped by reply headers when available.</p></div>' + (f'<ul class="index">{"".join(entries)}</ul>' if entries else '<p class="empty">No .eml documents have been added yet. Add one and rebuild the host to publish it here.</p>'))
    (output / "_mail" / "index.html").write_text(listing, encoding="utf-8")
    return len(messages)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(f"Rendered {build(args.source, args.output)} correspondence messages")
