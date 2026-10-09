"""StudySynth Master Dashboard (index.html) Generator & Updater.

Maintains a self-contained local library dashboard (index.html) in the root output directory.
Automatically appends or updates cards for generated Study Modules in a clean CSS grid layout.
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import os
import re
from pathlib import Path


REGISTRY_START = "<!-- STUDY_SYNTH_REGISTRY_START -->"
REGISTRY_END = "<!-- STUDY_SYNTH_REGISTRY_END -->"


DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StudySynth Library — Master Dashboard</title>
<style>
:root {
  --bg: #0f172a;
  --surface: #1e293b;
  --surface-hover: #28364e;
  --border: #334155;
  --text-main: #f8fafc;
  --text-muted: #94a3b8;
  --accent: #3b82f6;
  --accent-glow: rgba(59, 130, 246, 0.25);
  --badge-bg: #1e3a8a;
  --badge-text: #93c5fd;
  --success-bg: #064e3b;
  --success-text: #6ee7b7;
  --radius: 12px;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: var(--font);
  background-color: var(--bg);
  color: var(--text-main);
  line-height: 1.5;
  min-height: 100vh;
  padding: 2.5rem 1.5rem;
}

.container {
  max-width: 1200px;
  margin: 0 auto;
}

header {
  margin-bottom: 2.5rem;
  padding-bottom: 1.75rem;
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1.5rem;
}

.brand-section {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.brand-icon {
  width: 48px;
  height: 48px;
  background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  font-size: 1.25rem;
  color: #ffffff;
  box-shadow: 0 4px 12px var(--accent-glow);
}

.brand-info h1 {
  font-size: 1.75rem;
  font-weight: 700;
  letter-spacing: -0.025em;
  color: var(--text-main);
}

.brand-info p {
  color: var(--text-muted);
  font-size: 0.925rem;
}

.stats-bar {
  display: flex;
  gap: 1rem;
  align-items: center;
}

.stat-pill {
  background: var(--surface);
  border: 1px solid var(--border);
  padding: 0.45rem 1rem;
  border-radius: 20px;
  font-size: 0.85rem;
  color: var(--text-muted);
  display: flex;
  gap: 0.5rem;
}

.stat-pill strong {
  color: var(--text-main);
}

.search-section {
  margin-bottom: 2rem;
}

.search-input {
  width: 100%;
  max-width: 480px;
  padding: 0.75rem 1.15rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--text-main);
  font-size: 0.95rem;
  transition: all 0.2s ease;
}

.search-input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-glow);
}

/* CSS Grid layout for study module library cards */
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 1.5rem;
}

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}

.card:hover {
  transform: translateY(-3px);
  border-color: #475569;
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.35);
  background: var(--surface-hover);
}

.card-top {
  margin-bottom: 1.25rem;
}

.card-badges {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.85rem;
}

.badge {
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.25rem 0.6rem;
  border-radius: 6px;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}

.badge-module {
  background: var(--badge-bg);
  color: var(--badge-text);
}

.badge-status {
  background: var(--success-bg);
  color: var(--success-text);
}

.card-title {
  font-size: 1.2rem;
  font-weight: 600;
  line-height: 1.4;
  margin-bottom: 0.5rem;
  color: var(--text-main);
}

.card-meta {
  font-size: 0.85rem;
  color: var(--text-muted);
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.card-footer {
  padding-top: 1.25rem;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.btn-launch {
  background: var(--accent);
  color: #ffffff;
  text-decoration: none;
  font-weight: 600;
  font-size: 0.875rem;
  padding: 0.5rem 1rem;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  transition: background 0.2s ease, transform 0.1s ease;
}

.btn-launch:hover {
  background: #2563eb;
  transform: scale(1.02);
}

.date-text {
  font-size: 0.8rem;
  color: var(--text-muted);
}

.empty-state {
  grid-column: 1 / -1;
  text-align: center;
  padding: 4rem 1.5rem;
  background: var(--surface);
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  color: var(--text-muted);
}

@media (max-width: 640px) {
  body { padding: 1.5rem 1rem; }
  .grid { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="brand-section">
      <div class="brand-icon">SS</div>
      <div class="brand-info">
        <h1>StudySynth Library</h1>
        <p>Interactive Study Modules & Revision Engine</p>
      </div>
    </div>
    <div class="stats-bar">
      <div class="stat-pill">
        <span>Modules:</span>
        <strong id="moduleCount">0</strong>
      </div>
      <div class="stat-pill">
        <span>Storage:</span>
        <strong>Local-First</strong>
      </div>
    </div>
  </header>

  <div class="search-section">
    <input type="text" id="searchInput" class="search-input" placeholder="Search study modules..." onkeyup="filterCards()">
  </div>

  <main class="grid" id="moduleGrid">
    <!-- STUDY_SYNTH_REGISTRY_START -->
    <div class="empty-state">
      <p>No Study Modules generated yet. Run the StudySynth pipeline to create interactive modules.</p>
    </div>
    <script type="application/json" id="studysynth-registry">{"modules":[]}</script>
    <!-- STUDY_SYNTH_REGISTRY_END -->
  </main>
</div>

<script>
function filterCards() {
  const query = (document.getElementById('searchInput').value || '').toLowerCase().trim();
  const cards = document.querySelectorAll('.card');
  cards.forEach(card => {
    const text = card.textContent.toLowerCase();
    card.style.display = text.includes(query) ? '' : 'none';
  });
}
</script>
</body>
</html>
"""


