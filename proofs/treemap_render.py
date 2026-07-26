"""Re-render the recorded Treemap run into treemap_render.png.

The committed figure is a build artifact of the render clients: change how a
treemap tile is drawn and the screenshot beside it silently goes stale. This
script regenerates it from the recorded proof instead of a fresh capture, so the
figure keeps depicting the run the README and the pull request describe.

  1. read treemap_run.json      the accepted 10-component surface of the
                                recorded run — no model call, no service
  2. serve app.html verbatim    plus a driver appended AFTER it, which calls the
                                client's own render() and setStatus(), then
                                POSTs back what it rendered
  3. check that report          every tile labelled, the table and buttons
                                intact, the content not cropped
  4. publish treemap_render.png captured by headless Chrome in the same pass

The client is never edited: fidelity is the point, so the figure has to come
from the shipped renderer rather than a lookalike. The driver only supplies the
recorded payload and names the captured run in the badge, because this is a
replay and claiming "composed live" would be false.

Hermetic apart from Chrome — it needs no glc_v3, no Ollama and no S14Code
process:

    uv run python proofs/treemap_render.py
"""

from __future__ import annotations

import json
import queue
import shutil
import socketserver
import subprocess
import tempfile
import threading
import time
from functools import partial
from http.server import BaseHTTPRequestHandler
from pathlib import Path

HERE = Path(__file__).parent
PROOF = HERE / "treemap_run.json"
OUT = HERE / "treemap_render.png"
CLIENT = HERE.parent / "s13code" / "ui" / "client" / "app.html"

# The viewport is the figure's frame, and these values are what the committed
# treemap_render.png was captured at — changing them rewrites the artifact. The
# render is checked to fit inside the frame, so a surface or stylesheet that
# outgrows it fails here instead of quietly producing a cropped screenshot.
# Content currently measures 1361px; the remainder is trailing page background.
CAPTURE_WIDTH = 1280
CAPTURE_HEIGHT = 1384
CAPTURE_SCALE = 2
CHROME_TIMEOUT = 60

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
)

# The driver POSTs its report rather than printing it: that tells this script the
# render finished, and carries the values back without an HTML escaping round
# trip through a DOM dump.
DRIVER = """
<script>
(async () => {
  const c = await (await fetch("/v1/runs/__RUN_ID__/composed")).json();
  document.getElementById("prompt").value = __PROMPT__;
  render(c.surface);
  setStatus('<span class="pill good">' + c.provider + ' \\u00b7 ' + c.component_count
    + ' components \\u00b7 0 executable</span> exact captured run ' + c.run_id);
  await fetch("/report", {method: "POST", body: JSON.stringify({
    badge: document.getElementById("status").textContent.trim(),
    crumbs: document.getElementById("crumbs").textContent.trim(),
    svg_text: [...document.querySelectorAll("#mount svg text")].map(t => t.textContent),
    table_rows: document.querySelectorAll("#mount table tr").length,
    buttons: [...document.querySelectorAll("#mount button")].map(b => b.textContent.trim()),
    content_bottom: Math.ceil(Math.max(...[...document.body.querySelectorAll("*")]
      .map(e => e.getBoundingClientRect().bottom))),
  })});
})();
</script>
"""


def find_chrome() -> str:
    """Locate a Chrome/Chromium binary, or say exactly what is missing."""
    for name in ("google-chrome", "chromium", "chrome"):
        found = shutil.which(name)
        if found: return found
    for path in CHROME_CANDIDATES:
        if Path(path).exists(): return path
    raise SystemExit(
        "no Chrome or Chromium found; install one or add its path to CHROME_CANDIDATES.\n"
        "This script only needs it to rasterise the page — nothing else here uses a browser."
    )


def composed_payload(proof: dict) -> dict:
    """Shape the recorded surface exactly as GET /v1/runs/{id}/composed does."""
    return {
        "run_id": proof["run_id"],
        "finished": True,
        "surface": proof["accepted_surface"],
        "component_count": proof["validator"]["accepted"],
        "clean": proof["validator"]["ok"],
        "provider": proof["provider"],
        "model": proof["model"],
    }


class Handler(BaseHTTPRequestHandler):
    """Serves the real client, stubs the one endpoint it reads, and collects the
    driver's report."""

    def __init__(self, page: bytes, composed: bytes, reports: queue.Queue, *args, **kwargs):
        self.page, self.composed, self.reports = page, composed, reports
        super().__init__(*args, **kwargs)

    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith("/composed"): self._send(self.composed, "application/json")
        elif self.path in ("/", "/app", "/app/"): self._send(self.page, "text/html; charset=utf-8")
        else: self.send_error(404)

    def do_POST(self):
        if self.path != "/report": return self.send_error(404)
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.reports.put(json.loads(raw))
        self._send(b"{}", "application/json")

    def log_message(self, format, *args):
        """Silent: the capture output is the report, not a request log."""


