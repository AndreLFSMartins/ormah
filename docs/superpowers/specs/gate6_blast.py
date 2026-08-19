"""Read-only blast-radius measurement for forgetting gate #6 with the planned filter.

Gate #6 (src/ormah/background/forgetting_manager.py:_evaluate_protection):
    protected if degree > deletion_max_degree (2)
                 or max_weight >= deletion_strong_edge_weight
    STRONG below is 0.61 (this deployment's ORMAH_DELETION_STRONG_EDGE_WEIGHT); the code
    default is 0.7 and gives different counts. Check ~/.config/ormah/.env before trusting.
Reached only when: tier='archival', archived_at NOT NULL, importance < 0.5, no positive affinity.
"""

import sqlite3
import sys

MAX_DEGREE = 2
STRONG = 0.61
IMPORTANCE_THRESHOLD = 0.5

SQL = """
WITH cand AS (
  SELECT n.id
  FROM nodes n
  WHERE n.tier = 'archival'
    AND COALESCE(n.importance, 0.5) < :imp
    AND NOT EXISTS (SELECT 1 FROM affinity a WHERE a.node_id = n.id AND a.signal > 0)
),
old AS (
  SELECT c.id,
         COUNT(e.rowid) AS deg,
         COALESCE(MAX(e.weight), 0) AS mw
  FROM cand c LEFT JOIN edges e ON (e.source_id = c.id OR e.target_id = c.id)
  GROUP BY c.id
),
new AS (
  SELECT c.id,
         COUNT(e.rowid) AS deg,
         COALESCE(MAX(e.weight), 0) AS mw
  FROM cand c LEFT JOIN edges e
    ON (e.source_id = c.id OR e.target_id = c.id) AND e.edge_type NOT IN ('contradicts')
  GROUP BY c.id
)
SELECT
  COUNT(*) AS candidates,
  SUM(CASE WHEN (old.deg > :d OR old.mw >= :w) THEN 1 ELSE 0 END) AS protected_before,
  SUM(CASE WHEN (new.deg > :d OR new.mw >= :w) THEN 1 ELSE 0 END) AS protected_after,
  SUM(CASE WHEN (old.deg > :d OR old.mw >= :w)
            AND NOT (new.deg > :d OR new.mw >= :w) THEN 1 ELSE 0 END) AS lost_protection,
  SUM(CASE WHEN (old.deg > :d OR old.mw >= :w)
            AND NOT (new.deg > :d OR new.mw >= :w)
            AND old.mw >= :w THEN 1 ELSE 0 END) AS lost_with_strong_contradicts,
  SUM(CASE WHEN (old.deg > :d OR old.mw >= :w)
            AND NOT (new.deg > :d OR new.mw >= :w)
            AND old.mw < :w THEN 1 ELSE 0 END) AS lost_degree_arm_only
FROM old JOIN new USING (id)
"""

# How many of the lost ones would also pass the *staleness* gates is a separate question;
# gate #6 protection loss is what the plan's claim is about.
MIX = """
WITH cand AS (
  SELECT n.id FROM nodes n
  WHERE n.tier = 'archival' AND COALESCE(n.importance, 0.5) < 0.5
    AND NOT EXISTS (SELECT 1 FROM affinity a WHERE a.node_id = n.id AND a.signal > 0)
)
SELECT COUNT(DISTINCT c.id) FROM cand c JOIN edges e
  ON (e.source_id = c.id OR e.target_id = c.id) WHERE e.edge_type = 'contradicts'
"""

for db in sys.argv[1:]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    r = conn.execute(SQL, {"d": MAX_DEGREE, "w": STRONG, "imp": IMPORTANCE_THRESHOLD}).fetchone()
    touching = conn.execute(MIX).fetchone()[0]
    print(f"\n=== {db}")
    print(f"  gate#6 candidates (archival, imp<0.5, no +feedback): {r['candidates']}")
    print(f"  of those, touching >=1 contradicts edge:             {touching}")
    print(f"  protected by gate#6 BEFORE filter:                   {r['protected_before']}")
    print(f"  protected by gate#6 AFTER  filter:                   {r['protected_after']}")
    print(f"  >> LOSE gate#6 protection (verdict change):          {r['lost_protection']}")
    print(f"       ...of which had a strong (>=0.7) contradicts:   {r['lost_with_strong_contradicts']}")
    print(f"       ...of which lost via the DEGREE arm only:       {r['lost_degree_arm_only']}")
    conn.close()