def _load_registry_data(html_content: str) -> list[dict]:
    """Extract registered modules from JSON payload in dashboard HTML."""
    match = re.search(
        r'<script type="application/json" id="studysynth-registry">(.*?)</script>',
        html_content,
        re.DOTALL,
    )
    if match:
        try:
            data = json.loads(match.group(1))
            return data.get("modules", [])
        except Exception:
            pass
    return []


def read_dashboard_entries(dashboard_path: Path | str) -> list[dict]:
    """Read the registered study module entries from a dashboard file."""
    p = Path(dashboard_path)
    if not p.is_file():
        return []
    content = p.read_text(encoding="utf-8")
    return _load_registry_data(content)


def _render_cards(modules: list[dict]) -> str:
    """Render HTML cards and registry script for a list of modules."""
    if not modules:
        cards_html = """      <div class="empty-state">
        <p>No Study Modules generated yet. Run the StudySynth pipeline to create interactive modules.</p>
      </div>"""
    else:
        cards = []
        for m in modules:
            title = html.escape(m.get("title", "Untitled Module"))
            rel_path = html.escape(m.get("path", "#"))
            status = html.escape(m.get("status", "Active"))
            updated = html.escape(m.get("updated", datetime.date.today().isoformat()))
            q_cnt = m.get("question_count")
            q_meta = f"<span>Items: {q_cnt} questions</span>" if q_cnt is not None else ""
            profile = m.get("profile")
            prof_meta = f"<span>Target: {html.escape(str(profile))}</span>" if profile else ""

            card = f"""      <article class="card" data-title="{title}">
        <div class="card-top">
          <div class="card-badges">
            <span class="badge badge-module">Study Module</span>
            <span class="badge badge-status">{status}</span>
          </div>
          <h2 class="card-title">{title}</h2>
          <div class="card-meta">
            <span>File: {rel_path}</span>
            {q_meta}
            {prof_meta}
          </div>
        </div>
        <div class="card-footer">
          <span class="date-text">{updated}</span>
          <a href="{rel_path}" class="btn-launch">Launch Module →</a>
        </div>
      </article>"""
            cards.append(card)
        cards_html = "\n".join(cards)

    data_payload = json.dumps({"modules": modules}, ensure_ascii=False)
    registry_script = f'<script type="application/json" id="studysynth-registry">{data_payload}</script>'

    return f"\n{cards_html}\n      {registry_script}\n"


