"""
Render the AETHER markdown documents to print-ready PDFs.

Converts markdown to HTML, wraps it in a print stylesheet that matches the
AETHER visual identity, then drives a headless Chromium (Edge or Chrome, both
already present on Windows) to print to PDF. No LaTeX, no pandoc, no extra
runtime.

Run:  python scripts/build_docs_pdf.py
Out:  docs/pdf/*.pdf
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

try:
    import markdown
except ImportError:
    sys.exit("markdown is not installed. Run: pip install markdown")

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT = DOCS / "pdf"

BROWSERS = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
]

# (source, output stem, subtitle shown under the title)
DOCUMENTS = [
    (
        "architecture.md",
        "AETHER-Architecture",
        "System design, the decisions taken and why, and the build plan to demo.",
    ),
    (
        "test-strategy.md",
        "AETHER-Test-Strategy",
        "What gets tested in the vertical slice, and what deliberately does not.",
    ),
]

STYLESHEET = """
@page {
  size: A4;
  margin: 17mm 15mm 16mm 15mm;
}

:root {
  --ink:      #131E1D;
  --ink-mid:  #3C4B49;
  --ink-mute: #63736F;
  --rule:     #C9D4D1;
  --rule-soft:#E2E9E7;
  --accent:   #0E635B;
  --tint:     #F1F5F4;
  --warn:     #8A5808;
  --crit:     #8F2739;

  --serif: "Cambria", "Palatino Linotype", Georgia, serif;
  --sans:  "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  --mono:  "Cascadia Mono", Consolas, "Courier New", monospace;
}

* { box-sizing: border-box; }

html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }

body {
  margin: 0;
  font-family: var(--sans);
  font-size: 9.6pt;
  line-height: 1.55;
  color: var(--ink);
  background: #fff;
}

/* ---------- cover block ---------- */
.cover { border-bottom: 2.5pt solid var(--ink); padding-bottom: 9pt; margin-bottom: 16pt; }
.cover .mark {
  font-family: var(--mono);
  font-size: 8pt;
  letter-spacing: .26em;
  font-weight: 700;
  color: var(--accent);
  margin-bottom: 7pt;
}
.cover h1 {
  font-family: var(--serif);
  font-size: 25pt;
  line-height: 1.08;
  letter-spacing: -.01em;
  margin: 0 0 5pt;
  font-weight: 700;
}
.cover .sub { font-size: 11pt; color: var(--ink-mid); margin: 0 0 9pt; }
.cover .meta {
  font-family: var(--mono);
  font-size: 7.4pt;
  letter-spacing: .04em;
  color: var(--ink-mute);
  display: flex;
  flex-wrap: wrap;
  gap: 0 16pt;
}
.cover .meta b { color: var(--ink-mid); font-weight: 600; }

.simnote {
  border: .6pt solid var(--rule);
  border-left: 2.5pt solid var(--warn);
  background: #FBF7EF;
  padding: 6pt 9pt;
  margin: 0 0 16pt;
  font-size: 8.2pt;
  color: var(--ink-mid);
  break-inside: avoid;
}
.simnote b { color: var(--warn); font-family: var(--mono); font-size: 7.4pt; letter-spacing: .1em; }

/* ---------- headings ---------- */
h1, h2, h3, h4 { break-after: avoid; break-inside: avoid; text-wrap: balance; }

h1 {
  font-family: var(--serif);
  font-size: 17pt;
  margin: 20pt 0 8pt;
  padding-bottom: 4pt;
  border-bottom: 1pt solid var(--rule);
  font-weight: 700;
}
h2 {
  font-family: var(--serif);
  font-size: 13.5pt;
  margin: 16pt 0 6pt;
  padding-bottom: 3pt;
  border-bottom: .6pt solid var(--rule-soft);
  font-weight: 700;
}
h3 {
  font-family: var(--sans);
  font-size: 10.2pt;
  font-weight: 700;
  margin: 13pt 0 4pt;
}
h4 {
  font-family: var(--mono);
  font-size: 8pt;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--ink-mute);
  margin: 11pt 0 4pt;
}

p { margin: 0 0 7pt; }
ul, ol { margin: 0 0 7pt; padding-left: 15pt; }
li { margin-bottom: 3pt; }
li::marker { color: var(--ink-mute); }
strong { font-weight: 700; }

blockquote {
  margin: 0 0 9pt;
  padding: 7pt 11pt;
  background: var(--tint);
  border-left: 2.5pt solid var(--accent);
  font-size: 10pt;
  break-inside: avoid;
}
blockquote p { margin: 0; }

hr { border: 0; border-top: .6pt solid var(--rule); margin: 14pt 0; }

/* ---------- code ---------- */
code {
  font-family: var(--mono);
  font-size: 8.4pt;
  background: var(--tint);
  border: .5pt solid var(--rule-soft);
  padding: .3pt 2pt;
  border-radius: 1.5pt;
}
pre {
  font-family: var(--mono);
  font-size: 8.2pt;
  line-height: 1.5;
  background: var(--tint);
  border: .6pt solid var(--rule);
  border-radius: 2pt;
  padding: 8pt 10pt;
  margin: 0 0 9pt;
  white-space: pre-wrap;
  word-break: break-word;
  break-inside: avoid;
}
pre code { background: none; border: 0; padding: 0; font-size: inherit; }

