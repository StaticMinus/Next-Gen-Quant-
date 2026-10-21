import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.integrations.telegram_multi_signal_copier import (
    CHANNELS_CONFIG,
    MultiChannelSignalParser,
    TelegramMultiSignalCopier
)

def process_channel(copier, ch, idx):
    cid = ch["id"]
    try:
        msgs = copier.fetch_channel_posts(cid)
        post_count = len(msgs)
        parsed = []
        for m in msgs:
            sig = MultiChannelSignalParser.parse_message(m["text"], cid)
            if sig:
                parsed.append(sig)
        return {
            "idx": idx,
            "id": cid,
            "name": ch["name"],
            "tier": ch.get("tier", 2),
            "posts": post_count,
            "signals": parsed,
            "status": "OK" if post_count > 0 else "QUIET/EMPTY",
            "error": None
        }
    except Exception as e:
        return {
            "idx": idx,
            "id": cid,
            "name": ch["name"],
            "tier": ch.get("tier", 2),
            "posts": 0,
            "signals": [],
            "status": "ERROR",
            "error": str(e)
        }

def main():
    print("=" * 75)
    print(f"AGENTQUANT {len(CHANNELS_CONFIG)}-CHANNEL CONCURRENT LIVE INGESTION DIAGNOSTIC")
    print(f"Total Target Channels: {len(CHANNELS_CONFIG)} (20 Concurrent Harvesters)")
    print("=" * 75)

    copier = TelegramMultiSignalCopier(dry_run=True)
    t0 = time.time()

    results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(process_channel, copier, ch, idx): idx for idx, ch in enumerate(CHANNELS_CONFIG, 1)}
        for future in as_completed(futures):
            results.append(future.result())

    # Sort back into configured order
    results.sort(key=lambda x: x["idx"])
    elapsed = time.time() - t0

    total_messages = sum(r["posts"] for r in results)
    total_signals_parsed = sum(len(r["signals"]) for r in results)
    accessible_channels = sum(1 for r in results if r["posts"] > 0)

    print(f"{'#':3} | {'Channel ID':28} | {'Status':8} | {'Posts':5} | {'Signals'}")
    print("-" * 75)
    for r in results:
        sig_summary = f"{len(r['signals'])} signal(s)" if r["signals"] else "None in recent 20"
        print(f"{r['idx']:3} | {r['id']:28} | {r['status']:8} | {r['posts']:5} | {sig_summary}")
        for s in r["signals"][:1]:
            print(f"    └──> {s['symbol']} {s['side']} (Entry: {s['entry_mid']}, SL: {s['sl']}, TPs: {s['tps']})")

    print("=" * 75)
    print(f"Diagnostic Summary (Completed in {elapsed:.2f}s):")
    print(f"  Accessible Channels: {accessible_channels}/{len(CHANNELS_CONFIG)} ({(accessible_channels/len(CHANNELS_CONFIG))*100:.1f}%)")
    print(f"  Total Recent Messages Ingested: {total_messages}")
    print(f"  Live Signals Parsed from Ingested Stream: {total_signals_parsed}")
    print("=" * 75)

    if accessible_channels >= 140:
        print(f"✅ 155-CHANNEL FLEET LIVE INGESTION VERIFICATION: PASS ({accessible_channels}/{len(CHANNELS_CONFIG)} accessible)")
        return 0
    else:
        print(f"⚠️ LIVE INGESTION WARNING: {accessible_channels}/{len(CHANNELS_CONFIG)} accessible")
        return 1

if __name__ == "__main__":
    sys.exit(main())
