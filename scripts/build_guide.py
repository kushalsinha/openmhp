"""Write the user guide that ships inside the wheel: openmhp/guide/*.md, from the website's pages and SPEC.md.

Many enterprise machines give an agent no web and no git access; it can install packages and read what they
contain. `mhp guide` reads these files there. Run this whenever the website's pages change:

    python scripts/build_guide.py [--site ../openMHP-website/src]

Pages are converted to plain Markdown: headings, paragraphs, lists, tables, code, links made absolute
(https://openmhp.com/...), figures replaced by their written description. Hand-written pages in openmhp/guide
(troubleshooting.md) are left alone.
"""
from __future__ import annotations

import argparse
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "openmhp" / "guide"
SITE = "https://openmhp.com"
PAGES = [  # (website page, guide topic)
    ("quickstart", "quickstart"), ("index", "introduction"), ("features", "features"), ("design", "design"),
    ("add-a-device", "add-a-device"), ("lab-nodes", "lab-nodes"), ("gateway", "gateway"),
    ("experiment-flow", "experiment-flow"), ("adapters", "adapters"), ("recipes", "recipes"),
    ("cookbook", "cookbook"), ("architecture", "architecture"), ("roadmap", "roadmap"),
]
HAND_WRITTEN = {"troubleshooting"}
SKIP_CLASSES = {"eyebrow", "meta"}
BLOCKS = {"p", "h1", "h2", "h3", "h4", "pre", "li", "figcaption", "blockquote", "table", "ul", "ol", "div", "section",
          "header", "figure", "tr", "summary", "details"}


class ToMarkdown(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []      # finished blocks
        self.buf: list[str] = []      # inline text of the current block
        self.lists: list[list] = []   # [kind, counter]
        self.pre = 0
        self.skip = 0
        self.quote = 0
        self.href: list[str | None] = []
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.prefix = ""
        self.divs: list[bool] = []    # open <div>s: is it a callout (rendered as a quote)?

    # ---- helpers ----
    def text(self, t: str) -> None:
        if self.skip:
            return
        (self.cell if self.cell is not None else self.buf).append(t)

    def flush(self, prefix: str | None = None) -> None:
        raw = "".join(self.buf)
        self.buf = []
        if self.pre:
            return
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            return
        p = self.prefix if prefix is None else prefix
        self.prefix = ""
        q = "> " * self.quote
        self.out.append(q + p + line)

    # ---- tags ----
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = set((a.get("class") or "").split())
        if self.skip:
            if tag not in ("br", "img", "source"):
                self.skip += 1
            return
        if tag in ("script", "style", "nav") or cls & SKIP_CLASSES:
            self.skip = 1
            return
        if tag in ("picture", "source"):
            return
        if self.pre:
            return
        if tag in BLOCKS and tag not in ("li",):
            self.flush()
        if tag in ("h1", "h2", "h3", "h4"):
            self.prefix = "#" * int(tag[1]) + " "
        elif tag in ("ul", "ol"):
            self.flush()
            self.lists.append([tag, 0])
        elif tag == "li":
            self.flush()
            depth = max(len(self.lists) - 1, 0)
            if self.lists and self.lists[-1][0] == "ol":
                self.lists[-1][1] += 1
                self.prefix = "   " * depth + f"{self.lists[-1][1]}. "
            else:
                self.prefix = "   " * depth + "- "
        elif tag == "pre":
            self.flush()
            self.pre = 1
            self.buf = []
        elif tag == "code":
            self.text("`")
        elif tag in ("strong", "b"):
            self.text("**")
        elif tag in ("em", "i"):
            self.text("*")
        elif tag == "br":
            self.text(" ")
        elif tag == "a":
            href = a.get("href") or ""
            if href.startswith("/"):
                href = SITE + href
            self.href.append(href if href and not href.startswith("#") else None)
            self.text("[")
        elif tag == "img":
            alt = (a.get("alt") or "").strip()
            if alt:
                self.flush()
                self.out.append(f"[Figure: {alt}]")
        elif tag == "blockquote":
            self.quote += 1
        elif tag == "div":
            self.divs.append("callout" in cls)
            if "callout" in cls:
                self.quote += 1
        elif tag == "table":
            self.table = []
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []

    def handle_endtag(self, tag):
        if self.skip:
            self.skip -= 1
            return
        if self.pre:
            if tag == "pre":
                code = "".join(self.buf).strip("\n")
                self.buf = []
                self.pre = 0
                self.out.append("```\n" + code + "\n```")
            return
        if tag in ("code", "strong", "b", "em", "i"):
            mark = {"code": "`", "strong": "**", "b": "**"}.get(tag, "*")
            target = self.cell if self.cell is not None else self.buf
            if target and target[-1] == mark:          # nothing inside: drop the pair
                target.pop()
            elif not self.skip:
                target.append(mark)
        elif tag == "a":
            href = self.href.pop() if self.href else None
            self.text(f"]({href})" if href else "]")
        elif tag in ("td", "th"):
            if self.row is not None and self.cell is not None:
                self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip().replace("|", "\\|"))
            self.cell = None
        elif tag == "tr":
            if self.table is not None and self.row is not None:
                self.table.append(self.row)
            self.row = None
        elif tag == "table":
            rows = [r for r in (self.table or []) if r]
            self.table = None
            if rows:
                n = max(len(r) for r in rows)
                rows = [r + [""] * (n - len(r)) for r in rows]
                md = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * n] + ["| " + " | ".join(r) + " |" for r in rows[1:]]
                self.out.append("\n".join(md))
        elif tag in ("ul", "ol"):
            self.flush()
            if self.lists:
                self.lists.pop()
        elif tag == "figcaption":
            raw = re.sub(r"\s+", " ", "".join(self.buf)).strip()
            self.buf = []
            if raw:
                self.out.append(f"*{raw}*")
        elif tag in BLOCKS:
            self.flush()
            if tag == "blockquote" or (tag == "div" and self.divs and self.divs.pop()):
                self.quote = max(self.quote - 1, 0)

    def handle_data(self, data):
        if self.pre and not self.skip:
            self.buf.append(data)
        else:
            self.text(data)

    def result(self) -> str:
        self.flush()
        md = "\n\n".join(self.out)
        md = md.replace("****", "** **")                          # two bold words side by side
        return md.strip() + "\n"


def convert(html: str) -> str:
    p = ToMarkdown()
    p.feed(html)
    p.close()
    return p.result()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default=str(ROOT.parent / "openMHP-website" / "src"), help="the website's src folder")
    a = ap.parse_args()
    site = Path(a.site)
    if not (site / "gateway.html").is_file():
        raise SystemExit(f"no website pages in {site}; pass --site <openMHP-website>/src")
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.md"):
        if f.stem not in HAND_WRITTEN:
            f.unlink()
    written = []
    for page, topic in PAGES:
        md = convert((site / f"{page}.html").read_text(encoding="utf-8"))
        if page == "cookbook":
            for entry in sorted((site / "cookbook").glob("*.html")):
                md += "\n\n" + convert(entry.read_text(encoding="utf-8")).replace("\n# ", "\n## ", 1).replace("# ", "## ", 1)
        head = f"<!-- generated from {SITE}/{'' if page == 'index' else page} by scripts/build_guide.py; edit the website, not this file -->\n\n"
        (OUT / f"{topic}.md").write_text(head + md, encoding="utf-8")
        written.append(topic)
    shutil.copyfile(ROOT / "SPEC.md", OUT / "spec.md")
    written.append("spec")
    print(f"wrote {len(written)} topics to {OUT.relative_to(ROOT)}: {', '.join(written)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
