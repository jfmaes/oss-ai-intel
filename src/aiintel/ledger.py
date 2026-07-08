from __future__ import annotations
import json, sqlite3, sys, time
from pathlib import Path
from rapidfuzz import fuzz
from aiintel.models import Item

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items(
  id INTEGER PRIMARY KEY,
  url_canon TEXT NOT NULL,
  title TEXT NOT NULL,
  title_norm TEXT NOT NULL,
  source TEXT NOT NULL,
  trust TEXT NOT NULL,
  natural_key TEXT,
  published REAL,
  first_seen REAL NOT NULL,
  run_date TEXT NOT NULL,
  metrics TEXT,
  story_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_items_url ON items(url_canon);
CREATE INDEX IF NOT EXISTS idx_items_seen ON items(first_seen);
CREATE TABLE IF NOT EXISTS brief_log(
  id INTEGER PRIMARY KEY,
  ts REAL NOT NULL,
  run_date TEXT NOT NULL,
  kind TEXT NOT NULL,
  subject TEXT,
  cost_usd REAL,
  stats TEXT
);
CREATE TABLE IF NOT EXISTS stories(
  id INTEGER PRIMARY KEY,
  natural_key TEXT UNIQUE,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new',
  first_seen REAL NOT NULL,
  last_seen REAL NOT NULL,
  cum_score REAL DEFAULT 0,
  last_briefed TEXT,
  brief_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS story_briefings(
  id INTEGER PRIMARY KEY,
  story_id INTEGER NOT NULL,
  run_date TEXT NOT NULL,
  section TEXT NOT NULL,
  line TEXT,
  note TEXT
);
"""

class Ledger:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(_SCHEMA)
        # In-place upgrade for dev DBs created before story_briefings.note existed;
        # a no-op (duplicate-column OperationalError) on fresh or already-upgraded DBs.
        try:
            self.conn.execute("ALTER TABLE story_briefings ADD COLUMN note TEXT")
        except sqlite3.OperationalError:
            pass
        self.conn.commit()

    def filter_new(self, items: list[Item], window_days: int, fuzzy_threshold: int) -> tuple[list[Item], int]:
        cutoff = time.time() - window_days * 86400
        recent_titles = [r[0] for r in self.conn.execute(
            "SELECT title_norm FROM items WHERE first_seen >= ?", (cutoff,))]
        new, dupes = [], 0
        seen_urls: set[str] = set()
        for it in items:
            seen = self.conn.execute(
                "SELECT 1 FROM items WHERE url_canon = ? LIMIT 1", (it.url_canon,)).fetchone()
            if seen or it.url_canon in seen_urls or any(
                    fuzz.token_set_ratio(it.title_norm, t) >= fuzzy_threshold for t in recent_titles):
                dupes += 1
                continue
            new.append(it)
            seen_urls.add(it.url_canon)
            recent_titles.append(it.title_norm)
        return new, dupes

    def attach_stories(self, items: list[Item]) -> tuple[dict[int, list[Item]], set[int]]:
        from rapidfuzz import fuzz
        now = time.time()
        cutoff = now - 14 * 86400
        grouped: dict[int, list[Item]] = {}
        created: set[int] = set()
        for it in items:
            sid = None
            if it.natural_key:
                row = self.conn.execute("SELECT id FROM stories WHERE natural_key=?",
                                        (it.natural_key,)).fetchone()
                if row:
                    sid = row[0]
            if sid is None:
                for rid, title in self.conn.execute(
                        "SELECT id, title FROM stories WHERE last_seen >= ?", (cutoff,)):
                    if fuzz.token_set_ratio(it.title_norm, title.lower()) >= 90:
                        sid = rid
                        break
            if sid is None:
                cur = self.conn.execute(
                    "INSERT INTO stories(natural_key,title,first_seen,last_seen,cum_score)"
                    " VALUES(?,?,?,?,?)",
                    (it.natural_key or None, it.title, now, now, it.score))
                sid = cur.lastrowid
                created.add(sid)
            else:
                self.conn.execute(
                    "UPDATE stories SET last_seen=?, cum_score=cum_score+?, status='developing'"
                    " WHERE id=?", (now, it.score, sid))
            grouped.setdefault(sid, []).append(it)
        self.conn.commit()
        return grouped, created

    def compensate_run(self, item_ids, score_deltas, created_story_ids):
        if item_ids:
            q = ",".join("?" * len(item_ids))
            self.conn.execute(f"DELETE FROM items WHERE id IN ({q})", item_ids)
        for sid, delta in score_deltas.items():
            self.conn.execute("UPDATE stories SET cum_score = MAX(0, cum_score - ?) WHERE id=?", (delta, sid))
        for sid in created_story_ids:
            row = self.conn.execute("SELECT COUNT(*) FROM items WHERE story_id=?", (sid,)).fetchone()
            if row[0] == 0:
                self.conn.execute("DELETE FROM story_briefings WHERE story_id=?", (sid,))
                self.conn.execute("DELETE FROM stories WHERE id=?", (sid,))
        self.conn.commit()

    def story_prior_briefings(self, story_id: int) -> list[dict]:
        return [{"date": d, "section": s, "line": l} for d, s, l in self.conn.execute(
            "SELECT run_date, section, line FROM story_briefings WHERE story_id=? ORDER BY id",
            (story_id,))]

    def mark_briefed(self, entries, run_date: str) -> None:
        for entry in entries:
            sid, section, line = entry[0], entry[1], entry[2]
            note = entry[3] if len(entry) > 3 else ""
            self.conn.execute(
                "INSERT INTO story_briefings(story_id,run_date,section,line,note) VALUES(?,?,?,?,?)",
                (sid, run_date, section, line, note))
            self.conn.execute(
                "UPDATE stories SET last_briefed=?, brief_count=brief_count+1 WHERE id=?",
                (run_date, sid))
        self.conn.commit()

    def apply_merges(self, pairs: list[list[int]]) -> None:
        # Resolve merge chains internally (defence; run.py resolves first): a local
        # remap folds [[a,b],[b,c]] onto a even though b is gone by the second pair.
        remap: dict[int, int] = {}
        for keep, dupe in pairs:
            keep = remap.get(keep, keep)
            dupe = remap.get(dupe, dupe)
            if keep == dupe:
                continue
            if not self.conn.execute("SELECT 1 FROM stories WHERE id=?", (keep,)).fetchone():
                print(f"[merge] keep story {keep} missing — skipping [{keep},{dupe}]", file=sys.stderr)
                continue
            self.conn.execute("UPDATE items SET story_id=? WHERE story_id=?", (keep, dupe))
            self.conn.execute("UPDATE story_briefings SET story_id=? WHERE story_id=?", (keep, dupe))
            row = self.conn.execute("SELECT cum_score FROM stories WHERE id=?", (dupe,)).fetchone()
            if row:
                self.conn.execute("UPDATE stories SET cum_score=cum_score+? WHERE id=?", (row[0], keep))
            self.conn.execute("DELETE FROM stories WHERE id=?", (dupe,))
            remap[dupe] = keep
            for d, k in list(remap.items()):
                if k == dupe:
                    remap[d] = keep
        self.conn.commit()

    def story_corroboration(self, story_id: int) -> int:
        # sources of items attached this run are not yet inserted; corroboration is
        # computed from stored items plus the caller's grouped view — here: stored items
        row = self.conn.execute(
            "SELECT COUNT(DISTINCT source) FROM items WHERE story_id=?", (story_id,)).fetchone()
        return row[0]

    def insert_items(self, items: list[Item], run_date: str,
                     story_of: dict[int, int] | None = None) -> list[int]:
        now, ids = time.time(), []
        for it in items:
            cur = self.conn.execute(
                "INSERT INTO items(url_canon,title,title_norm,source,trust,natural_key,published,first_seen,run_date,metrics,story_id)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (it.url_canon, it.title, it.title_norm, it.source, it.trust,
                 it.natural_key or None, it.published, now, run_date, json.dumps(it.metrics),
                 (story_of or {}).get(id(it))))
            ids.append(cur.lastrowid)
        self.conn.commit()
        return ids

    def record_brief(self, run_date: str, kind: str, subject: str, cost_usd: float, stats: dict) -> None:
        self.conn.execute(
            "INSERT INTO brief_log(ts,run_date,kind,subject,cost_usd,stats) VALUES(?,?,?,?,?,?)",
            (time.time(), run_date, kind, subject, cost_usd, json.dumps(stats)))
        self.conn.commit()

    def last_success(self) -> float | None:
        row = self.conn.execute("SELECT MAX(ts) FROM brief_log WHERE kind != 'failed'").fetchone()
        return row[0]

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
