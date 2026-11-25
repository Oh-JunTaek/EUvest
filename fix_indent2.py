with open('src/invest_agent/evaluation.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix indentation for lines 291-310
for i, line in enumerate(lines):
    if line.startswith('        buy_20d = [e for e in evals if e.outcome == DecisionOutcome.TRADE'):
        lines[i] = '        buy_20d = [e for e in evals if e.outcome == DecisionOutcome.TRADE and e.side == OrderSide.BUY and e.horizon_20d_hit is not None]\n'
    elif line.startswith('        sell_20d = [e for e in evals if e.outcome == DecisionOutcome.TRADE and e.side == OrderSide.SELL and e.horizon_20d_hit is not None]'):
        lines[i] = '        sell_20d = [e for e in evals if e.outcome == DecisionOutcome.TRADE and e.side == OrderSide.SELL and e.horizon_20d_hit is not None]\n'
    elif line.startswith('        buy_hit_20d = sum(1 for e in buy_20d if e.horizon_20d_hit)'):
        lines[i] = '        buy_hit_20d = sum(1 for e in buy_20d if e.horizon_20d_hit)\n'
    elif line.startswith('        sell_hit_20d = sum(1 for e in sell_20d if e.horizon_20d_hit)'):
        lines[i] = '        sell_hit_20d = sum(1 for e in sell_20d if e.horizon_20d_hit)\n'
    elif line.startswith('        total_20d = len(buy_20d) + len(sell_20d)'):
        lines[i] = '        total_20d = len(buy_20d) + len(sell_20d)\n'
    elif line.startswith('        total_hit_20d = buy_hit_20d + sell_hit_20d'):
        lines[i] = '        total_hit_20d = buy_hit_20d + sell_hit_20d\n'
    elif line.startswith('        buy_hit_rate_20d = (Decimal(buy_hit_20d) / Decimal(len(buy_20d)) * Decimal("100")).quantize(Decimal("0.01")) if buy_20d else None'):
        lines[i] = '        buy_hit_rate_20d = (Decimal(buy_hit_20d) / Decimal(len(buy_20d)) * Decimal("100")).quantize(Decimal("0.01")) if buy_20d else None\n'
    elif line.startswith('        sell_hit_rate_20d = (Decimal(sell_hit_20d) / Decimal(len(sell_20d)) * Decimal("100")).quantize(Decimal("0.01")) if sell_20d else None'):
        lines[i] = '        sell_hit_rate_20d = (Decimal(sell_hit_20d) / Decimal(len(sell_20d)) * Decimal("100")).quantize(Decimal("0.01")) if sell_20d else None\n'
    elif line.startswith('        total_hit_rate_20d = (Decimal(total_hit_20d) / Decimal(total_20d) * Decimal("100")).quantize(Decimal("0.01")) if total_20d else None'):
        lines[i] = '        total_hit_rate_20d = (Decimal(total_hit_20d) / Decimal(total_20d) * Decimal("100")).quantize(Decimal("0.01")) if total_20d else None\n'
    elif line.startswith('        returns_1d = [e.horizon_1d_return_pct for e in evals if e.horizon_1d_return_pct is not None]'):
        lines[i] = '        returns_1d = [e.horizon_1d_return_pct for e in evals if e.horizon_1d_return_pct is not None]\n'
    elif line.startswith('        returns_5d = [e.horizon_5d_return_pct for e in evals if e.horizon_5d_return_pct is not None]'):
        lines[i] = '        returns_5d = [e.horizon_5d_return_pct for e in evals if e.horizon_5d_return_pct is not None]\n'
    elif line.startswith('        returns_20d = [e.horizon_20d_return_pct for e in evals if e.horizon_20d_return_pct is not None]'):
        lines[i] = '        returns_20d = [e.horizon_20d_return_pct for e in evals if e.horizon_20d_return_pct is not None]\n'

with open('src/invest_agent/evaluation.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('Fixed indentation part 1')