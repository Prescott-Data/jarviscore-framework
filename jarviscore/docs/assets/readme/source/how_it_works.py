"""JarvisCore blueprint: an agent's loop as an orbit around the model, beside its mesh."""
import math

SANS = "'Avenir Next', 'Helvetica Neue', Arial, sans-serif"
MONO = "Menlo, 'SF Mono', monospace"
BLUE, DEEP, LIGHT, CYAN = "#1758F5", "#0533AC", "#35B0FE", "#0CF0E3"
INK, MUTE, PAPER, GRID = "#14213D", "#5B6782", "#F7FAFF", "#E3ECFB"
AMBER, GREEN = "#C9820F", "#1E8E62"

W, H = 1000, 540
CX, CY, R = 330, 270, 130
out = []
add = out.append


def pt(deg, r=R):
    a = math.radians(deg)
    return CX + r * math.cos(a), CY + r * math.sin(a)


add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
add('<defs>'
    f'<pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse"><path d="M20 0H0V20" fill="none" stroke="{GRID}" stroke-width="0.8"/></pattern>'
    f'<marker id="head" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0,1 L9,5 L0,9 z" fill="{BLUE}"/></marker>'
    f'<marker id="headg" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0,1 L9,5 L0,9 z" fill="{GREEN}"/></marker>'
    f'<radialGradient id="core"><stop offset="0%" stop-color="#ffffff"/><stop offset="100%" stop-color="#EAF1FF"/></radialGradient>'
    '</defs>')
add(f'<rect width="{W}" height="{H}" rx="18" fill="{PAPER}"/>')
add(f'<rect width="{W}" height="{H}" rx="18" fill="url(#grid)"/>')
add(f'<rect x="0.75" y="0.75" width="{W-1.5}" height="{H-1.5}" rx="18" fill="none" stroke="#C9D8F6" stroke-width="1.5"/>')

# Outer ring: the runtime
add(f'<circle cx="{CX}" cy="{CY}" r="{R+40}" fill="none" stroke="#C9D8F6" stroke-width="1.2"/>')
add(f'<text x="24" y="40" font-family="{SANS}" font-size="12.5" letter-spacing="2.4" fill="{BLUE}" font-weight="600">ONE AGENT TURN</text>')
add(f'<text x="24" y="60" font-family="{SANS}" font-size="12.5" fill="{MUTE}">the outer ring is the runtime:</text>')
add(f'<text x="24" y="77" font-family="{SANS}" font-size="12.5" fill="{MUTE}">it wraps every call, outside</text>')
add(f'<text x="24" y="94" font-family="{SANS}" font-size="12.5" fill="{MUTE}">the model&#8217;s discretion</text>')

# The orbit
add(f'<circle cx="{CX}" cy="{CY}" r="{R}" fill="none" stroke="{BLUE}" stroke-width="2" stroke-dasharray="2 7" stroke-linecap="round"/>')
for a0, a1 in ((193, 255), (285, 318), (342, 18), (42, 75), (105, 167)):
    x0, y0 = pt(a0)
    x1, y1 = pt(a1)
    add(f'<path d="M{x0:.1f},{y0:.1f} A{R},{R} 0 0 1 {x1:.1f},{y1:.1f}" fill="none" stroke="{BLUE}" stroke-width="2.2" marker-end="url(#head)"/>')

# The model
add(f'<circle cx="{CX}" cy="{CY}" r="62" fill="url(#core)" stroke="{DEEP}" stroke-width="2"/>')
add(f'<circle cx="{CX}" cy="{CY}" r="70" fill="none" stroke="{LIGHT}" stroke-width="1" stroke-dasharray="1 4"/>')
add(f'<text x="{CX}" y="{CY-4}" font-family="{SANS}" font-size="19" font-weight="600" fill="{DEEP}" text-anchor="middle">the model</text>')
add(f'<text x="{CX}" y="{CY+16}" font-family="{MONO}" font-size="10.5" fill="{MUTE}" text-anchor="middle">Azure · Claude</text>')
add(f'<text x="{CX}" y="{CY+30}" font-family="{MONO}" font-size="10.5" fill="{MUTE}" text-anchor="middle">Gemini · vLLM</text>')

for deg, n, color in ((180, "1", BLUE), (270, "2", BLUE), (330, "3", BLUE), (30, "4", AMBER), (90, "5", GREEN)):
    x, y = pt(deg)
    add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="15" fill="#fff" stroke="{color}" stroke-width="2.2"/>')
    add(f'<text x="{x:.1f}" y="{y+5:.1f}" font-family="{SANS}" font-size="14" font-weight="700" fill="{color}" text-anchor="middle">{n}</text>')


def leader(x0, y0, x1, y1, color):
    add(f'<path d="M{x0:.1f},{y0:.1f} L{x1:.1f},{y1:.1f}" stroke="{color}" stroke-width="1" fill="none"/>')
    add(f'<circle cx="{x1:.1f}" cy="{y1:.1f}" r="2.6" fill="{color}"/>')


