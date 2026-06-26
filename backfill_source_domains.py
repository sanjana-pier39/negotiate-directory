#!/usr/bin/env python3
"""
backfill_source_domains.py — populate `source_domain` for every multi-tenant
registry entry by probing candidate Shopify hostnames.

Why: the bulk-add script that originally populated the registry only set
`domain: pier39.fly.dev/<slug>` without ever filling in `source_domain`.
Without it, the MCP's list_products can't fetch real /products.json data.

This script tries <slug>.com, www.<slug>.com, <slug>.co, shop.<slug>.com,
and <slug>.myshopify.com for each entry — first one that returns a valid
Shopify /products.json response wins. Results written incrementally to a
checkpoint file so Ctrl-C is safe and resumable.

Usage:
    cd negotiate-directory/
    python3 backfill_source_domains.py
    # Then once it finishes:
    git add registry.json
    git commit -m "Backfill source_domain for X stores"
    git push

Tunables: CONCURRENCY (default 20), TIMEOUT_S (default 6).
"""
from __future__ import annotations

import concurrent.futures
import json
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REGISTRY_PATH = Path(__file__).parent / "registry.json"
CHECKPOINT_PATH = Path(__file__).parent / ".backfill_checkpoint.json"

# Candidate hostnames to try, in order. First Shopify-shape match wins.
CANDIDATE_PATTERNS = (
    "{slug}.com",
    "www.{slug}.com",
    "{slug}.co",
    "shop.{slug}.com",
    "{slug}.myshopify.com",
)

# Concurrency + timeout. Bumping these makes it faster but ruder to merchants.
CONCURRENCY = 20
TIMEOUT_S = 6
PROGRESS_EVERY = 100  # save checkpoint + print every N entries

USER_AGENT = (
    "pier39-backfill/1.0 (sanjana@pier39.ai) — "
    "one-time registry source_domain discovery; will not repeat"
)


def probe_one(slug: str) -> str | None:
    """Try the candidate hostnames; return the first one that responds with
    a valid Shopify /products.json (HTTP 200 + JSON content-type), or None."""
    safe_slug = "".join(c for c in slug.lower() if c.isalnum() or c == "-").strip("-")
    if not safe_slug or len(safe_slug) < 2:
        return None
    for pattern in CANDIDATE_PATTERNS:
        host = pattern.format(slug=safe_slug)
        url = f"https://{host}/products.json?limit=1"
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                if resp.status != 200:
                    continue
                ct = resp.headers.get("Content-Type", "").lower()
                if "json" not in ct:
                    continue
                # Sanity: must have a "products" key (Shopify response shape)
                body = resp.read(8192)  # only need a tiny prefix
                try:
                    parsed = json.loads(body.decode("utf-8", errors="replace"))
                except Exception:
                    continue
                if isinstance(parsed, dict) and "products" in parsed:
                    return host
        except Exception:
            continue
    return None


def slug_from_entry(entry: dict) -> str | None:
    domain = (entry.get("domain") or "").lower()
    if domain.startswith("pier39.fly.dev/"):
        return domain[len("pier39.fly.dev/"):].split("/", 1)[0]
    if domain.startswith("www.pier39.fly.dev/"):
        return domain[len("www.pier39.fly.dev/"):].split("/", 1)[0]
    return None


def load_checkpoint() -> dict[str, str | None]:
    """slug -> resolved hostname (or None for confirmed-not-Shopify)."""
    if CHECKPOINT_PATH.exists():
        try:
            return json.loads(CHECKPOINT_PATH.read_text())
        except Exception:
            pass
    return {}


def save_checkpoint(resolved: dict[str, str | None]) -> None:
    CHECKPOINT_PATH.write_text(json.dumps(resolved, indent=0))


def main() -> int:
    if not REGISTRY_PATH.exists():
        print(f"ERROR: {REGISTRY_PATH} not found. Run this from the repo root.")
        return 1

    print(f"Loading {REGISTRY_PATH} …")
    data = json.loads(REGISTRY_PATH.read_text())
    stores = data.get("stores", [])
    print(f"  {len(stores):,} stores total\n")

    resolved = load_checkpoint()
    print(f"Resuming from checkpoint: {len(resolved):,} slugs already probed\n")

    # Build the work queue — slugs we haven't probed yet AND that need backfilling
    work: list[tuple[int, str]] = []  # (index, slug)
    for i, entry in enumerate(stores):
        if entry.get("source_domain"):
            continue  # already has source_domain
        slug = slug_from_entry(entry)
        if not slug:
            continue
        if slug in resolved:
            continue
        work.append((i, slug))

    if not work:
        print("Nothing to probe — all entries already resolved.")
    else:
        print(f"Probing {len(work):,} slugs with concurrency={CONCURRENCY}, timeout={TIMEOUT_S}s")
        print(f"Estimated wall time: ~{len(work) * TIMEOUT_S // CONCURRENCY // 60} minutes (worst case)\n")

    # Graceful Ctrl-C: save what we have and exit
    interrupted = {"flag": False}
    def _on_sigint(signum, frame):
        if interrupted["flag"]:
            print("\nForced exit.")
            sys.exit(130)
        interrupted["flag"] = True
        print("\n[interrupted] saving checkpoint, will exit after current batch...")
    signal.signal(signal.SIGINT, _on_sigint)

    start = time.time()
    done = 0
    hits = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        future_to_slug = {ex.submit(probe_one, slug): (i, slug) for i, slug in work}
        for fut in concurrent.futures.as_completed(future_to_slug):
            i, slug = future_to_slug[fut]
            try:
                host = fut.result()
            except Exception:
                host = None
            resolved[slug] = host
            if host:
                hits += 1
            done += 1
            if done % PROGRESS_EVERY == 0 or done == len(work):
                elapsed = time.time() - start
                rate = done / elapsed if elapsed > 0 else 0
                eta = (len(work) - done) / rate if rate > 0 else 0
                print(f"  [{done:,}/{len(work):,}] {hits:,} hits ({hits/done*100:.1f}%) — "
                      f"{rate:.1f}/s, ETA {eta/60:.1f} min")
                save_checkpoint(resolved)
            if interrupted["flag"]:
                # Cancel pending work
                for f in future_to_slug:
                    f.cancel()
                break

    save_checkpoint(resolved)
    print(f"\nProbe complete: {len(resolved):,} entries cached, {sum(1 for v in resolved.values() if v):,} hits\n")

    # Write resolutions back into the registry
    print("Updating registry.json with source_domain fields …")
    updated = 0
    for entry in stores:
        if entry.get("source_domain"):
            continue
        slug = slug_from_entry(entry)
        if not slug:
            continue
        host = resolved.get(slug)
        if host:
            entry["source_domain"] = host
            updated += 1
        # We deliberately do NOT write None back — leaving the field absent
        # lets the runtime heuristic in _resolve_shopify_domain still try
        # in case the merchant fixes their setup later.

    REGISTRY_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"  {updated:,} entries updated with source_domain\n")

    print("Done. Next steps:")
    print(f"  git add {REGISTRY_PATH.name}")
    print(f"  git commit -m 'Backfill source_domain for {updated:,} stores'")
    print(f"  git push")
    print()
    print(f"Checkpoint preserved at {CHECKPOINT_PATH.name} — safe to delete after push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
