#!/usr/bin/env python3
"""Replicate deployments from one platform to another, content-addressed.

For each named deployment: take the SOURCE's current published version, ensure
every firmware asset (by sha256) and file set (by fingerprint) exists on
the TARGET, compose, publish, and mirror the
channels. Ids never travel — only content and names — so the two stacks can
have entirely different row ids.

Usage: replicate_deployments.py <source_api> <target_api> "Name A" "Name B" …
"""
import sys

import requests

SRC, DST = sys.argv[1].rstrip("/"), sys.argv[2].rstrip("/")
NAMES = sys.argv[3:]


def get(api, path):
    r = requests.get(f"{api}{path}")
    r.raise_for_status()
    return r.json()


def post(api, path, **kw):
    r = requests.post(f"{api}{path}", **kw)
    if not r.ok:
        raise SystemExit(f"POST {api}{path} -> {r.status_code}: {r.text[:300]}")
    return r.json()


def project_map():
    src_p = {p["name"]: p["id"] for p in get(SRC, "/api/projects")}
    dst_p = {p["name"]: p["id"] for p in get(DST, "/api/projects")}
    return src_p, dst_p


def ensure_asset(dst_pid, img):
    for a in get(DST, f"/api/flasher/projects/{dst_pid}/firmware"):
        if a["sha256"] == img["sha256"]:
            return a["id"]
    src_meta = next(a for a in get(SRC, f"/api/flasher/projects/{img['src_pid']}/firmware")
                    if a["id"] == img["firmware_asset_id"])
    data = requests.get(f"{SRC}/api/flasher/firmware/{img['firmware_asset_id']}/bin").content
    r = requests.post(
        f"{DST}/api/flasher/projects/{dst_pid}/firmware",
        files={"file": (img["filename"], data)},
        data={"kind": img["kind"], "chip": img["chip"],
              "build_label": img["build_label"],
              "notes": src_meta.get("notes", ""), "uploaded_by": "replicate"},
    )
    r.raise_for_status()
    return r.json()["id"]


def ensure_set(ref):
    """The same file set on the target, by fingerprint; content from the
    source. Sets are platform wide (decision 0029), so there is no project
    in the path — only the manifest matters."""
    if not ref:
        return None
    for s in get(DST, "/api/flasher/file-sets"):
        if s["fingerprint"] == ref["fingerprint"]:
            return s["id"]
    src = get(SRC, f"/api/flasher/file-sets/{ref['id']}")
    files = []
    for f in src["files"]:
        data = requests.get(f"{SRC}/api/flasher/files/{src['id']}/{f['filename']}").content
        files.append(("files", (f["filename"], data)))
    made = post(DST, "/api/flasher/file-sets/import", files=files,
                data={"label": src["label"], "comment": f"replicated: {src['comment']}"[:290],
                      "created_by": "replicate", "kind": src["kind"]})
    return made["set"]["id"]


def main():
    src_projects, dst_projects = project_map()
    src_param_sets = {}
    for name in NAMES:
        found = None
        for pname, pid in src_projects.items():
            for d in get(SRC, f"/api/flasher/projects/{pid}/deployments"):
                if d["name"] == name:
                    found = (pname, pid, d)
        if not found:
            print(f"!! {name}: not found on the source")
            continue
        pname, src_pid, dep = found
        dst_pid = dst_projects[pname]
        cur_id = dep["current_version_id"]
        if not cur_id:
            print(f"!! {name}: no current version")
            continue
        v = get(SRC, f"/api/flasher/deployment-versions/{cur_id}")

        # Skip when the target's current version already matches by content.
        dst_deps = {d["name"]: d for d in get(DST, f"/api/flasher/projects/{dst_pid}/deployments")}
        tgt = dst_deps.get(name)
        if tgt and tgt.get("current_version_id"):
            t = get(DST, f"/api/flasher/deployment-versions/{tgt['current_version_id']}")
            def fp(x):
                return ((x.get("file_set") or {}).get("fingerprint"),
                        (x.get("artwork_set") or {}).get("fingerprint"))
            if (t["firmware_fingerprint"], fp(t), t["steps"]) == \
               (v["firmware_fingerprint"], fp(v), v["steps"]):
                print(f"== {name}: target already current")
                continue

        if tgt is None:
            tgt_id = post(DST, f"/api/flasher/projects/{dst_pid}/deployments", json={
                "name": name, "chip": v["deployment"]["chip"],
                "description": f"replicated from {SRC}"})["id"]
        else:
            tgt_id = tgt["id"]

        images = [{"firmware_asset_id": ensure_asset(
                       dst_pid, {**img, "src_pid": src_pid}),
                   "address": img["address"]} for img in v["images"]]
        set_id = ensure_set(v.get("file_set"))
        art_id = ensure_set(v.get("artwork_set"))
        ps_id = None
        if v.get("param_set_name"):
            for ps in get(DST, f"/api/flasher/projects/{dst_pid}/param-sets"):
                if ps["name"] == v["param_set_name"]:
                    ps_id = ps["id"]
        new = post(DST, f"/api/flasher/deployments/{tgt_id}/versions", json={
            "comment": f"replicated: {v['comment']}"[:490],
            "created_by": "replicate",
            "images": images, "file_set_id": set_id, "artwork_set_id": art_id,
            "steps": v["steps"], "param_set_id": ps_id,
            "param_defaults": v["param_defaults"],
            "transport_profile": v["transport_profile"],
            "monitor_baud": v["monitor_baud"], "flash_config": v["flash_config"]})
        if not new["validation"]["ok"]:
            print(f"!! {name}: target draft does not validate: {new['validation']['errors'][:2]}")
            continue
        post(DST, f"/api/flasher/deployment-versions/{new['id']}/publish",
             json={"approved_by": "replicate"})
        # Mirror the source channels that point at THIS version.
        for ch in dep["channels"]:
            if ch["deployment_version_id"] == cur_id:
                requests.put(f"{DST}/api/flasher/deployments/{tgt_id}/channels/{ch['name']}",
                             json={"deployment_version_id": new["id"],
                                   "updated_by": "replicate"}).raise_for_status()
        print(f"== {name}: replicated as v{new['version_no']} "
              f"(fw {new['firmware_fingerprint'][:8]}, files {new['files_fingerprint'][:8]}) "
              f"channels={[c['name'] for c in dep['channels'] if c['deployment_version_id'] == cur_id]}")


if __name__ == "__main__":
    main()