def label(x, y, num, title, lines, color=BLUE, anchor="start"):
    add(f'<text x="{x}" y="{y}" font-family="{SANS}" font-size="16" font-weight="600" fill="{INK}" text-anchor="{anchor}"><tspan fill="{color}">{num}</tspan>  {title}</text>')
    for i, (kind, text) in enumerate(lines, 1):
        font, size, fill = (MONO, 11.5, DEEP) if kind == "code" else (SANS, 12.5, MUTE)
        add(f'<text x="{x}" y="{y + 18*i + (1 if kind != "code" else 0)}" font-family="{font}" font-size="{size}" fill="{fill}" text-anchor="{anchor}">{text}</text>')


x, y = pt(180)
leader(x - 15, y, 150, y, BLUE)
label(24, y - 30, "1", "Context in", [("code", "system_prompt"), ("code", "working_notes"), ("note", "every turn;"), ("note", "never dropped")])

x, y = pt(270)
leader(x, y - 15, x, 98, BLUE)
label(x + 14, 52, "2", "Act", [("code", "search · code · browse · draft"), ("note", "one real tool call, in the agent&#8217;s role")])

x, y = pt(330)
leader(x + 13, y - 8, 520, 172, BLUE)
label(530, 168, "3", "Record", [("code", "work_record · evidence"), ("note", "each call kept, with its result")])

x, y = pt(30)
leader(x + 13, y + 8, 520, 368, AMBER)
label(530, 364, "4", "Approve", [("code", "irreversible → HITLRequest"), ("note", "a person decides; it runs once")], AMBER)

x, y = pt(90)
leader(x, y + 15, x, 452, GREEN)
label(x + 14, 458, "5", "Done, or not", [("code", "done(complete=True|False)"), ("note", "a blocked agent says so, and why")], GREEN)

# The mesh globe, from the logo
GX, GY, GR = 862, 196, 88
add(f'<text x="{GX}" y="80" font-family="{SANS}" font-size="12.5" letter-spacing="2.4" fill="{BLUE}" font-weight="600" text-anchor="middle">THE MESH</text>')
add(f'<circle cx="{GX}" cy="{GY}" r="{GR}" fill="#fff" stroke="{BLUE}" stroke-width="2"/>')
for rx in (GR * 0.78, GR * 0.48, GR * 0.16):
    add(f'<ellipse cx="{GX}" cy="{GY}" rx="{rx:.1f}" ry="{GR}" fill="none" stroke="{LIGHT}" stroke-width="1"/>')
for ry in (GR * 0.62, GR * 0.25):
    add(f'<ellipse cx="{GX}" cy="{GY}" rx="{GR}" ry="{ry:.1f}" fill="none" stroke="{LIGHT}" stroke-width="1"/>')
nodes = [(-50, -44, "scout"), (44, -54, "coder"), (62, 10, "browser"), (-56, 32, "writer"), (6, 60, "you")]
for i, (dx, dy, _) in enumerate(nodes):
    for jx, jy, _ in nodes[i + 1:]:
        add(f'<line x1="{GX+dx}" y1="{GY+dy}" x2="{GX+jx}" y2="{GY+jy}" stroke="{CYAN}" stroke-width="1.4"/>')
for dx, dy, name in nodes:
    add(f'<circle cx="{GX+dx}" cy="{GY+dy}" r="6.5" fill="{DEEP if name != "you" else BLUE}" stroke="#fff" stroke-width="2"/>')
    add(f'<text x="{GX+dx}" y="{GY+dy-11}" font-family="{MONO}" font-size="10.5" fill="{DEEP}" stroke="#fff" stroke-width="3.2" paint-order="stroke" text-anchor="middle">{name}</text>')
add(f'<text x="{GX}" y="{GY+GR+24}" font-family="{SANS}" font-size="13" fill="{INK}" text-anchor="middle">agents find each other by capability</text>')
add(f'<text x="{GX}" y="{GY+GR+42}" font-family="{MONO}" font-size="11.5" fill="{DEEP}" text-anchor="middle">Pool(max=8) · ask_peer · Redis</text>')
add(f'<text x="{GX}" y="{GY+GR+60}" font-family="{SANS}" font-size="12.5" fill="{MUTE}" text-anchor="middle">kill -9 a node; the next run resumes</text>')

# Answer out of station 5
x, y = pt(90)
add(f'<path d="M{x+16:.1f},{y:.1f} C470,{y} 600,430 742,430" stroke="{GREEN}" stroke-width="2" fill="none" marker-end="url(#headg)"/>')
add(f'<rect x="746" y="407" width="226" height="48" rx="10" fill="#fff" stroke="{GREEN}" stroke-width="1.6"/>')
add(f'<text x="762" y="428" font-family="{SANS}" font-size="14.5" font-weight="600" fill="{INK}">result_summary</text>')
add(f'<text x="762" y="445" font-family="{MONO}" font-size="11" fill="{DEEP}">+ output · evidence · status</text>')
add("</svg>")
open("how-it-works.svg", "w").write("\n".join(out))
