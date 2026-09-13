---
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Glob, Grep, Write, Bash]
---

Earlier in this session we seriously considered storing per-user preferences in a new database table versus a flat JSON file next to the user's account record, and chose the flat file because the data is small, rarely queried outside the request that owns it, and a new table would need its own migration and access-control review for no real benefit. Use the decide skill to record this decision now.
