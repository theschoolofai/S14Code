"""Build a self-contained HTML evidence page for the Part 2 boundary attack.

Reads proofs/part2/turn_4_raw_surface.json and turn_4_validator_verdict.json,
embeds them inline, and writes proofs/part2/turn_4_evidence.html. The page
uses text content only (no innerHTML from data) so it mirrors the render
client's own safety contract.
"""
from __future__ import annotations

import html
import json
import pathlib

HERE = pathlib.Path(__file__).parent
RAW = json.loads((HERE / "part2" / "turn_4_raw_surface.json").read_text(encoding="utf-8-sig"))
VERDICT = json.loads((HERE / "part2" / "turn_4_validator_verdict.json").read_text(encoding="utf-8-sig"))
OUT = HERE / "part2" / "turn_4_evidence.html"

RAW_STR = json.dumps(RAW, indent=2)
VERDICT_STR = json.dumps(VERDICT, indent=2)

rows_html = "".join(
    f'<tr><td class="mono">{html.escape(r["component_id"])}.{html.escape(r["field"])}</td>'
    f'<td><span class="inv inv-{r["invariant"]}">{html.escape(r["invariant"])}</span></td>'
    f'<td>{html.escape(r["reason"])}</td></tr>'
    for r in VERDICT["rejections"]
)

accepted_str = ", ".join(VERDICT["accepted"]) or "(none)"

page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Turn 4 -- boundary attack refused at the wall</title>
<style>
  body{{font-family:'Inter',system-ui,sans-serif;margin:0;padding:24px;background:#F7F8FA;color:#111}}
  h1{{font-family:'Palatino Linotype',Palatino,Georgia,serif;font-size:26px;margin:0 0 4px}}
  .sub{{color:#555;margin-bottom:20px;font-size:14px;line-height:1.55}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
  .pane{{background:#fff;border:1px solid #E8E8E8;border-radius:12px;padding:16px}}
  .pane h2{{margin:0 0 10px;font-size:14px;text-transform:uppercase;letter-spacing:.08em;color:#555;font-family:'JetBrains Mono',ui-monospace,Menlo,monospace}}
  pre{{background:#FAFAFA;border:1px solid #E8E8E8;border-radius:8px;padding:10px;font-family:'JetBrains Mono',ui-monospace,Menlo,monospace;font-size:11px;line-height:1.5;white-space:pre-wrap;word-break:break-word;max-height:600px;overflow:auto;margin:0}}
  table{{width:100%;border-collapse:collapse;margin-top:6px}}
  th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #E8E8E8;font-size:13px;vertical-align:top}}
  th{{font-family:'JetBrains Mono',monospace;font-size:11px;text-transform:uppercase;color:#555}}
  .mono{{font-family:'JetBrains Mono',monospace;font-size:12px;color:#111}}
  .inv{{font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;padding:2px 8px;border-radius:999px;display:inline-block;text-transform:uppercase;letter-spacing:.05em}}
  .inv-catalog{{background:rgba(220,38,38,.10);color:#B91C1C}}
  .inv-data-not-code{{background:rgba(217,119,6,.14);color:#B45309}}
  .inv-event{{background:rgba(37,99,235,.08);color:#2563EB}}
  .banner{{background:#fff;border:1px solid #E8E8E8;border-radius:12px;padding:14px 18px;margin-bottom:16px;display:flex;gap:20px;align-items:center;flex-wrap:wrap;font-size:13px}}
  .pill{{background:rgba(220,38,38,.10);color:#B91C1C;padding:4px 12px;border-radius:999px;font-weight:600;font-size:12px;font-family:'JetBrains Mono',monospace}}
  .pill.good{{background:rgba(22,163,74,.12);color:#15803D}}
  b{{font-family:'JetBrains Mono',monospace;font-size:12px}}
</style></head><body>
<h1>Turn 4 &mdash; boundary attack refused at the wall</h1>
<div class="sub">Live capture from Part 2 of the fitness-coach conversation. When told
to include a <b>RawHtml</b> node, a bound value carrying markup, and a
<b>bookmark</b> action never registered in the catalog, Gemini produced the
surface on the left. <b>POST /v1/validate</b> on the running S14 server refuses
it with <b>{len(VERDICT["rejections"])} rejections</b> covering all three
invariant classes; the only accepted survivor is <code>{html.escape(accepted_str)}</code>.</div>
<div class="banner">
  <span class="pill">ok: {str(VERDICT["ok"]).lower()}</span>
  <span>attack surface: <b>{len(RAW["components"])} components proposed</b></span>
  <span>wall verdict: <b>{len(VERDICT["accepted"])} accepted / {len(VERDICT["rejections"])} rejected</b></span>
  <span>provider: <b>gemini_1</b> &middot; model: <b>gemini-2.5-flash</b></span>
</div>
<div class="grid">
  <div class="pane">
    <h2>Raw surface Gemini emitted (attack)</h2>
    <pre>{html.escape(RAW_STR)}</pre>
  </div>
  <div class="pane">
    <h2>Validator verdict (POST /v1/validate)</h2>
    <table>
      <tr><th>Component.field</th><th>Invariant</th><th>Reason</th></tr>
      {rows_html}
    </table>
  </div>
</div>
</body></html>
"""

OUT.write_text(page, encoding="utf-8")
print(f"wrote {OUT} ({len(page)} bytes)")
