#!/usr/bin/env python3
"""Offline static, navigation, SVG and accidental disclosure checks for a site export."""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit, unquote
import xml.etree.ElementTree as ET

SITE = 'https://justgithubaccount.github.io/'
PROFILE = 'https://github.com/justgithubaccount'
REPOS = {'app-poly-gitops-k8s', 'app-poly-gitops-infra', 'app-poly-gitops-fastapi'}
EVIDENCE = {
    'app-poly-gitops-k8s': {'README.md', 'clusters/dev/kustomization.yaml', 'clusters/smoke/kustomization.yaml'},
    'app-poly-gitops-infra': {'README.md', 'terraform/timeweb/main.tf', '.github/workflows/timeweb-smoke.yaml'},
    'app-poly-gitops-fastapi': {'README.md', 'app/api.py', 'app/core/llm_client.py'},
}
VOID = {'meta', 'link', 'img', 'br', 'hr', 'input', 'source', 'wbr', 'area', 'base', 'col', 'embed', 'param', 'track'}
HTML_TAGS = {'html', 'head', 'meta', 'title', 'link', 'script', 'body', 'a', 'header', 'span', 'nav', 'main', 'section', 'div', 'h1', 'h2', 'h3', 'p', 'ul', 'li', 'ol', 'article', 'img', 'details', 'summary', 'code', 'br', 'footer'}
HTML_ATTRS = {'lang', 'charset', 'name', 'content', 'property', 'rel', 'href', 'type', 'class', 'id', 'src', 'alt', 'width', 'height', 'loading', 'fetchpriority', 'role', 'open'}
EXPORT_FILES = {'index.html', 'styles.css', 'robots.txt', 'sitemap.xml', 'llms.txt', 'structured-data.json', '.nojekyll', 'assets/favicon.svg', 'assets/orbital.svg', 'assets/art-k8s.svg', 'assets/art-infra.svg', 'assets/art-fastapi.svg'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def public_url(url):
    if url in (PROFILE, SITE):
        return True
    u = urlsplit(url)
    if u.scheme != 'https' or u.netloc != 'github.com' or u.query or u.fragment:
        return False
    parts = u.path.strip('/').split('/')
    if len(parts) < 2 or parts[0] != 'justgithubaccount' or parts[1] not in REPOS:
        return False
    if len(parts) == 2:
        return True
    return len(parts) >= 5 and parts[2] == 'blob' and re.fullmatch('[0-9a-f]{40}', parts[3]) and '/'.join(parts[4:]) in EVIDENCE[parts[1]]


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.refs, self.stack, self.headings = set(), [], [], []
        self.json_ld, self.in_script, self.script_body = [], False, ''
        self.canonical, self.robots, self.lang, self.viewport = None, None, None, None

    def handle_starttag(self, tag, attrs):
        require(len(attrs) == len(dict(attrs)), 'Duplicate HTML attribute')
        attrs = dict(attrs)
        require(tag in HTML_TAGS, f'Unapproved HTML element: {tag}')
        require(all(k in HTML_ATTRS or k.startswith('aria-') for k in attrs), 'Unapproved HTML attribute')
        if 'src' in attrs:
            u = urlsplit(attrs['src'])
            require(tag == 'img' and not u.scheme and not u.netloc, 'Only local image resources are allowed')
        if tag == 'link':
            require(attrs.get('rel') in ('canonical', 'stylesheet', 'icon'), 'Unapproved link resource')
            if attrs.get('rel') != 'canonical':
                u = urlsplit(attrs.get('href', ''))
                require(not u.scheme and not u.netloc, 'Only local stylesheets and icons are allowed')
        if 'id' in attrs:
            require(attrs['id'] not in self.ids, 'Duplicate HTML id')
            self.ids.add(attrs['id'])
        if tag not in VOID:
            self.stack.append(tag)
        if tag == 'html':
            self.lang = attrs.get('lang')
        if tag in {'h1', 'h2', 'h3'}:
            self.headings.append(tag)
        if tag == 'meta' and attrs.get('name') == 'robots':
            self.robots = attrs.get('content')
        if tag == 'meta' and attrs.get('name') == 'viewport':
            self.viewport = attrs.get('content')
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonical = attrs.get('href')
        if tag == 'img':
            require('alt' in attrs and 'width' in attrs and 'height' in attrs, 'Image lacks alternative text or dimensions')
        if tag == 'script':
            require(attrs == {'type': 'application/ld+json'}, 'Only inert JSON-LD is allowed')
            self.in_script, self.script_body = True, ''
        for attr in ('href', 'src'):
            if attr in attrs:
                self.refs.append(attrs[attr])

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        require(self.stack and self.stack[-1] == tag, f'Unbalanced HTML element: {tag}')
        self.stack.pop()
        if tag == 'script':
            self.in_script = False
            self.json_ld.append(json.loads(self.script_body))

    def handle_data(self, data):
        if self.in_script:
            self.script_body += data


def audit_svg(path):
    text = path.read_text(encoding='utf-8')
    require(len(text.encode()) < 100_000, f'SVG exceeds byte budget: {path.name}')
    require(not re.search(r'<\?|<!DOCTYPE|<!ENTITY', text, re.I), 'SVG processing instruction or entity declaration')
    root = ET.fromstring(text)
    require(root.tag == '{http://www.w3.org/2000/svg}svg' and 'viewBox' in root.attrib, 'Invalid SVG root')
    ns = {'s': 'http://www.w3.org/2000/svg'}
    require(root.find('s:title', ns) is not None and root.find('s:desc', ns) is not None, 'SVG missing title/description')
    ids = {node.attrib['id'] for node in root.iter() if 'id' in node.attrib}
    require(len(ids) == sum('id' in node.attrib for node in root.iter()), 'Duplicate SVG id')
    allowed = {'svg', 'title', 'desc', 'defs', 'linearGradient', 'radialGradient', 'stop', 'path', 'rect', 'circle', 'ellipse', 'g', 'text'}
    attributes = {'id', 'viewBox', 'role', 'aria-labelledby', 'x1', 'y1', 'x2', 'y2', 'offset', 'stop-color', 'stop-opacity', 'cx', 'cy', 'r', 'fill', 'stroke', 'stroke-width', 'opacity', 'stroke-dasharray', 'rx', 'ry', 'x', 'y', 'width', 'height', 'transform', 'd', 'font-family', 'font-size', 'font-weight'}
    for node in root.iter():
        require(node.tag.startswith('{http://www.w3.org/2000/svg}') and node.tag.rsplit('}', 1)[-1] in allowed, 'Non-static SVG element')
        for name, value in node.attrib.items():
            require(name in attributes, 'SVG unsupported attribute')
            require(not re.search(r'https?:|data:|javascript:|@font-face', value), 'SVG external resource')
            if name in ('fill', 'stroke', 'stop-color'):
                require(re.fullmatch(r'#[0-9a-fA-F]{3,8}|none|currentColor|url\(#[A-Za-z][\w-]*\)', value), 'Unsupported SVG paint value')
            for ref in re.findall(r'url\s*\(([^)]+)\)', value, re.I):
                require(ref.startswith('#') and ref[1:] in ids, 'SVG unresolved paint reference')
    return True


def no_disclosure(text):
    for bad in ('Vast-CX-Suit', 'Control Plane', 'self-media-registry', 'self-offer-registry', 'self-revenue-registry', 'BEGIN PRIVATE KEY', 'ghp_', 'github_pat_', 'sk-proj-', '.svc.cluster.local'):
        require(bad.lower() not in text.lower(), f'Forbidden publication token: {bad}')
    require(not re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', text), 'Unreviewed contact data')
    require(not re.search(r'\b(?:10\.(?:\d{1,3}\.){2}\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b', text), 'Private network address')


def audit_site(root):
    root = root.resolve()
    info = json.loads((root / 'build-info.json').read_text())
    require(isinstance(info, dict) and set(info) == {'schema_version', 'publication_state', 'manifest_sha256', 'generator_sha256', 'files'}, 'Invalid export metadata fields')
    require(info['schema_version'] == 'portfolio-export.v1', 'Unknown export')
    require(info['publication_state'] in ('DRAFT', 'RELEASE_APPROVED'), 'Unreviewed publication state')
    for key in ('manifest_sha256', 'generator_sha256'):
        require(isinstance(info[key], str) and re.fullmatch('[0-9a-f]{64}', info[key]), 'Invalid export digest: ' + key)
    files = info['files']
    require(isinstance(files, dict) and set(files) == EXPORT_FILES, 'Invalid export inventory')
    engineering = {'build-info.json', 'README.md', '.gitignore', 'scripts/audit.py', '.github/workflows/validate.yml'}
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and '.git' not in p.relative_to(root).parts and '__pycache__' not in p.relative_to(root).parts}
    require(not actual - set(files) - engineering, 'Unexpected file in publication export')
    for name, expected in files.items():
        require(isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected), 'Invalid file digest')
        path = (root / name).resolve()
        require(path.is_relative_to(root) and path.is_file(), f'Missing or unsafe export path: {name}')
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected, f'Export digest drift: {name}')
        no_disclosure(path.read_text(encoding='utf-8'))
    page = Page()
    page.feed((root / 'index.html').read_text())
    require(not page.stack, 'Unclosed HTML elements')
    require(page.lang == 'en' and page.viewport == 'width=device-width, initial-scale=1', 'Language/viewport missing')
    require(page.headings.count('h1') == 1 and 'main' in page.ids, 'Missing main heading/landmark')
    require(page.canonical == SITE, 'Wrong canonical')
    require(page.json_ld == [json.loads((root / 'structured-data.json').read_text())], 'JSON-LD drift')
    indexing = info['publication_state'] == 'RELEASE_APPROVED'
    require(page.robots == ('index, follow' if indexing else 'noindex, nofollow'), 'Incorrect indexing meta')
    require(('Allow: /' if indexing else 'Disallow: /') in (root / 'robots.txt').read_text(), 'Incorrect robots rule')
    tree = ET.parse(root / 'sitemap.xml')
    require([x.text for x in tree.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc')] == [SITE], 'Incorrect sitemap')
    for ref in page.refs:
        u = urlsplit(ref)
        require(u.scheme not in ('javascript', 'data', 'mailto'), 'Unapproved link protocol')
        if u.scheme or u.netloc:
            require(public_url(ref), f'URL outside public allowlist: {ref}')
        elif u.path:
            require(not u.query, 'Unexpected resource query')
            dest = (root / unquote(u.path)).resolve()
            require(dest.is_relative_to(root) and dest.is_file(), f'Missing or unsafe local resource: {ref}')
        else:
            require(u.fragment in page.ids, f'Broken local navigation: {ref}')
    svgs = list((root / 'assets').glob('*.svg'))
    for svg in svgs:
        audit_svg(svg)
    css = (root / 'styles.css').read_text()
    # This generated sheet needs neither escapes nor image/font resources. Refuse
    # them rather than trying to implement the browser's CSS tokenizer in regex.
    require('\\' not in css and not re.search(r'@import|url\s*\(|image-set\s*\(|src\s*\(|https?:|//|data:', css, re.I), 'External or escaped CSS resource')
    require('@media' in css and 'prefers-reduced-motion' in css and ':focus-visible' in css, 'Missing responsive/accessibility styles')
    return {'result': 'PASS', 'files_hashed': len(files), 'html_refs': len(page.refs), 'svg_checked': len(svgs), 'publication_state': info['publication_state']}


def audit_profile(root):
    text = (root / 'README.md').read_text()
    no_disclosure(text)
    urls = re.findall(r'https?://[^\s)"<>]+', text)
    require(all(public_url(url) for url in urls), 'README URL outside allowlist')
    for name in re.findall(r'\]\((assets/[^)]+|site/[^)]+)\)', text):
        require((root / name).is_file(), 'Broken README resource')
    for name in re.findall(r'(?:src|srcset)="(assets/[^"]+)"', text):
        require((root / name).is_file(), 'Broken README picture resource')
    for svg in (root / 'assets').glob('*.svg'):
        audit_svg(svg)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--site-only', action='store_true')
    args = parser.parse_args()
    try:
        if not args.site_only:
            audit_profile(args.root)
        print(json.dumps(audit_site(args.root if args.site_only else args.root / 'site'), sort_keys=True))
    except (ValueError, OSError, ET.ParseError) as exc:
        print(f'Audit failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
