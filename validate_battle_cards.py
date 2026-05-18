#!/usr/bin/env python3
"""
validate_battle_cards.py — Pre-push sanity check for battle-cards.html

Catches the recurring bugs:
  1. Sections nested inside other sections (the superops </div> bug)
  2. Duplicate displaced customer bars in a single section
  3. Float:right displaced bars (should be static .section-sidebar)
  4. Sections missing a company overview-grid
  5. JS restructuring scripts that fight with static HTML

Run before pushing: python3 validate_battle_cards.py
Returns exit code 1 if any issues found.
"""

import re, sys

PATH = '/home/openclaw/.openclaw/workspace/battle-cards.html'
SKIP_IDS = {'integrators', 'quickref'}  # non-competitor sections, no overview needed
BAD_SCRIPTS = ['sidebar-layout', 'displaced-fix', 'overview-reorder']

def get_sections(html):
    return list(re.finditer(
        r'<div[^>]+id="([^"]+)"[^>]*class="section[^"]*"[^>]*>|<div[^>]+class="section[^"]*"[^>]*id="([^"]+)"[^>]*>',
        html
    ))

def check_nesting(html, sections):
    """Detect sections nested inside other sections."""
    from html.parser import HTMLParser
    class Tracker(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.issues = []
        def handle_starttag(self, tag, attrs):
            if tag != 'div': return
            ad = dict(attrs)
            div_id = ad.get('id', '')
            classes = ad.get('class', '').split()
            is_sec = 'section' in classes
            parent = next((s[1] for s in reversed(self.stack) if s[2]), None)
            self.stack.append((tag, div_id, is_sec))
            if is_sec and div_id and parent:
                self.issues.append(f"#{div_id} is nested inside #{parent}")
        def handle_endtag(self, tag):
            if tag == 'div' and self.stack:
                self.stack.pop()
    t = Tracker()
    for i, line in enumerate(html.split('\n')):
        t.feed(line + '\n')
    return t.issues

def check_duplicate_displaced(html, sections):
    issues = []
    for i, m in enumerate(sections):
        sid = m.group(1) or m.group(2)
        start = m.start()
        end = sections[i+1].start() if i+1 < len(sections) else len(html)
        chunk = html[start:end]
        count = len(re.findall(r'float:right;width:220px|class="section-sidebar"', chunk))
        if count > 1:
            issues.append(f"#{sid} has {count} displaced bars (expected 1)")
    return issues

def check_float_bars(html):
    count = len(re.findall(r'float:right;width:220px', html))
    if count:
        return [f"{count} float:right displaced bar(s) still present — should be static .section-sidebar"]
    return []

def check_missing_overviews(html, sections):
    issues = []
    for i, m in enumerate(sections):
        sid = m.group(1) or m.group(2)
        if sid in SKIP_IDS: continue
        start = m.start()
        end = sections[i+1].start() if i+1 < len(sections) else len(html)
        chunk = html[start:end]
        if 'overview-grid' not in chunk:
            issues.append(f"#{sid} is missing a company overview-grid")
    return issues

def check_bad_scripts(html):
    issues = []
    for sid in BAD_SCRIPTS:
        if f'id="{sid}"' in html:
            issues.append(f'JS restructuring script "{sid}" still present — remove it')
    return issues

def main():
    with open(PATH) as f:
        html = f.read()

    sections = get_sections(html)
    all_issues = []

    print(f"Validating {PATH} ({len(sections)} sections found)...")

    checks = [
        ("Section nesting",       check_nesting(html, sections)),
        ("Duplicate sidebars",    check_duplicate_displaced(html, sections)),
        ("Float:right bars",      check_float_bars(html)),
        ("Missing overviews",     check_missing_overviews(html, sections)),
        ("Bad JS scripts",        check_bad_scripts(html)),
    ]

    for name, issues in checks:
        if issues:
            print(f"\n❌ {name}:")
            for iss in issues:
                print(f"   • {iss}")
            all_issues.extend(issues)
        else:
            print(f"  ✅ {name}")

    print()
    if all_issues:
        print(f"❌ {len(all_issues)} issue(s) found — fix before pushing.")
        sys.exit(1)
    else:
        print("✅ All checks passed — safe to push.")
        sys.exit(0)

if __name__ == '__main__':
    main()
