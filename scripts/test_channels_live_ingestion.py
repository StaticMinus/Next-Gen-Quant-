"""
Live Channel Ingestion & Parsing Verification Suite
===================================================
Tests real-time HTTP connectivity, message extraction, and parser resilience
across all 25 configured signal channels.
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.integrations.telegram_multi_signal_copier import (
    CHANNELS_CONFIG,
    MultiChannelSignalParser,
    TelegramMultiSignalCopier
)

def main():
    print("=" * 70)
    print(f"AGENTQUANT {len(CHANNELS_CONFIG)}-CHANNEL LIVE INGESTION DIAGNOSTIC")
    print(f"Total Target Channels: {len(CHANNELS_CONFIG)}")
    print("=" * 70)

    copier = TelegramMultiSignalCopier(dry_run=True)
    
    total_messages = 0
    total_signals_parsed = 0
    accessible_channels = 0

    print(f"{'#':2} | {'Channel ID':26} | {'Status':10} | {'Posts':5} | {'Signals Detected'}")
    print("-" * 70)

    for idx, ch in enumerate(CHANNELS_CONFIG, 1):
        cid = ch["id"]
        cname = ch["name"]
        try:
            msgs = copier.fetch_channel_posts(cid)
            post_count = len(msgs)
            total_messages += post_count

            parsed = []
            for m in msgs:
                sig = MultiChannelSignalParser.parse_message(m["text"], cid)
                if sig:
                    parsed.append(sig)

            total_signals_parsed += len(parsed)
            if post_count > 0:
                accessible_channels += 1
                status = "OK"
            else:
                status = "QUIET/EMPTY"

            sig_summary = f"{len(parsed)} signal(s)" if parsed else "None in recent 20 posts"
            print(f"{idx:2} | {cid:26} | {status:10} | {post_count:5} | {sig_summary}")

            for s in parsed[:1]:
                print(f"   └──> {s['symbol']} {s['side']} (Entry: {s['entry_mid']}, SL: {s['sl']}, TPs: {s['tps']})")

        except Exception as e:
            print(f"{idx:2} | {cid:26} | ERROR      |     0 | Exception: {e}")

    print("=" * 70)
    print(f"Diagnostic Summary:")
    print(f"  Accessible Channels: {accessible_channels}/{len(CHANNELS_CONFIG)} ({(accessible_channels/len(CHANNELS_CONFIG))*100:.1f}%)")
    print(f"  Total Recent Messages Ingested: {total_messages}")
    print(f"  Live Signals Parsed from Ingested Stream: {total_signals_parsed}")
    print("=" * 70)

    if accessible_channels >= 20:
        print("✅ LIVE INGESTION VERIFICATION: PASS")
        return 0
    else:
        print("⚠️ LIVE INGESTION VERIFICATION: WARNING (Fewer than 20 channels accessible)")
        return 1

if __name__ == "__main__":
    sys.exit(main())
