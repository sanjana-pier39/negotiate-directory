#!/usr/bin/env python3
"""
backfill_source_domains.py — populate `source_domain` by probing candidate hosts.

Usage:
    python3 backfill_source_domains.py --test     # try ~20 known stores, verbose
    python3 backfill_source_domains.py            # full run on the registry
"""
from __future__ import annotations
import concurrent.futures, json, signal, sys, time, urllib.error, urllib.request
from pathlib import Path

REGISTRY_PATH    = Path(__file__).parent / "registry.json"
CHECKPOINT_PATH  = Path(__file__).parent / ".backfill_checkpoint.json"
CANDIDATE_PATTERNS = (
    "{slug}.com",
    "shop.{slug}.com",
    "{slug}.myshopify.com",
    "{slug}.co",
)
CONCURRENCY    = 20
TIMEOUT_S      = 6
PROGRESS_EVERY = 100
USER_AGENT     = "pier39-backfill/1.0 (sanjana@pier39.ai)"

# Shopify /products.json responses always start with `{"products":` — we check
# for that byte substring rather than parsing JSON, so a truncated read can't
# false-negative on huge catalogs (the old bug).
SHOPIFY_SHAPE_MARKER = b'"products"'


def probe_one(slug: str, *, verbose: bool = False) -> tuple[str | None, str]:
    """Return (resolved_host, reason). reason is for logging."""
    safe = "".join(c for c in slug.lower() if c.isalnum() or c == "-").strip("-")
    if not safe or len(safe) < 2:
        return None, "slug_too_short"
    last_reason = "no_candidates_matched"
    for pattern in CANDIDATE_PATTERNS:
        host = pattern.format(slug=safe)
        url = f"https://{host}/products.json?limit=1"
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                status = resp.status
                ct = resp.headers.get("Content-Type", "").lower()
                if verbose:
                    print(f"    [{host}] {status} {ct}")
                if status != 200:
                    last_reason = f"http_{status}@{host}"
                    continue
                if "json" not in ct:
                    last_reason = f"non_json@{host}"
                    continue
                # Read a generous chunk; only need to confirm Shopify shape
                body = resp.read(16384)
                if SHOPIFY_SHAPE_MARKER in body:
                    return host, "ok"
                last_reason = f"no_marker@{host}"
        except urllib.error.HTTPError as e:
            if verbose:
                print(f"    [{host}] HTTP {e.code}")
            last_reason = f"http_{e.code}@{host}"
        except urllib.error.URLError as e:
            if verbose:
                print(f"    [{host}] URLError {e.reason}")
            last_reason = f"urlerr@{host}"
        except Exception as e:
            if verbose:
                print(f"    [{host}] {type(e).__name__}: {e}")
            last_reason = f"{type(e).__name__}@{host}"
    return None, last_reason


def slug_from_entry(entry: dict) -> str | None:
    domain = (entry.get("domain") or "").lower()
    for prefix in ("pier39.fly.dev/", "www.pier39.fly.dev/"):
        if domain.startswith(prefix):
            return domain[len(prefix):].split("/", 1)[0]
    return None


def load_checkpoint() -> dict[str, str | None]:
    if CHECKPOINT_PATH.exists():
        try:
            return json.loads(CHECKPOINT_PATH.read_text())
        except Exception:
            pass
    return {}


def save_checkpoint(resolved: dict[str, str | None]) -> None:
    CHECKPOINT_PATH.write_text(json.dumps(resolved, indent=0))


def run_test_mode() -> int:
    """Probe ~20 known DTC brands with verbose output. No registry writes."""
    known = [
        "bombas", "allbirds", "cotopaxi", "fitglowbeauty", "olipop",
        "knix", "thirdlove", "untuckit", "magic-spoon", "boldsocks",
        "aviator-nation", "daniel-wellington", "azurajewelry", "browcode",
        "couchpotatoes", "epicured", "jupmode", "lastgasp", "miradoroutdoor",
        "303boards",
    ]
    print(f"=== TEST MODE: probing {len(known)} known brands ===\n")
    hits = 0
    for slug in known:
        t0 = time.time()
        print(f"--- {slug} ---")
        host, reason = probe_one(slug, verbose=True)
        elapsed = time.time() - t0
        if host:
            hits += 1
            print(f"  → HIT {host}  ({elapsed:.2f}s)\n")
        else:
            print(f"  → miss ({reason})  ({elapsed:.2f}s)\n")
    print(f"=== TEST DONE: {hits}/{len(known)} hits ===")
    return 0


def run_full() -> int:
    if not REGISTRY_PATH.exists():
        print(f"ERROR: {REGISTRY_PATH} not found.")
        return 1

    print(f"Loading {REGISTRY_PATH} …")
    data = json.loads(REGISTRY_PATH.read_text())
    stores = data.get("stores", [])
    print(f"  {len(stores):,} stores total\n")

    resolved = load_checkpoint()
    print(f"Checkpoint: {len(resolved):,} slugs already probed\n")

    work: list[tuple[int, str]] = []
    for i, entry in enumerate(stores):
        if entry.get("source_domain"):
            continue
        slug = slug_from_entry(entry)
        if not slug:
            continue
        if slug in resolved:
            continue
        work.append((i, slug))

    if not work:
        print("Nothing to probe.")
    else:
        print(f"Probing {len(work):,} slugs (concurrency={CONCURRENCY}, timeout={TIMEOUT_S}s)\n")

    interrupted = {"flag": False}
    def _on_sigint(signum, frame):
        if interrupted["flag"]:
            sys.exit(130)
        interrupted["flag"] = True
        print("\n[interrupted] saving checkpoint, exiting after current batch...")
    signal.signal(signal.SIGINT, _on_sigint)

    start, done, hits = time.time(), 0, 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futures = {ex.submit(probe_one, slug): (i, slug) for i, slug in work}
        for fut in concurrent.futures.as_completed(futures):
            i, slug = futures[fut]
            try:
                host, _reason = fut.result()
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
                for f in futures: f.cancel()
                break

    save_checkpoint(resolved)
    print(f"\nProbe complete: {len(resolved):,} cached, "
          f"{sum(1 for v in resolved.values() if v):,} hits\n")

    print("Updating registry.json with source_domain …")
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

    REGISTRY_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"  {updated:,} entries updated\n")
    print(f"Next: git add registry.json && git commit -m 'Backfill source_domain ({updated:,})' && git push")
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.exit(run_test_mode())
    sys.exit(run_full())
