#!/usr/bin/env python3
"""Small, dependency-free portfolio CMS. Uses ffmpeg for web image derivatives."""
import base64, hashlib, hmac, json, mimetypes, os, secrets, sqlite3, subprocess, time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parent
DATA = Path(os.environ.get("SILVIA_DATA_DIR", ROOT / "data")); DATA.mkdir(exist_ok=True)
UPLOADS = Path(os.environ.get("SILVIA_UPLOAD_DIR", ROOT / "uploads")); UPLOADS.mkdir(exist_ok=True)
DB = DATA / "portfolio.sqlite3"
PASSWORD = os.environ.get("SILVIA_ADMIN_PASSWORD", "change-me-before-production")
SECRET = os.environ.get("SILVIA_SESSION_SECRET", "local-development-secret")
PREFIX = os.environ.get("SILVIA_PREFIX", "").rstrip("/")

def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

def init():
    c = db()
    c.executescript('''
    create table if not exists projects (id integer primary key, title text not null, slug text unique not null, client text, year text, discipline text, description text, published integer default 0, position integer default 0, created_at integer);
    create table if not exists images (id integer primary key, project_id integer not null, file text not null, alt text, position integer default 0, foreign key(project_id) references projects(id) on delete cascade);
    ''')
    if not c.execute("select count(*) from projects").fetchone()[0]:
        rows = [
          ("Atlantic House", "atlantic-house", "Atlantic House", "2025", "Identity & Editorial", "A visual identity for a coastal retreat where the weather is part of the architecture.", 1, 1),
          ("The Common", "the-common", "The Common Studio", "2024", "Campaign & Digital", "A flexible campaign system built around generous type, lucid information and moments of surprise.", 1, 2),
          ("Field Notes", "field-notes", "Independent", "2024", "Publication", "A quarterly journal about land, place and the value of paying closer attention.", 1, 3),
        ]
        c.executemany("insert into projects (title,slug,client,year,discipline,description,published,position,created_at) values (?,?,?,?,?,?,?,?,?)", [r+(int(time.time()),) for r in rows])
    c.commit(); c.close()

