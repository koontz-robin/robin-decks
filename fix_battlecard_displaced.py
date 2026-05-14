#!/usr/bin/env python3
"""
Restructure battle-cards.html so each competitor section uses a
two-column layout: main content left, displaced customers sticky sidebar right.
"""

import re

with open("/home/openclaw/.openclaw/workspace/battle-cards.html") as f:
    html = f.read()

# ── 1. Add CSS for the new layout ────────────────────────────────────────────
new_css = """
  /* Two-column layout: main content + displaced sidebar */
  .bc-layout { display: grid; grid-template-columns: 1fr 230px; gap: 28px; align-items: start; }
  .bc-main { min-width: 0; }
  .displaced-bar {
    position: sticky;
    top: 130px;
    background: #061a0e;
    border: 1px solid #3DC57044;
    border-radius: 10px;
    padding: 14px;
    align-self: start;
  }
  .displaced-bar .d-header {
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #3DC570;
    margin-bottom: 10px;
    padding-bottom: 8px;
    border-bottom: 1px solid #3DC57033;
  }
  .displaced-bar ul { list-style: none; margin: 0; padding: 0; }
  .displaced-bar ul li {
    padding: 5px 0;
    font-size: 11px;
    color: #c8f0dc;
    border-bottom: 1px solid #0d2a0d;
    display: flex;
    align-items: flex-start;
    gap: 6px;
    line-height: 1.4;
  }
  .displaced-bar ul li:last-child { border-bottom: none; }
  .displaced-bar ul li .chk { color: #3DC570; font-weight: 700; flex-shrink: 0; }
"""

# Insert new CSS before closing </style>
html = html.replace("</style>", new_css + "\n</style>", 1)

# ── 2. For each section div, extract and restructure ─────────────────────────
# Pattern to find the displaced div (the float:right box inside sections)
displaced_pattern = re.compile(
    r'<div style="float:right;width:220px[^"]*">(.*?)</div>\s*</div>',
    re.DOTALL
)

def extract_customers(displaced_html):
    """Parse the customer list from the old displaced div HTML and return (count_label, list_items)."""
    # Extract header text
    header_m = re.search(r'color:#3DC570;margin-bottom:8px">([^<]+)</div>', displaced_html)
    header = header_m.group(1) if header_m else "Displaced Customers"

    # Extract customer names
    names = re.findall(r'</span>([^<]+)</li>', displaced_html)
    return header, names

def build_displaced_bar(header, names):
    items = "\n".join(
        f'<li><span class="chk">✓</span>{name}</li>'
        for name in names
    )
    return (
        f'<div class="displaced-bar">'
        f'<div class="d-header">{header}</div>'
        f'<ul>{items}</ul>'
        f'</div>'
    )

def restructure_section(section_html):
    """Wrap section content in two-column layout with displaced bar on right."""
    # Find the displaced div - it appears right inside overview-grid or just after it
    disp_match = re.search(
        r'(<div style="float:right;width:220px.*?</div>\s*</div>)',
        section_html,
        re.DOTALL
    )
    if not disp_match:
        return section_html  # No displaced box, leave as-is

    full_match = disp_match.group(0)

    # The displaced div is the last </div> in the match — it closes the overview-grid li
    # Find just the displaced div itself (starts at float:right)
    disp_start = section_html.find('<div style="float:right;width:220px')
    if disp_start == -1:
        return section_html

    # Find the closing tag of the displaced div
    # Count nested divs to find the correct closing tag
    pos = disp_start
    depth = 0
    disp_end = -1
    while pos < len(section_html):
        open_m = re.search(r'<div', section_html[pos:])
        close_m = re.search(r'</div>', section_html[pos:])
        if not close_m:
            break
        if not open_m or close_m.start() < open_m.start():
            if depth == 0:
                disp_end = pos + close_m.end()
                break
            depth -= 1
            pos += close_m.end()
        else:
            depth += 1
            pos += open_m.end()

    if disp_end == -1:
        return section_html

    displaced_html = section_html[disp_start:disp_end]
    header, names = extract_customers(displaced_html)
    displaced_bar = build_displaced_bar(header, names)

    # Remove displaced div from its current position
    main_content = section_html[:disp_start] + section_html[disp_end:]

    # Wrap in two-column layout
    # Insert wrapper after the opening <div class="section..."> tag
    section_open_end = main_content.find('>') + 1
    inner = main_content[section_open_end:]

    new_inner = (
        f'<div class="bc-layout">'
        f'<div class="bc-main">{inner}</div>'
        f'{displaced_bar}'
        f'</div>'
    )
    return main_content[:section_open_end] + new_inner

# Process all section divs
section_pattern = re.compile(
    r'(<div class="section[^"]*"[^>]*>)(.*?)(</div>\s*\n)',
    re.DOTALL
)

# Actually, sections are closed with </div>\n\n<!-- ===== next section
# Let's process section by section by splitting on section comments and section divs

# Find all section boundaries
section_blocks = re.findall(
    r'(<div class="section[^"]*" id="[^"]*">.*?</div>)(?=\s*\n\s*(?:<!--|\s*$|\s*</main>))',
    html,
    re.DOTALL
)

print(f"Found {len(section_blocks)} sections")

for block in section_blocks:
    new_block = restructure_section(block)
    if new_block != block:
        html = html.replace(block, new_block, 1)
        # Extract section id for logging
        id_m = re.search(r'id="([^"]+)"', block)
        sid = id_m.group(1) if id_m else "unknown"
        print(f"  ✅ Restructured: {sid}")
    else:
        id_m = re.search(r'id="([^"]+)"', block)
        sid = id_m.group(1) if id_m else "unknown"
        disp_check = 'float:right;width:220px' in block
        print(f"  {'⚠️  has float but no restructure' if disp_check else '-- no displaced box'}: {sid}")

with open("/home/openclaw/.openclaw/workspace/battle-cards.html", "w") as f:
    f.write(html)

print("\n✅ Done")
