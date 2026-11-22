"""Drive bootstrap.InstallReporter through the real call order into a pyte screen."""
import io, os, sys, threading
cols, rows = int(sys.argv[1]), int(sys.argv[2])
mode = sys.argv[3] if len(sys.argv) > 3 else "real"
os.environ["COLUMNS"] = str(cols); os.environ["LINES"] = str(rows)
os.environ.setdefault("COLORTERM", "truecolor"); os.environ["TERM"] = "xterm-256color"
sys.path.insert(0, os.environ.get("CE_REPO", "."))
import pyte, bootstrap
class TTY(io.StringIO):
    encoding = "utf-8"
    def isatty(self): return True
s = TTY()
class T:  # no ticker thread: deterministic frames
    ident = None
    def join(self, timeout=None): pass
r = bootstrap.InstallReporter(stream=s, clock=iter(range(0, 10**6, 5)).__next__, environ=os.environ)
r._thread = T()
ALL = ("Resolve source","Download source","Install core","Provision dependencies","Verify installation","Activate clients")
rem = lambda op: ALL[ALL.index(op)+1:]
prompt = "mohab@rog:/media/mohab/Data/chaosengine-harness$ curl -fsSL \"https://raw.githubusercontent.com/ShaftHQ/SHAFT_ENGINE/main/chaos-engine/install.sh\" | bash\r\n"
s.write(prompt)
s.write("ChaosEngine moved to ShaftHQ/chaosengine-harness; forwarding to https://raw.githubusercontent.com/ShaftHQ/chaosengine-harness/main/install.sh\r\n")
proj = "/media/mohab/Data/chaosengine-harness"
r.announce(__import__("pathlib").Path("/tmp"), "ShaftHQ/chaosengine-harness", "main")
r.project_root = proj
sha = "db38269bb8fa9f25c8a1e2b3e3446def6ab2694a"
r.start("Resolve source", remaining=rem("Resolve source")); r.note_commit(sha)
r.complete("Resolve source", remaining=rem("Resolve source"))
r.start("Download source", remaining=rem("Download source"))
r.begin_download(123456, detail="912 source files"); r.downloaded(100000)
url = f"https://github.com/ShaftHQ/chaosengine-harness/tree/{sha}"
r.detail = url
if mode == "real":  # bootstrap.py:5904-5910 prints straight into the live frame
    s.write(f"ShaftHQ/chaosengine-harness {bootstrap.product_version()} {sha} -> {proj}\n")
    s.write(url + "\n")
r.complete("Download source", remaining=rem("Download source"))
r.start("Install core", remaining=rem("Install core")); r.trace("install core")
r.complete("Install core", remaining=rem("Install core"))
r.start("Provision dependencies", remaining=rem("Provision dependencies"), detail="pip: 3 packages")
r.complete("Provision dependencies", remaining=rem("Provision dependencies"))
r.start("Verify installation", remaining=rem("Verify installation"))
raw = s.getvalue()
open(f"./raw-{cols}x{rows}-{mode}.txt","w").write(raw)
scr = pyte.Screen(cols, rows); st = pyte.Stream(scr)
st.feed(raw.replace("\n", "\r\n").replace("\r\r\n", "\r\n"))
out = "\n".join(l.rstrip() for l in scr.display)
open(f"./screen-{cols}x{rows}-{mode}.txt","w").write(out+"\n")
print(f"=== {cols}x{rows} {mode} ==="); print(out)