def signed(value): return hmac.new(SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()
def session_valid(headers):
    cookie = SimpleCookie(headers.get("Cookie")); item = cookie.get("silvia_session")
    if not item: return False
    try:
        value, sig = base64.urlsafe_b64decode(item.value.encode()).decode().split(".")
        return hmac.compare_digest(sig, signed(value)) and int(value) > int(time.time())
    except Exception: return False

def public_project(row, c):
    d = dict(row); d["published"] = bool(d["published"])
    d["images"] = [dict(x) for x in c.execute("select * from images where project_id=? order by position,id", (d["id"],))]
    return d

class App(BaseHTTPRequestHandler):
    server_version = "SilviaPing/1.0"
    def log_message(self, fmt, *args): print("[%s] %s" % (self.log_date_time_string(), fmt % args))
    def send_json(self, data, status=200, cookies=None):
        payload=json.dumps(data).encode(); self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(payload))); self.send_header("Cache-Control","no-store")
        for x in cookies or []: self.send_header("Set-Cookie",x)
        self.end_headers(); self.wfile.write(payload)
    def body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length",0))) or b"{}")
    def auth(self):
        if session_valid(self.headers): return True
        self.send_json({"error":"Authentication required"},401); return False
    def do_GET(self):
        path=urlparse(self.path).path
        if PREFIX and path.startswith(PREFIX): path=path[len(PREFIX):] or "/"
        if path=="/api/projects":
            c=db(); rows=c.execute("select * from projects where published=1 order by position,id").fetchall(); out=[public_project(r,c) for r in rows]; c.close(); return self.send_json(out)
        if path.startswith("/api/projects/"):
            slug=path.rsplit('/',1)[-1]; c=db(); r=c.execute("select * from projects where slug=? and published=1",(slug,)).fetchone(); out=public_project(r,c) if r else None; c.close(); return self.send_json(out or {"error":"Not found"}, 200 if out else 404)
        if path=="/api/admin/projects":
            if not self.auth(): return
            c=db(); out=[public_project(r,c) for r in c.execute("select * from projects order by position,id")]; c.close(); return self.send_json(out)
        if path=="/api/session": return self.send_json({"authenticated":session_valid(self.headers)})
        if path.startswith("/uploads/"):
            return self.file(UPLOADS / path.removeprefix("/uploads/"), cache=True)
        if path.startswith("/api/"): return self.send_json({"error":"Not found"},404)
        if path in ("/style.css", "/app.js"):
            return self.file(ROOT / "public" / path.lstrip("/"))
        return self.file(ROOT / "public" / "index.html")
    def do_HEAD(self):
        # Health checks use HEAD; public routes are all served by the same app.
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()
    def file(self, p, cache=False):
        try:
            p=p.resolve(); allowed=(ROOT/"public").resolve() if "public" in p.parts else UPLOADS.resolve()
            if not str(p).startswith(str(allowed)) or not p.is_file(): raise FileNotFoundError
            data=p.read_bytes(); self.send_response(200); self.send_header("Content-Type",mimetypes.guess_type(p)[0] or "application/octet-stream"); self.send_header("Content-Length",str(len(data))); self.send_header("Cache-Control", "public, max-age=31536000, immutable" if cache else "no-cache"); self.end_headers(); self.wfile.write(data)
        except FileNotFoundError: self.send_error(404)
    def do_POST(self):
        path=urlparse(self.path).path
        if PREFIX and path.startswith(PREFIX): path=path[len(PREFIX):]
        if path=="/api/login":
            b=self.body(); ok=hmac.compare_digest(str(b.get("password","")),PASSWORD)
            if not ok: return self.send_json({"error":"That password isn’t recognised."},401)
            token=str(int(time.time())+60*60*12); cookie=f"silvia_session={base64.urlsafe_b64encode((token+'.'+signed(token)).encode()).decode()}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200"
            return self.send_json({"ok":True},cookies=[cookie])
        if path=="/api/logout": return self.send_json({"ok":True},cookies=["silvia_session=; HttpOnly; Path=/; Max-Age=0"])
        if not self.auth(): return
        if path=="/api/admin/projects":
            b=self.body(); c=db(); pos=c.execute("select coalesce(max(position),0)+1 from projects").fetchone()[0]; slug=self.slug(b.get("title","Untitled"),c)
            c.execute("insert into projects(title,slug,client,year,discipline,description,published,position,created_at) values (?,?,?,?,?,?,?,?,?)",(b.get("title","Untitled"),slug,b.get("client",""),b.get("year",""),b.get("discipline",""),b.get("description",""),0,pos,int(time.time()))); c.commit(); r=c.execute("select * from projects where id=last_insert_rowid()").fetchone(); out=public_project(r,c); c.close(); return self.send_json(out,201)
        if path.endswith("/upload"):
            return self.upload(int(path.split('/')[-2]))
        if path.endswith("/reorder-images"):
            pid=int(path.split('/')[-2]); b=self.body(); c=db(); [c.execute("update images set position=? where id=? and project_id=?",(i,x,pid)) for i,x in enumerate(b.get("ids",[]),1)]; c.commit(); c.close(); return self.send_json({"ok":True})
        if path.endswith("/publish"):
            pid=int(path.split('/')[-2]); c=db(); c.execute("update projects set published=1-published where id=?",(pid,)); c.commit(); c.close(); return self.send_json({"ok":True})
        return self.send_json({"error":"Not found"},404)
    def do_PUT(self):
        if not self.auth(): return
        path=urlparse(self.path).path
        if PREFIX and path.startswith(PREFIX): path=path[len(PREFIX):]
        if path.startswith("/api/admin/projects/"):
            pid=int(path.rsplit('/',1)[-1]); b=self.body(); c=db(); slug=self.slug(b.get("title","Untitled"),c,pid); c.execute("update projects set title=?,slug=?,client=?,year=?,discipline=?,description=? where id=?",(b.get("title","Untitled"),slug,b.get("client",""),b.get("year",""),b.get("discipline",""),b.get("description",""),pid)); c.commit(); r=c.execute("select * from projects where id=?",(pid,)).fetchone(); out=public_project(r,c); c.close(); return self.send_json(out)
        return self.send_json({"error":"Not found"},404)
    def do_DELETE(self):
        if not self.auth(): return
        path=urlparse(self.path).path
        if PREFIX and path.startswith(PREFIX): path=path[len(PREFIX):]
        if "/images/" in path:
            iid=int(path.rsplit('/',1)[-1]); c=db(); r=c.execute("select file from images where id=?",(iid,)).fetchone(); c.execute("delete from images where id=?",(iid,)); c.commit(); c.close();
            if r: (UPLOADS/r["file"]).unlink(missing_ok=True)
            return self.send_json({"ok":True})
        return self.send_json({"error":"Not found"},404)
    def slug(self,title,c,exclude=None):
        import re
        base=re.sub(r"[^a-z0-9]+","-",title.lower()).strip("-") or "project"; out=base; n=2
        while c.execute("select 1 from projects where slug=? and id != coalesce(?, -1)",(out,exclude)).fetchone(): out=f"{base}-{n}"; n+=1
        return out
    def upload(self,pid):
        try:
            b=self.body(); raw=base64.b64decode(b.get("data","")); ext=Path(b.get("name","image")).suffix.lower();
            if len(raw)>35*1024*1024 or ext not in (".jpg",".jpeg",".png",".webp"): raise ValueError("Please upload a JPG, PNG or WebP under 35 MB.")
            source=UPLOADS/(secrets.token_hex(12)+ext); source.write_bytes(raw); target=source.with_suffix(".webp")
            subprocess.run(["ffmpeg","-y","-i",str(source),"-vf","scale='min(2400,iw)':-2:force_original_aspect_ratio=decrease", "-q:v","75",str(target)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); source.unlink(missing_ok=True)
            c=db(); pos=c.execute("select coalesce(max(position),0)+1 from images where project_id=?",(pid,)).fetchone()[0]; c.execute("insert into images(project_id,file,alt,position) values(?,?,?,?)",(pid,target.name,b.get("alt","") ,pos)); c.commit(); r=c.execute("select * from images where id=last_insert_rowid()").fetchone(); c.close(); return self.send_json(dict(r),201)
        except Exception as e: return self.send_json({"error":str(e)},400)

if __name__ == "__main__":
    init(); print(f"Silvia Ping portfolio on http://127.0.0.1:{os.environ.get('PORT','5188')}{PREFIX}/"); ThreadingHTTPServer(("127.0.0.1",int(os.environ.get("PORT","5188"))),App).serve_forever()
