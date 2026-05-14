#!/usr/bin/env python3
"""
Fix battle-cards.html displaced customers bars using JS DOM manipulation approach.
Injects a small script that moves each displaced bar into a proper sidebar layout.
"""

with open("/home/openclaw/.openclaw/workspace/battle-cards.html") as f:
    html = f.read()

# First, undo any partial changes from previous run
# Remove bc-layout wrappers already inserted (keep inner content)
import re

# Undo previous partial fix (unwrap bc-layout divs that were inserted)
def unwrap_bc_layout(h):
    # Pattern: <div class="bc-layout"><div class="bc-main">CONTENT</div>DISPLACED</div>
    # We need to restore: CONTENT + DISPLACED in original flat form
    while '<div class="bc-layout">' in h:
        m = re.search(r'<div class="bc-layout"><div class="bc-main">(.*?)</div>(<div class="displaced-bar">.*?</div>)\s*</div>', h, re.DOTALL)
        if not m:
            break
        # Restore: put displaced back as float:right inside main content... actually just flatten
        inner = m.group(1) + m.group(2)
        h = h[:m.start()] + inner + h[m.end():]
    return h

# Also restore displaced-bar class back to original inline style if needed
def restore_displaced_bars(h):
    # If any displaced-bar class divs exist (from partial run), revert their structure
    h = re.sub(
        r'<div class="displaced-bar"><div class="d-header">([^<]+)</div><ul>(.*?)</ul></div>',
        lambda m: restore_displaced(m.group(1), m.group(2)),
        h,
        flags=re.DOTALL
    )
    return h

def restore_displaced(header, ul_inner):
    # Rebuild old-style displaced div from new style
    items_raw = re.findall(r'<li><span class="chk">✓</span>(.*?)</li>', ul_inner, re.DOTALL)
    items_html = "".join(
        f'<li style="padding:3px 0;font-size:11px;color:#c8f0dc;border-bottom:1px solid #0d2a0d"><span style="color:#3DC570;margin-right:6px">✓</span>{name}</li>'
        for name in items_raw
    )
    return (
        f'<div style="float:right;width:220px;background:#061a0e;border:1px solid #3DC57044;border-radius:8px;padding:12px;margin:0 0 16px 20px">'
        f'<div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:#3DC570;margin-bottom:8px">{header}</div>'
        f'<ul style="list-style:none;margin:0;padding:0">{items_html}</ul>'
        f'</div>'
    )

html = unwrap_bc_layout(html)
html = restore_displaced_bars(html)

# Remove any previously added CSS/JS blocks from this script
html = re.sub(r'\s*/\* Two-column layout.*?\*/', '', html, flags=re.DOTALL)
html = re.sub(r'\s*\.bc-layout\s*\{.*?\}', '', html, flags=re.DOTALL)
html = re.sub(r'\s*\.bc-main\s*\{.*?\}', '', html, flags=re.DOTALL)
html = re.sub(r'\s*\.displaced-bar\s*\{.*?\}', '', html, flags=re.DOTALL)
html = re.sub(r'\s*\.displaced-bar \.d-header\s*\{.*?\}', '', html, flags=re.DOTALL)
html = re.sub(r'\s*\.displaced-bar ul\s*\{.*?\}', '', html, flags=re.DOTALL)
html = re.sub(r'\s*\.displaced-bar ul li[^{]*\{.*?\}', '', html, flags=re.DOTALL)
html = re.sub(r'\s*\.displaced-bar ul li \.chk\s*\{.*?\}', '', html, flags=re.DOTALL)
html = re.sub(r'<script id="displaced-fix">.*?</script>', '', html, flags=re.DOTALL)

# ── Add new CSS ───────────────────────────────────────────────────────────────
new_css = """
  /* Displaced customers sidebar */
  .bc-layout { display: grid; grid-template-columns: 1fr 230px; gap: 28px; align-items: start; }
  .bc-main { min-width: 0; }
  .displaced-bar {
    position: sticky;
    top: 130px;
    background: #061a0e;
    border: 1px solid #3DC57055;
    border-radius: 10px;
    padding: 14px 12px;
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
  .displaced-bar .chk { color: #3DC570; font-weight: 700; flex-shrink: 0; }
"""
html = html.replace("</style>", new_css + "\n</style>", 1)

# ── Add JS to restructure at runtime ─────────────────────────────────────────
fix_js = """<script id="displaced-fix">
(function() {
  function fixSection(section) {
    // Find the float:right displaced div anywhere in the section
    var displaced = null;
    var all = section.querySelectorAll('div');
    for (var i = 0; i < all.length; i++) {
      var s = all[i].getAttribute('style') || '';
      if (s.indexOf('float:right') !== -1 && s.indexOf('220px') !== -1) {
        displaced = all[i];
        break;
      }
    }
    if (!displaced) return;

    // Build new displaced bar
    var header = '';
    var hEl = displaced.querySelector('div');
    if (hEl) header = hEl.textContent.trim();

    var items = displaced.querySelectorAll('li');
    var ul = document.createElement('ul');
    items.forEach(function(li) {
      var name = li.textContent.replace(/^✓\\s*/, '').trim();
      var newLi = document.createElement('li');
      var chk = document.createElement('span');
      chk.className = 'chk';
      chk.textContent = '✓';
      newLi.appendChild(chk);
      newLi.appendChild(document.createTextNode(name));
      ul.appendChild(newLi);
    });

    var bar = document.createElement('div');
    bar.className = 'displaced-bar';
    var dHead = document.createElement('div');
    dHead.className = 'd-header';
    dHead.textContent = header;
    bar.appendChild(dHead);
    bar.appendChild(ul);

    // Remove old displaced div from its parent
    displaced.parentNode.removeChild(displaced);

    // Wrap section contents in bc-layout
    var layout = document.createElement('div');
    layout.className = 'bc-layout';
    var main = document.createElement('div');
    main.className = 'bc-main';

    // Move all section children into main
    while (section.firstChild) {
      main.appendChild(section.firstChild);
    }
    layout.appendChild(main);
    layout.appendChild(bar);
    section.appendChild(layout);
  }

  document.querySelectorAll('.section').forEach(fixSection);
})();
</script>"""

# Insert just before </body>
html = html.replace("</body>", fix_js + "\n</body>")

with open("/home/openclaw/.openclaw/workspace/battle-cards.html", "w") as f:
    f.write(html)

print("✅ Done — JS-based displaced bar fix applied")
