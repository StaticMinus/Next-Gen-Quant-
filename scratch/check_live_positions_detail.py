from src.integrations.ctrader_mcp_client import CTraderMCPClient

c = CTraderMCPClient()
if c.initialize():
    en = c.get_enriched_positions()
    print(f"Total Active Positions: {len(en)}")
    for p in en:
        sym = p['symbol_name']
        pid = p['position_id']
        entry = p['entry_price']
        sl = p['stop_loss']
        tp = p['take_profit']
        pnl = p['floating_pnl']
        lots = p['lots']
        print(f"• {sym} (#{pid}) {lots} lots | Entry: ${entry:.2f} | SL: ${sl} | TP: ${tp} | PnL: ${pnl:+.2f}")
