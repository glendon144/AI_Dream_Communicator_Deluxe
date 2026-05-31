# Upgrade Guide — FunKit 1.20

1) **Install Flask** (if not already):
```bash
pip install flask
```

2) **Update server + exporter**
- Use the new `modules/flask_server.py` (reads `PORT`, has view modes, share links).
- Keep the patched `modules/exporter.py` that Base64-encodes `bytes` and lifts image hints.

3) **Restart**
- Kill any old Flask on 5050 (`lsof -i :5050` → `kill <PID>`).
- Launch from GUI (recommended) — it picks a free port — or run `python3 main.py`.

4) **Sanity checks**
- Open `/health` → expect `{ "status": "ok", "doc_count": N, ... }`.
- Load `/` and `/doc/<id>`; try `?mode=reader` and `?mode=code`.

5) **Sharing**
- Use the **Copy link** button on a doc page. Anyone on the network can view it while the server runs.
