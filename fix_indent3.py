with open('src/invest_agent/evaluation.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix indentation for lines after the returns_20d line
for i, line in enumerate(lines):
    if line.startswith('        avg_return_1d = (sum(returns_1d) / len(returns_1d)).quantize(Decimal("0.0001")) if returns_1d else None'):
        lines[i] = '        avg_return_1d = (sum(returns_1d) / len(returns_1d)).quantize(Decimal("0.0001")) if returns_1d else None\n'
    elif line.startswith('        avg_return_5d = (sum(returns_5d) / len(returns_5d)).quantize(Decimal("0.0001")) if returns_5d else None'):
        lines[i] = '        avg_return_5d = (sum(returns_5d) / len(returns_5d)).quantize(Decimal("0.0001")) if returns_5d else None\n'
    elif line.startswith('        avg_return_20d = (sum(returns_20d) / len(returns_20d)).quantize(Decimal("0.0001")) if returns_20d else None'):
        lines[i] = '        avg_return_20d = (sum(returns_20d) / len(returns_20d)).quantize(Decimal("0.0001")) if returns_20d else None\n'
    elif line.startswith('        non_eval_reasons = []'):
        lines[i] = '        non_eval_reasons = []\n'
    elif line.startswith('        for e in evals:'):
        lines[i] = '        for e in evals:\n'
    elif line.startswith('            if not e.evaluable:'):
        lines[i] = '            if not e.evaluable:\n'
    elif line.startswith('                non_eval_reasons.extend(e.non_evaluable_reasons)'):
        lines[i] = '                non_eval_reasons.extend(e.non_evaluable_reasons)\n'
    elif line.startswith('        summary = ModelEvaluationSummary('):
        lines[i] = '        summary = ModelEvaluationSummary(\n'
    elif line.startswith('            model_provider=provider,'):
        lines[i] = '            model_provider=provider,\n'
    elif line.startswith('            model_name=name,'):
        lines[i] = '            model_name=name,\n'
    elif line.startswith('            total_decisions=total,'):
        lines[i] = '            total_decisions=total,\n'
    elif line.startswith('            buy_count=buy_count,'):
        lines[i] = '            buy_count=buy_count,\n'
    elif line.startswith('            sell_count=sell_count,'):
        lines[i] = '            sell_count=sell_count,\n'
    elif line.startswith('            no_trade_count=no_trade_count,'):
        lines[i] = '            no_trade_count=no_trade_count,\n'
    elif line.startswith('            blocked_count=blocked_count,'):
        lines[i] = '            blocked_count=blocked_count,\n'
    elif line.startswith('            error_count=error_count,'):
        lines[i] = '            error_count=error_count,\n'
    elif line.startswith('            evaluated_count=evaluated,'):
        lines[i] = '            evaluated_count=evaluated,\n'
    elif line.startswith('            pending_count=0,'):
        lines[i] = '            pending_count=0,\n'
    elif line.startswith('            unevaluable_count=unevaluable,'):
        lines[i] = '            unevaluable_count=unevaluable,\n'
    elif line.startswith('            buy_hit_rate_1d=buy_hit_rate_1d,'):
        lines[i] = '            buy_hit_rate_1d=buy_hit_rate_1d,\n'
    elif line.startswith('            sell_hit_rate_1d=sell_hit_rate_1d,'):
        lines[i] = '            sell_hit_rate_1d=sell_hit_rate_1d,\n'
    elif line.startswith('            total_hit_rate_1d=total_hit_rate_1d,'):
        lines[i] = '            total_hit_rate_1d=total_hit_rate_1d,\n'
    elif line.startswith('            hit_rate_1d_denominator=total_1d,'):
        lines[i] = '            hit_rate_1d_denominator=total_1d,\n'
    elif line.startswith('            buy_hit_rate_5d=buy_hit_rate_5d,'):
        lines[i] = '            buy_hit_rate_5d=buy_hit_rate_5d,\n'
    elif line.startswith('            sell_hit_rate_5d=sell_hit_rate_5d,'):
        lines[i] = '            sell_hit_rate_5d=sell_hit_rate_5d,\n'
    elif line.startswith('            total_hit_rate_5d=total_hit_rate_5d,'):
        lines[i] = '            total_hit_rate_5d=total_hit_rate_5d,\n'
    elif line.startswith('            hit_rate_5d_denominator=total_5d,'):
        lines[i] = '            hit_rate_5d_denominator=total_5d,\n'
    elif line.startswith('            buy_hit_rate_20d=buy_hit_rate_20d,'):
        lines[i] = '            buy_hit_rate_20d=buy_hit_rate_20d,\n'
    elif line.startswith('            sell_hit_rate_20d=sell_hit_rate_20d,'):
        lines[i] = '            sell_hit_rate_20d=sell_hit_rate_20d,\n'
    elif line.startswith('            total_hit_rate_20d=total_hit_rate_20d,'):
        lines[i] = '            total_hit_rate_20d=total_hit_rate_20d,\n'
    elif line.startswith('            hit_rate_20d_denominator=total_20d,'):
        lines[i] = '            hit_rate_20d_denominator=total_20d,\n'
    elif line.startswith('            avg_return_1d=avg_return_1d,'):
        lines[i] = '            avg_return_1d=avg_return_1d,\n'
    elif line.startswith('            avg_return_5d=avg_return_5d,'):
        lines[i] = '            avg_return_5d=avg_return_5d,\n'
    elif line.startswith('            avg_return_20d=avg_return_20d,'):
        lines[i] = '            avg_return_20d=avg_return_20d,\n'
    elif line.startswith('            non_evaluable_reasons=list(set(non_eval_reasons)),'):
        lines[i] = '            non_evaluable_reasons=list(set(non_eval_reasons)),\n'
    elif line.startswith('        )'):
        lines[i] = '        )\n'
    elif line.startswith('        summaries.append(summary)'):
        lines[i] = '        summaries.append(summary)\n'
    elif line.startswith('    return summaries'):
        lines[i] = '    return summaries\n'

with open('src/invest_agent/evaluation.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('Fixed indentation part 2')