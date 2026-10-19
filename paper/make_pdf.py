from __future__ import annotations

import argparse
import html
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

STYLE = """
@page { size: A4; margin: 15mm 13mm; }
* { box-sizing: border-box; }
body { margin:0; font-family:"Apple SD Gothic Neo","Malgun Gothic",serif;
       font-size:9.5pt; line-height:1.26; color:#000;
       -webkit-print-color-adjust:exact; }
.cols { column-count:2; column-gap:7mm; text-align:justify; }
h1 { font-size:16pt; line-height:1.35; text-align:center; margin:0 0 6pt; }
h2 { font-size:11pt; margin:7pt 0 2.5pt; }
h3 { font-size:10pt; margin:5pt 0 2pt; }
p { margin:0 0 4pt; text-indent:0; }
ol, ul { margin:0 0 4pt; padding-left:15pt; }
li { margin-bottom:2pt; }
code { font-family:"SF Mono",Menlo,monospace; font-size:8.6pt; }
strong { font-weight:700; }
table { border-collapse:collapse; width:100%; margin:3pt 0 6pt; font-size:8.1pt; }
th, td { border:0.5pt solid #000; padding:1.5pt 3pt; text-align:center;
         line-height:1.24; }
th { background:#eee; font-weight:700; }
figure { margin:4pt 0 6pt; text-align:center; break-inside:avoid; }
figure img { width:88%; }
.span { column-span:all; }
figure.span img { width:122mm; }
table.span { font-size:8.1pt; }
p.title-en { text-align:center; font-size:10pt; margin:0 0 10pt; }
p.ref { font-size:8.6pt; margin:0 0 1.5pt; padding-left:12pt;
        text-indent:-12pt; text-align:left; }
"""


def inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return text


def render_table(block: list[str], span: bool) -> str:
    rows = [[c.strip() for c in r.strip().strip("|").split("|")] for r in block]
    header, body = rows[0], rows[2:] if len(rows) > 1 else []
    wide = span or len(header) >= 5
    head_html = "".join(f"<th>{inline(c)}</th>" for c in header)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>"
        for row in body
    )
    cls = ' class="span"' if wide else ""
    return (f"<table{cls}><thead><tr>{head_html}</tr></thead>"
            f"<tbody>{body_html}</tbody></table>")


def to_html(markdown: str, wide_figures: bool = False) -> str:
    figure_class = ' class="span"' if wide_figures else ""
    lines = markdown.splitlines()
    out: list[str] = []
    index = 0
    in_head = True

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped or set(stripped) == {"-"}:
            index += 1
            continue

        heading = re.match(r"^(#{1,6}) (.*)", line)
        if heading:
            level, text = len(heading.group(1)), heading.group(2)
            if level == 2 and re.match(r"^\d", text):
                in_head = False
            cls = ' class="span"' if in_head else ""
            out.append(f"<h{level}{cls}>{inline(text)}</h{level}>")
            index += 1
            continue

        image = re.match(r"^!\[\]\(([^)]+)\)", stripped)
        if image:
            out.append(f'<figure{figure_class}><img src="{image.group(1)}"></figure>')
            index += 1
            continue

        if stripped.startswith("|"):
            block = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                block.append(lines[index])
                index += 1
            out.append(render_table(block, in_head))
            continue

        if re.match(r"^\[\d+\] ", stripped):
            out.append(f'<p class="ref">{inline(stripped)}</p>')
            index += 1
            continue

        listed = re.match(r"^(\d+\. |- )", stripped)
        if listed:
            ordered = stripped[0].isdigit()
            items = []
            while index < len(lines) and re.match(r"^(\d+\. |- )", lines[index].strip()):
                items.append(re.sub(r"^(\d+\. |- )", "", lines[index].strip()))
                index += 1
            tag = "ol" if ordered else "ul"
            body = "".join(f"<li>{inline(i)}</li>" for i in items)
            out.append(f"<{tag}>{body}</{tag}>")
            continue

        para = []
        while index < len(lines):
            current = lines[index].strip()
            if not current or set(current) == {"-"}:
                break
            if re.match(r"^(#{1,6} |\||!\[\]\(|\[\d+\] |\d+\. |- )", current):
                break
            para.append(current)
            index += 1
        text = inline(" ".join(para))
        cls = ""
        if in_head and len(out) == 1:
            cls = ' class="title-en span"'
        elif in_head:
            cls = ' class="span"'
        out.append(f"<p{cls}>{text}</p>")

    return f'<div class="cols">{"".join(out)}</div>'


def print_pdf(page_html: str, source: Path, out_pdf: Path) -> None:
    tmp = source.with_suffix(".print.html")
    tmp.write_text(
        f'<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">'
        f"<style>{STYLE}</style></head><body>{page_html}</body></html>",
        encoding="utf-8",
    )
    out_pdf.unlink(missing_ok=True)
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={out_pdf}", f"--user-data-dir=/tmp/pdf-chrome",
         f"file://{tmp}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 90
    size = -1
    while time.monotonic() < deadline:
        if out_pdf.exists():
            current = out_pdf.stat().st_size
            if current > 0 and current == size:
                break
            size = current
        time.sleep(0.5)
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    if not (out_pdf.exists() and out_pdf.stat().st_size > 0):
        raise RuntimeError(f"PDF 생성 실패: {out_pdf}")


def page_count(pdf: Path) -> int:
    probe = subprocess.run(
        ["mdls", "-raw", "-name", "kMDItemNumberOfPages", str(pdf)],
        capture_output=True, text=True,
    )
    value = probe.stdout.strip()
    if value.isdigit():
        return int(value)
    return len(re.findall(rb"/Type\s*/Page[^sR]", pdf.read_bytes()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_pdf")
    parser.add_argument("--source", default=str(ROOT / "paper" / "draft.md"))
    parser.add_argument("--out", default=str(ROOT / "paper" / "draft.pdf"))
    parser.add_argument("--limit", type=int, default=4)
    parser.add_argument("--wide-figures", action="store_true")
    args = parser.parse_args(argv)

    source, out_pdf = Path(args.source), Path(args.out)
    page_html = to_html(source.read_text(encoding="utf-8"), args.wide_figures)
    print_pdf(page_html, source, out_pdf)
    pages = page_count(out_pdf)

    verdict = "OK" if pages <= args.limit else "OVER"
    print(f"MAKE_PDF_DONE pages={pages} limit={args.limit} {verdict} out={out_pdf}")
    return 0 if pages <= args.limit else 1


if __name__ == "__main__":
    sys.exit(main())