def generate_dashboard_html(modules: list[dict]) -> str:
    """Generate complete standalone master dashboard HTML for given modules."""
    rendered_block = _render_cards(modules)
    content = DASHBOARD_TEMPLATE
    s_idx = content.find(REGISTRY_START) + len(REGISTRY_START)
    e_idx = content.find(REGISTRY_END)
    updated_content = content[:s_idx] + rendered_block + content[e_idx:]
    updated_content = re.sub(
        r'<span id="moduleCount">\d*</span>',
        f'<span id="moduleCount">{len(modules)}</span>',
        updated_content,
    )
    return updated_content


def update_dashboard(
    dashboard_path: Path | str,
    module_path: Path | str,
    title: str,
    metadata: dict | None = None,
) -> Path:
    """Append or update a Study Module entry in the master dashboard index.html.

    Args:
        dashboard_path: Destination path for index.html (e.g. output/index.html)
        module_path: Absolute or relative path to the generated study module HTML
        title: Clean, human-readable title (e.g. 'Assam Geography v2')
        metadata: Optional dictionary with status, question_count, profile, etc.
    """
    dash_p = Path(dashboard_path).resolve()
    mod_p = Path(module_path).resolve()

    dash_p.parent.mkdir(parents=True, exist_ok=True)

    # Compute relative path from dashboard location to module
    try:
        rel_path = os.path.relpath(mod_p, dash_p.parent)
        # Normalize to web forward slashes
        rel_path = rel_path.replace("\\", "/")
    except ValueError:
        rel_path = str(mod_p)

    meta = metadata or {}
    new_entry = {
        "title": title,
        "path": rel_path,
        "status": meta.get("status", "Comprehensive"),
        "question_count": meta.get("question_count"),
        "profile": meta.get("profile", ""),
        "updated": datetime.date.today().isoformat(),
    }

    if dash_p.is_file():
        content = dash_p.read_text(encoding="utf-8")
    else:
        content = DASHBOARD_TEMPLATE

    # Ensure registry markers exist
    if REGISTRY_START not in content or REGISTRY_END not in content:
        content = DASHBOARD_TEMPLATE

    modules = _load_registry_data(content)

    # Upsert module: replace if existing matching path or title
    matched_idx = -1
    for i, m in enumerate(modules):
        if m.get("path") == rel_path or m.get("title") == title:
            matched_idx = i
            break

    if matched_idx >= 0:
        modules[matched_idx] = new_entry
    else:
        modules.append(new_entry)

    rendered_block = _render_cards(modules)

    # Update HTML between markers
    s_idx = content.find(REGISTRY_START) + len(REGISTRY_START)
    e_idx = content.find(REGISTRY_END)
    updated_content = content[:s_idx] + rendered_block + content[e_idx:]

    # Update module count in header
    updated_content = re.sub(
        r'<span id="moduleCount">\d*</span>',
        f'<span id="moduleCount">{len(modules)}</span>',
        updated_content,
    )

    dash_p.write_text(updated_content, encoding="utf-8")
    return dash_p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Maintain master StudySynth index.html dashboard.")
    ap.add_argument("--dashboard", "-d", default="output/index.html", help="Path to master index.html")
    ap.add_argument("--module", "-m", required=True, help="Path to generated Study Module HTML")
    ap.add_argument("--title", "-t", required=True, help="Clean title for Study Module")
    ap.add_argument("--question-count", type=int, default=None, help="Question count")
    ap.add_argument("--status", default="Comprehensive", help="Package status")
    ap.add_argument("--profile", default="", help="Profile name")
    args = ap.parse_args(argv)

    meta = {
        "question_count": args.question_count,
        "status": args.status,
        "profile": args.profile,
    }

    out = update_dashboard(
        dashboard_path=args.dashboard,
        module_path=args.module,
        title=args.title,
        metadata=meta,
    )
    print(f"OK: Updated Master Dashboard at {out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
