with open('src/invest_agent/evaluation.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix indentation: lines 291-320 have 8 spaces but should have 4 spaces
# (they're inside a for loop that's already at 4 spaces)
for i in range(len(lines)):
    line = lines[i]
    # Check if line starts with 8 spaces and is in the _compute_model_summaries function
    if line.startswith('        buy_20d = ') or line.startswith('        sell_20d = ') or \
       line.startswith('        buy_hit_20d = ') or line.startswith('        sell_hit_20d = ') or \
       line.startswith('        total_20d = ') or line.startswith('        total_hit_20d = ') or \
       line.startswith('        buy_hit_rate_20d = ') or line.startswith('        sell_hit_rate_20d = ') or \
       line.startswith('        total_hit_rate_20d = ') or line.startswith('        returns_1d = ') or \
       line.startswith('        returns_5d = ') or line.startswith('        returns_20d = ') or \
       line.startswith('        avg_return_1d = ') or line.startswith('        avg_return_5d = ') or \
       line.startswith('        avg_return_20d = ') or line.startswith('        non_eval_reasons = []') or \
       line.startswith('        for e in evals:') or line.startswith('        summary = ModelEvaluationSummary(') or \
       line.startswith('        summaries.append(summary)') or line.startswith('    return summaries'):
        # Replace 8 leading spaces with 4 leading spaces
        if line.startswith('        '):
            lines[i] = line[4:]
    elif line.startswith('            if not e.evaluable:') or \
         line.startswith('                non_eval_reasons.extend(e.non_evaluable_reasons)') or \
         line.startswith('            model_provider=provider,') or \
         line.startswith('            model_name=name,') or \
         line.startswith('            total_decisions=total,') or \
         line.startswith('            buy_count=buy_count,') or \
         line.startswith('            sell_count=sell_count,') or \
         line.startswith('            no_trade_count=no_trade_count,') or \
         line.startswith('            blocked_count=blocked_count,') or \
         line.startswith('            error_count=error_count,') or \
         line.startswith('            evaluated_count=evaluated,') or \
         line.startswith('            pending_count=0,') or \
         line.startswith('            unevaluable_count=unevaluable,') or \
         line.startswith('            buy_hit_rate_1d=buy_hit_rate_1d,') or \
         line.startswith('            sell_hit_rate_1d=sell_hit_rate_1d,') or \
         line.startswith('            total_hit_rate_1d=total_hit_rate_1d,') or \
         line.startswith('            hit_rate_1d_denominator=total_1d,') or \
         line.startswith('            buy_hit_rate_5d=buy_hit_rate_5d,') or \
         line.startswith('            sell_hit_rate_5d=sell_hit_rate_5d,') or \
         line.startswith('            total_hit_rate_5d=total_hit_rate_5d,') or \
         line.startswith('            hit_rate_5d_denominator=total_5d,') or \
         line.startswith('            buy_hit_rate_20d=buy_hit_rate_20d,') or \
         line.startswith('            sell_hit_rate_20d=sell_hit_rate_20d,') or \
         line.startswith('            total_hit_rate_20d=total_hit_rate_20d,') or \
         line.startswith('            hit_rate_20d_denominator=total_20d,') or \
         line.startswith('            avg_return_1d=avg_return_1d,') or \
         line.startswith('            avg_return_5d=avg_return_5d,') or \
         line.startswith('            avg_return_20d=avg_return_20d,') or \
         line.startswith('            non_evaluable_reasons=list(set(non_eval_reasons)),') or \
         line.startswith('        )'):
        # Replace 12 leading spaces with 8 leading spaces (for nested inside for loop)
        if line.startswith('            '):
            lines[i] = line[4:]

with open('src/invest_agent/evaluation.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('Fixed indentation properly')