def capture(chrome: str, url: str, reports: queue.Queue, scratch: Path, profile: str) -> dict:
    """Render once, returning the driver's report and leaving the PNG at scratch.

    Headless Chrome often will not exit on its own, so it is stopped as soon as
    both the report and a settled screenshot have arrived rather than sitting out
    the timeout.
    """
    argv = [
        chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--no-first-run", "--no-default-browser-check",
        f"--user-data-dir={profile}",
        f"--force-device-scale-factor={CAPTURE_SCALE}",
        f"--window-size={CAPTURE_WIDTH},{CAPTURE_HEIGHT}",
        "--virtual-time-budget=6000",
        f"--screenshot={scratch}", url,
    ]
    proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    report: dict | None = None
    sizes: list[int] = []
    deadline = time.monotonic() + CHROME_TIMEOUT
    try:
        while time.monotonic() < deadline:
            if report is None:
                try: report = reports.get_nowait()
                except queue.Empty: pass
            if report is not None and scratch.exists():
                sizes.append(scratch.stat().st_size)
                # Two equal readings: Chrome has finished writing the file.
                if sizes[-1] > 0 and len(sizes) >= 2 and sizes[-1] == sizes[-2]: return report
            if proc.poll() is not None and report is not None: return report
            time.sleep(0.2)
    finally:
        proc.kill()
    missing = "no report from the page" if report is None else "no screenshot"
    raise SystemExit(f"Chrome produced {missing} within {CHROME_TIMEOUT}s")


def check(report: dict, proof: dict) -> list[str]:
    """Assert the render shows what the evidence claims. Everything expected is
    derived from the recorded proof, never hardcoded here."""
    accepted = proof["validator"]["accepted"]
    labels = [item["label"] for item in proof["normalized_breakdown"]["items"]]
    buttons = [c for c in proof["accepted_surface"]["components"] if c["type"] == "Button"]
    rendered = set(report["svg_text"])
    failures = []

    if f"{accepted} components" not in report["badge"]:
        failures.append(f"badge does not report {accepted} components: {report['badge']!r}")
    if proof["run_id"] not in report["badge"]:
        failures.append(f"badge does not name the captured run {proof['run_id']}")
    # The whole reason this script exists: narrow tiles used to render unlabelled.
    missing = [label for label in labels if label not in rendered]
    if missing:
        failures.append(f"treemap tiles carry no label: {', '.join(missing)}")
    if report["table_rows"] != len(labels) + 1:
        failures.append(f"table has {report['table_rows']} rows, expected {len(labels) + 1} with its header")
    if len(report["buttons"]) != len(buttons):
        failures.append(f"rendered {len(report['buttons'])} buttons, surface declares {len(buttons)}")
    if report["crumbs"]:
        failures.append(f"a conversation crumb leaked into the figure: {report['crumbs']!r}")
    if report["content_bottom"] > CAPTURE_HEIGHT:
        failures.append(
            f"content is {report['content_bottom']}px tall but the frame is only {CAPTURE_HEIGHT}px, "
            f"so the figure would be cropped; raise CAPTURE_HEIGHT to {report['content_bottom']}"
        )
    return failures


def main() -> None:
    proof = json.loads(PROOF.read_text())
    composed = composed_payload(proof)
    page = CLIENT.read_text() + (
        DRIVER.replace("__RUN_ID__", proof["run_id"])
              .replace("__PROMPT__", json.dumps(proof["request"]["prompt"]))
    )

    chrome = find_chrome()
    reports: queue.Queue = queue.Queue()
    handler = partial(Handler, page.encode(), json.dumps(composed).encode(), reports)
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_address[1]}/"

        with tempfile.TemporaryDirectory() as profile:
            scratch = Path(profile) / "capture.png"
            report = capture(chrome, url, reports, scratch, profile)
            failures = check(report, proof)
            if failures:
                for failure in failures: print(f"  FAIL {failure}")
                raise SystemExit(f"{len(failures)} check(s) failed; {OUT.name} left untouched")
            # Only now replace the committed figure: a failed capture must never
            # destroy the artifact it was meant to refresh.
            shutil.move(str(scratch), OUT)

    parts = len(proof["normalized_breakdown"]["items"])
    print(f"replayed {proof['run_id']}  provider={composed['provider']}  model={composed['model']}")
    print(f"no model call: surface read from {PROOF.name}")
    print(f"components: {composed['component_count']}/{proof['validator']['proposed']} accepted")
    print(f"tiles labelled: {parts}/{parts}")
    print(f"buttons: {', '.join(report['buttons'])}")
    print(f"frame: {CAPTURE_WIDTH}x{CAPTURE_HEIGHT} at {CAPTURE_SCALE}x, content {report['content_bottom']}px")
    print(f"\nwrote {OUT}  ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
