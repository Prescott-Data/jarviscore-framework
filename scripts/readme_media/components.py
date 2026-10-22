"""JarvisCore blueprint: the eight components around the model, grouped by what they do."""

SANS = "'Avenir Next', 'Helvetica Neue', Arial, sans-serif"
MONO = "Menlo, 'SF Mono', monospace"
BLUE, DEEP, LIGHT, CYAN = "#1758F5", "#0533AC", "#35B0FE", "#0CF0E3"
INK, MUTE, PAPER, GRID = "#14213D", "#5B6782", "#F7FAFF", "#E3ECFB"
AMBER, GREEN = "#C9820F", "#1E8E62"

W, H = 1000, 456
out = []
add = out.append


def text(x, y, s, size=12.5, fill=MUTE, font=SANS, weight="400", anchor="start", spacing=None):
    extra = f' letter-spacing="{spacing}"' if spacing else ""
    add(f'<text x="{x}" y="{y}" font-family="{font}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}" text-anchor="{anchor}"{extra}>{s}</text>')


add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
add('<defs>'
    f'<pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse"><path d="M20 0H0V20" fill="none" stroke="{GRID}" stroke-width="0.8"/></pattern>'
    f'<radialGradient id="core"><stop offset="0%" stop-color="#ffffff"/><stop offset="100%" stop-color="#EAF1FF"/></radialGradient>'
    '</defs>')
add(f'<rect width="{W}" height="{H}" rx="18" fill="{PAPER}"/>')
add(f'<rect width="{W}" height="{H}" rx="18" fill="url(#grid)"/>')
add(f'<rect x="0.75" y="0.75" width="{W-1.5}" height="{H-1.5}" rx="18" fill="none" stroke="#C9D8F6" stroke-width="1.5"/>')

# The model, at the top centre
MX, MY = W / 2, 78
add(f'<rect x="{MX-170}" y="{MY-34}" width="340" height="68" rx="34" fill="url(#core)" stroke="{DEEP}" stroke-width="2"/>')
text(MX, MY - 4, "the model", 19, DEEP, weight="600", anchor="middle")
text(MX, MY + 17, "Azure · Claude · Gemini · vLLM", 11, MUTE, MONO, anchor="middle")

groups = [
    ("WRITE", BLUE, [
        ("AutoAgent", "role · capabilities · prompt"),
        ("CustomAgent", "plain Python in execute_task()"),
    ]),
    ("RUN", BLUE, [
        ("Kernel", "roles · budgets · done check"),
        ("Mesh", "peers · shared ledger · pools"),
    ]),
    ("REMEMBER &amp; REACH", GREEN, [
        ("Memory", "notes · episodes · Athena"),
        ("Nexus", "credentials placed at the call"),
        ("Integrations", "typed atoms, auth injected"),
    ]),
    ("PEOPLE", AMBER, [
        ("People in the loop", "approve once, then it runs"),
        ("Rooms", "shared files · Slack"),
    ]),
]

COLS, GAP, LEFT = 4, 18, 28
CW = (W - 2 * LEFT - (COLS - 1) * GAP) / COLS
TOP = 168
for i, (title, color, items) in enumerate(groups):
    x = LEFT + i * (CW + GAP)
    cx = x + CW / 2
    # connector from the model to the group
    add(f'<path d="M{MX:.1f},{MY+34} C{MX:.1f},{(MY+34+TOP)/2:.1f} {cx:.1f},{(MY+34+TOP)/2:.1f} {cx:.1f},{TOP-6}" '
        f'fill="none" stroke="{LIGHT}" stroke-width="1.4" stroke-dasharray="3 4"/>')
    add(f'<circle cx="{cx:.1f}" cy="{TOP-6}" r="3" fill="{color}"/>')
    text(cx, TOP + 18, title, 12, color, weight="600", anchor="middle", spacing="2.2")
    y = TOP + 34
    for name, detail in items:
        h = 74 if len(items) == 2 else 70
        add(f'<rect x="{x:.1f}" y="{y}" width="{CW:.1f}" height="{h - 12}" rx="11" fill="#fff" stroke="{color}" stroke-width="1.6"/>')
        text(x + 16, y + 26, name, 15, INK, weight="600")
        text(x + 16, y + 46, detail, 10.5, DEEP, MONO)
        y += h
    if title == "PEOPLE":
        nx, ny = x + CW - 16, TOP + 34 + 74 + 22
        add(f'<rect x="{nx-58}" y="{ny-11}" width="58" height="18" rx="9" fill="{CYAN}"/>')
        text(nx - 29, ny + 2, "new in 2.3", 10, "#04342f", weight="600", anchor="middle")

text(LEFT, H - 30, "You write the first column.", 14.5, INK, weight="600")
text(LEFT + 205, H - 30, "The runtime supplies the rest, around every call the model makes.", 13, MUTE)
add("</svg>")
open("components.svg", "w").write("\n".join(out))