/* ---------- tables ---------- */
table {
  border-collapse: collapse;
  width: 100%;
  font-size: 8.4pt;
  line-height: 1.42;
  margin: 0 0 10pt;
  break-inside: auto;
}
thead { display: table-header-group; }
tr { break-inside: avoid; }
thead th {
  text-align: left;
  font-family: var(--mono);
  font-size: 7.2pt;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--ink-mute);
  font-weight: 700;
  background: var(--tint);
  border-bottom: .8pt solid var(--rule);
  padding: 5pt 6pt;
}
tbody td {
  padding: 4.5pt 6pt;
  border-bottom: .5pt solid var(--rule-soft);
  vertical-align: top;
}
tbody tr:nth-child(even) td { background: #FAFCFB; }
td code { font-size: 7.8pt; }

/* Keep short sections together where possible. */
h3 + p, h3 + ul, h3 + table { break-before: avoid; }
"""

HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{title}</title>
<style>{css}</style>
</head><body>
<div class="cover">
  <div class="mark">AETHER</div>
  <h1>{title}</h1>
  <p class="sub">{subtitle}</p>
  <div class="meta">
    <span><b>Project</b> Autonomous Margin &amp; Collateral Intelligence</span>
    <span><b>Programme</b> GIFT IFIH Young Builders</span>
    <span><b>Revision</b> B</span>
    <span><b>Generated</b> {generated}</span>
  </div>
</div>

<div class="simnote">
  <b>PROTOTYPE DOCUMENT</b><br>
  Describes a prototype under construction. All market data, counterparties, portfolios and
  legal documents referenced are <strong>simulated</strong> and clearly labelled as such in
  the repository. Nothing here asserts regulatory approval, certification under any industry
  methodology, or connectivity to any market infrastructure.
</div>

{body}
</body></html>
"""


def find_browser() -> Path:
    for candidate in BROWSERS:
        if candidate.exists():
            return candidate
    sys.exit("No Edge or Chrome installation found. Cannot render PDFs.")


def build_html(md_path: Path, subtitle: str) -> tuple[str, str]:
    """Convert markdown to a print-ready HTML document. Returns (title, html)."""
    text = md_path.read_text(encoding="utf-8")

    # Lift the leading H1 out of the body and use it as the document title.
    match = re.match(r"^#\s+(.+?)\n", text)
    if match:
        title = match.group(1).strip()
        text = text[match.end() :]
    else:
        title = md_path.stem.replace("-", " ").title()

    # Strip an "AETHER <dash> " prefix; the wordmark above already carries it.
    # Matches hyphen, en dash (U+2013) and em dash (U+2014).
    title = re.sub(r"^AETHER\s*[-–—]\s*", "", title).strip()

    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
        output_format="html5",
    )

    html = HTML.format(
        title=title,
        subtitle=subtitle,
        css=STYLESHEET,
        body=body,
        generated=date.today().isoformat(),
    )
    return title, html


def render_pdf(browser: Path, html_path: Path, pdf_path: Path) -> None:
    """Print one HTML file to PDF via headless Chromium.

    Chromium's parent process can exit before the PDF is flushed to disk, so the
    file is polled for rather than checked once. A dedicated --user-data-dir keeps
    the run from colliding with an interactive browser session.
    """
    profile = Path(tempfile.gettempdir()) / "aether-pdf-profile"
    url = html_path.resolve().as_uri()
    cmd = [
        str(browser),
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--no-first-run",
        f"--user-data-dir={profile}",
        "--no-pdf-header-footer",
        "--print-to-pdf-no-header",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=4000",
        f"--print-to-pdf={pdf_path.resolve()}",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)

    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if pdf_path.exists() and pdf_path.stat().st_size > 1024:
            time.sleep(0.4)  # let the final write settle
            return
        time.sleep(0.3)

    sys.exit(f"Render failed for {pdf_path.name}\nexit={result.returncode}\n{result.stderr[:800]}")


def main() -> int:
    browser = find_browser()
    OUT.mkdir(parents=True, exist_ok=True)
    work = OUT / "_html"
    work.mkdir(exist_ok=True)

    print(f"  Renderer: {browser.name}\n")
    for source, stem, subtitle in DOCUMENTS:
        md_path = DOCS / source
        if not md_path.exists():
            print(f"  SKIP  {source} (not found)")
            continue

        title, html = build_html(md_path, subtitle)
        html_path = work / f"{stem}.html"
        html_path.write_text(html, encoding="utf-8")

        pdf_path = OUT / f"{stem}.pdf"
        pdf_path.unlink(missing_ok=True)
        render_pdf(browser, html_path, pdf_path)

        size_kb = pdf_path.stat().st_size / 1024
        print(f"  OK    {pdf_path.relative_to(ROOT).as_posix():<40} {size_kb:6.1f} KB   {title}")

    shutil.rmtree(work, ignore_errors=True)
    print(f"\n  Written to {OUT.relative_to(ROOT).as_posix()}/\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
