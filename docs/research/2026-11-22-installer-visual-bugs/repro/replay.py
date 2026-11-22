import sys, pyte, re
path, cols, rows = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
data = open(path, "rb").read().decode("utf-8", "replace")
scr = pyte.Screen(cols, rows); st = pyte.Stream(scr)
snap = None; i = 0
# feed per frame boundary (each redraw starts with CSI n F)
parts = re.split(r"(?=\x1b\[\d+F)", data)
for part in parts:
    st.feed(part)
    disp = [l.rstrip() for l in scr.display]
    if any("Verify installation" in l and "running" in l for l in disp):
        snap = list(disp)
print("=== last frame with 'Verify installation running' ===")
print("\n".join(snap or ["<none>"]))
print("=== final screen ===")
print("\n".join(l.rstrip() for l in scr.display))
