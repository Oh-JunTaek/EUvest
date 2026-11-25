with open('src/invest_agent/evaluation.py', 'r', encoding='utf-8') as f:
    content = f.read()

replacements = [
    ('        buy_20d = [e for e in evals if e.outcome == DecisionOutcome.TRADE', '        buy_20d = [e for e in evals if e.outcome == DecisionOutcome.TRADE'),
    ('        sell_20d = [e for e in evals if e.outcome == DecisionOutcome.TRADE', '        sell_20d = [e for e in evals if e.outcome == DecisionOutcome.TRADE'),
    ('        buy_hit_20d = sum(1 for e in buy_20d if e.horizon_20d_hit)', '        buy_hit_20d = sum(1 for e in buy_20d if e.horizon_20d_hit)'),
    ('        sell_hit_20d = sum(1 for e in sell_20d if e.horizon_20d_hit)', '        sell_hit_20d = sum(1 for e in sell_20d if e.horizon_20d_hit)'),
    ('        total_20d = len(buy_20d) + len(sell_20d)', '        total_20d = len(buy_20d) + len(sell_20d)'),
    ('        total_hit_20d = buy_hit_20d + sell_hit_20d', '        total_hit_20d = buy_hit_20d + sell_hit_20d'),
    ('        buy_hit_rate_20d = (Decimal(buy_hit_20d) / Decimal(len(buy_20d)) * Decimal("100")).quantize(Decimal("0.01")) if buy_20d else None', '        buy_hit_rate_20d = (Decimal(buy_hit_20d) / Decimal(len(buy_20d)) * Decimal("100")).quantize(Decimal("0.01")) if buy_20d else None'),
    ('        sell_hit_rate_20d = (Decimal(sell_hit_20d) / Decimal(len(sell_20d)) * Decimal("100")).quantize(Decimal("0.01")) if sell_20d else None', '        sell_hit_rate_20d = (Decimal(sell_hit_20d) / Decimal(len(sell_20d)) * Decimal("100")).quantize(Decimal("0.01")) if sell_20d else None'),
    ('        total_hit_rate_20d = (Decimal(total_hit_20d) / Decimal(total_20d) * Decimal("100")).quantize(Decimal("0.01")) if total_20d else None', '        total_hit_rate_20d = (Decimal(total_hit_20d) / Decimal(total_20d) * Decimal("100")).quantize(Decimal("0.01")) if total_20d else None'),
    ('        returns_1d = [e.horizon_1d_return_pct for e in evals if e.horizon_1d_return_pct is not None]', '        returns_1d = [e.horizon_1d_return_pct for e in evals if e.horizon_1d_return_pct is not None]'),
    ('        returns_5d = [e.horizon_5d_return_pct for e in evals if e.horizon_5d_return_pct is not None]', '        returns_5d = [e.horizon_5d_return_pct for e in evals if e.horizon_5d_return_pct is not None]'),
    ('        returns_20d = [e.horizon_20d_return_pct for e in evals if e.horizon_20d_return_pct is not None]', '        returns_20d = [e.horizon_20d_return_pct for e in evals if e.horizon_20d_return_pct is not None]'),
    ('        avg_return_1d = (sum(returns_1d) / len(returns_1d)).quantize(Decimal("0.0001")) if returns_1d else None', '        avg_return_1d = (sum(returns_1d) / len(returns_1d)).quantize(Decimal("0.0001")) if returns_1d else None'),
    ('        avg_return_5d = (sum(returns_5d) / len(returns_5d)).quantize(Decimal("0.0001")) if returns_5d else None', '        avg_return_5d = (sum(returns_5d) / len(returns_5d)).quantize(Decimal("0.0001")) if returns_5d else None'),
    ('        avg_return_20d = (sum(returns_20d) / len(returns_20d)).quantize(Decimal("0.0001")) if returns_20d else None', '        avg_return_20d = (sum(returns_20d) / len(returns_20d)).quantize(Decimal("0.0001")) if returns_20d else None'),
    ('        non_eval_reasons = []', '        non_eval_reasons = []'),
    ('        for e in evals:', '        for e in evals:'),
    ('            if not e.evaluable:', '            if not e.evaluable:'),
    ('                non_eval_reasons.extend(e.non_evaluable_reasons)', '                non_eval_reasons.extend(e.non_evaluable_reasons)'),

for old, new in replacements:
    content = content.replace(old, new)

with open('src/invest_agent/evaluation.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed first batch')