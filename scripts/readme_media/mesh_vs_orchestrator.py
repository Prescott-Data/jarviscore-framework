"""JarvisCore blueprint: a central orchestrator beside a mesh of equal peers."""
import math

SANS = "'Avenir Next', 'Helvetica Neue', Arial, sans-serif"
MONO = "Menlo, 'SF Mono', monospace"
BLUE, DEEP, LIGHT, CYAN = "#1758F5", "#0533AC", "#35B0FE", "#0CF0E3"
INK, MUTE, PAPER, GRID = "#14213D", "#5B6782", "#F7FAFF", "#E3ECFB"
AMBER, GREEN, RED = "#C9820F", "#1E8E62", "#C2410C"

W, H = 1000, 500
out = []
add = out.append


def text(x, y, s, size=12.5, fill=MUTE, font=SANS, weight="400", anchor="start", spacing=None, halo=False):
    extra = f' letter-spacing="{spacing}"' if spacing else ""
    if halo:
        extra += f' stroke="{PAPER}" stroke-width="4" paint-order="stroke"'
    add(f'<text x="{x}" y="{y}" font-family="{font}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}" text-anchor="{anchor}"{extra}>{s}</text>')


def node(x, y, name, r=7, fill=DEEP, label_dy=-13):
    add(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="#fff" stroke-width="2.2"/>')
    text(x, y + label_dy, name, 11, DEEP, MONO, anchor="middle", halo=True)


add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
add('<defs>'
    f'<pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse"><path d="M20 0H0V20" fill="none" stroke="{GRID}" stroke-width="0.8"/></pattern>'
    f'<marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,1 L9,5 L0,9 z" fill="{MUTE}"/></marker>'
    '</defs>')
add(f'<rect width="{W}" height="{H}" rx="18" fill="{PAPER}"/>')
add(f'<rect width="{W}" height="{H}" rx="18" fill="url(#grid)"/>')
add(f'<rect x="0.75" y="0.75" width="{W-1.5}" height="{H-1.5}" rx="18" fill="none" stroke="#C9D8F6" stroke-width="1.5"/>')
add(f'<line x1="500" y1="34" x2="500" y2="{H-34}" stroke="#C9D8F6" stroke-width="1.2" stroke-dasharray="3 6"/>')

# ── A: a central orchestrator ───────────────────────────────────────────────
text(36, 46, "A · CENTRAL ORCHESTRATOR", 12.5, MUTE, weight="600", spacing="2.4")
text(36, 68, "one process plans, routes and holds the state", 12.5, MUTE)

OX, OY = 250, 238
workers = [(-150, -76, "scout"), (150, -76, "coder"), (-150, 84, "browser"), (150, 84, "writer")]
for dx, dy, _ in workers:
    d = math.hypot(dx, dy)
    ex, ey = OX + dx * (1 - 14 / d), OY + dy * (1 - 14 / d)
    add(f'<line x1="{OX}" y1="{OY}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="{MUTE}" stroke-width="1.4" marker-end="url(#arrow)"/>')
for dx, dy, name in workers:
    node(OX + dx, OY + dy, name, fill="#8A95AD", label_dy=-13 if dy < 0 else 24)
add(f'<rect x="{OX-80}" y="{OY-25}" width="160" height="50" rx="10" fill="#fff" stroke="{INK}" stroke-width="1.8"/>')
text(OX, OY - 2, "orchestrator", 14.5, INK, weight="600", anchor="middle")
text(OX, OY + 14, "plans · routes · state", 10.5, MUTE, MONO, anchor="middle")
# the single point of failure
add(f'<circle cx="{OX+80}" cy="{OY-25}" r="11" fill="#fff" stroke="{RED}" stroke-width="2"/>')
text(OX + 80, OY - 20.5, "!", 13, RED, weight="700", anchor="middle")
text(OX, OY + 46, "single point of failure", 11, RED, MONO, anchor="middle", halo=True)
text(36, 398, "If it stops, everything stops.", 14.5, INK, weight="600")
text(36, 420, "Agents hold their own keys, and every request", 12.5, MUTE)
text(36, 438, "and every result passes through one place.", 12.5, MUTE)

# ── B: a mesh of equal peers ────────────────────────────────────────────────
text(536, 46, "B · PEER MESH  (JARVISCORE)", 12.5, BLUE, weight="600", spacing="2.4")
text(536, 68, "every agent is a peer; none of them is in charge", 12.5, MUTE)

MX, MY, MR = 730, 196, 98
peers = [(-90, "scout"), (-18, "coder"), (54, "browser"), (126, "writer"), (198, "analyst")]
pos = []
for deg, name in peers:
    a = math.radians(deg)
    pos.append((MX + MR * math.cos(a), MY + MR * 0.72 * math.sin(a), name))
for i, (x0, y0, n0) in enumerate(pos):
    for x1, y1, n1 in pos[i + 1:]:
        if "analyst" in (n0, n1):
            add(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" stroke="#C9D3E6" stroke-width="1.2" stroke-dasharray="3 4"/>')
        else:
            add(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" stroke="{CYAN}" stroke-width="1.5"/>')
text(536, 86, "they find each other by capability over SWIM gossip", 12.5, MUTE)

# the shared ledger
LY = 352
add(f'<rect x="586" y="{LY}" width="288" height="38" rx="9" fill="#fff" stroke="{BLUE}" stroke-width="1.8"/>')
text(730, LY + 17, "shared ledger", 13.5, INK, weight="600", anchor="middle")
text(730, LY + 31, "steps · claims · results  (Redis)", 10.5, DEEP, MONO, anchor="middle")
for x, y, name in pos:
    if y > MY - 40 and name != "analyst":
        add(f'<line x1="{x:.1f}" y1="{y+8:.1f}" x2="{x:.1f}" y2="{LY:.0f}" stroke="{BLUE}" stroke-width="1.2" stroke-dasharray="3 4"/>')
STOPPED = "analyst"
for x, y, name in pos:
    dy = -13 if y < MY else 22
    if name == STOPPED:
        add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="{PAPER}" stroke="#8A95AD" stroke-width="2" stroke-dasharray="2 2"/>')
        text(x, y + dy, "analyst · stopped", 11, "#8A95AD", MONO, anchor="middle", halo=True)
    else:
        node(x, y, name, label_dy=dy)

# the broker
BX, BY = 930, 196
add(f'<rect x="{BX-46}" y="{BY-22}" width="92" height="44" rx="10" fill="#fff" stroke="{GREEN}" stroke-width="1.8"/>')
text(BX, BY - 2, "Nexus", 14, INK, weight="600", anchor="middle")
text(BX, BY + 13, "zero-trust", 10.5, GREEN, MONO, anchor="middle")
bx, by, _ = pos[2]
add(f'<line x1="{bx+9:.1f}" y1="{by:.1f}" x2="{BX-46}" y2="{BY+6}" stroke="{GREEN}" stroke-width="1.4"/>')
cx, cy, _ = pos[1]
add(f'<line x1="{cx+9:.1f}" y1="{cy:.1f}" x2="{BX-46}" y2="{BY-8}" stroke="{GREEN}" stroke-width="1.4"/>')

text(536, 420, "A node stops; a peer claims its step from the ledger.", 14.5, INK, weight="600")
text(536, 442, "Credentials are placed at the call by the broker,", 12.5, MUTE)
text(536, 460, "never held by an agent.", 12.5, MUTE)

add("</svg>")
open("mesh-vs-orchestrator.svg", "w").write("\n".join(out))
