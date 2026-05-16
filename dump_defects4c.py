# save as ~/dump_defects4c.py
import requests, json, os, time

BASE = "http://146.190.90.3:9651"
OUT  = "/cs/student/project_msc/2025/dsml/nmxian/defects4c_corpus"
os.makedirs(OUT, exist_ok=True)

ids = requests.get(f"{BASE}/list_defects_bugid").json()["defects"]
ids = [d for d in ids if "llvm___llvm" not in d]
print(f"Fetching {len(ids)} bugs...")

for i, bug_id in enumerate(ids):
    safe = bug_id.replace("/", "_").replace("@", "__")
    out_path = f"{OUT}/{safe}.json"
    if os.path.exists(out_path):
        print(f"[{i+1}/{len(ids)}] skip {bug_id}")
        continue
    try:
        r = requests.get(f"{BASE}/get_defect/{bug_id}", timeout=30)
        data = r.json()
        if data.get("status") == "success":
            with open(out_path, "w") as f:
                json.dump(data, f, indent=2)
            print(f"[{i+1}/{len(ids)}] ✅ {bug_id}")
        else:
            print(f"[{i+1}/{len(ids)}] ❌ {bug_id}: bad status")
        time.sleep(0.4)
    except Exception as e:
        print(f"[{i+1}/{len(ids)}] ❌ {bug_id}: {e}")

print(f"\nDone. Files saved to {OUT}")