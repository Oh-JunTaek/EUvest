import re

with open('src/invest_agent/evaluation.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace all 8-space indents with 4-space indents in the _compute_model_summaries function
# This regex replaces 8 leading spaces with 4 leading spaces for specific patterns
patterns = [
    (r'^        buy_20d = ', '        buy_20d = '),
    ('        sell_20d = ', '        sell_20d = '),
    ('        buy_hit_20d = ', '        buy_hit_20d = '),
    ('        sell_hit_20d = ', '        sell_hit_20d = '),
    ('        total_20d = ', '        total_20d = '),
    ('        total_hit_20d = ', '        total_hit_20d = '),
    ('        buy_hit_rate_20d = ', '        buy_hit_rate_20d = '),
    ('        sell_hit_rate_20d = ', '        sell_hit_rate_20d = '),
    ('        total_hit_rate_20d = ', '        total_hit_rate_20d = '),
    ('        returns_1d = ', '        returns_1d = '),
    ('        returns_5d = ', '        returns_5d = '),
    ('        returns_20d = ', '        returns_20d = '),
    ('        avg_return_1d = ', '        avg_return_1d = '),
    ('        avg_return_5d = ', '        avg_return_5d = '),
    ('        avg_return_20d = ', '        avg_return_20d = '),
    ('        non_eval_reasons = []', '        non_eval_reasons = []'),
    ('        for e in evals:', '        for e in evals:'),
    ('            if not e.evaluable:', '            if not e.evaluable:'),
    ('                non_eval_reasons.extend(e.non_evaluable_reasons)', '                non_eval_reasons.extend(e.non_evaluable_reasons)'),
    ('        summary = ModelEvaluationSummary(', '        summary = ModelEvaluationSummary('),
    ('            model_provider=provider,', '            model_provider=provider,'),
    ('            model_name=name,', '            model_name=name,'),
    ('            total_decisions=total,', '            total_decisions=total,'),
    ('            buy_count=buy_count,', '            buy_count=buy_count,'),
    ('            sell_count=sell_count,', '            sell_count=sell_count,'),
    ('            no_trade_count=no_trade_count,', '            no_trade_count=no_trade_count,'),
    ('            blocked_count=blocked_count,', '            blocked_count=blocked_count,'),
    ('            error_count=error_count,', '            error_count=error_count,'),
    ('            evaluated_count=evaluated,', '            evaluated_count=evaluated,'),
    ('            pending_count=0,', '            pending_count=0,'),
    ('            unevaluable_count=unevaluable,', '            unevaluable_count=unevaluable,'),
    ('            buy_hit_rate_1d=buy_hit_rate_1d,', '            buy_hit_rate_1d=buy_hit_rate_1d,'),
    ('            sell_hit_rate_1d=sell_hit_rate_1d,', '            sell_hit_rate_1d=sell_hit_rate_1d,'),
    ('            total_hit_rate_1d=total_hit_rate_1d,', '            total_hit_rate_1d=total_hit_rate_1d,'),
    ('            hit_rate_1d_denominator=total_1d,', '            hit_rate_1d_denominator=total_1d,'),
    ('            buy_hit_rate_5d=buy_hit_rate_5d,', '            buy_hit_rate_5d=buy_hit_rate_5d,'),
    ('            sell_hit_rate_5d=sell_hit_rate_5d,', '            sell_hit_rate_5d=sell_hit_rate_5d,'),
    ('            total_hit_rate_5d=total_hit_rate_5d,', '            total_hit_rate_5d=total_hit_rate_5d,'),
    ('            hit_rate_5d_denominator=total_5d,', '            hit_rate_5d_denominator=total_5d,'),
    ('            buy_hit_rate_20d=buy_hit_rate_20d,', '            buy_hit_rate_20d=buy_hit_rate_20d,'),
    ('            sell_hit_rate_20d=sell_hit_rate_20d,', '            sell_hit_rate_20d=sell_hit_rate_20d,'),
    ('            total_hit_rate_20d=total_hit_rate_20d,', '            total_hit_rate_20d=total_hit_rate_20d,'),
    ('            hit_rate_20d_denominator=total_20d,', '            hit_rate_20d_denominator=total_20d,'),
    ('            avg_return_1d=avg_return_1d,', '            avg_return_1d=avg_return_1d,'),
    ('            avg_return_5d=avg_return_5d,', '            avg_return_5d=avg_return_5d,'),
    ('            avg_return_20d=avg_return_20d,', '            avg_return_20d=avg_return_20d,'),
    ('            non_evaluable_reasons=list(set(non_eval_reasons)),', '            non_evaluable_reasons=list(set(non_eval_reasons)),'),
    ('        )', '        )'),
    ('        summaries.append(summary)', '        summaries.append(summary)'),
    ('    return summaries', '    return summaries'),
]

with open('src/invest_agent/evaluation.py', 'r', encoding='utf-8') as f:
    content = f.read()

for old, new in replacements:
    content = content.replace(old, new)

with open('src/invest_agent/evaluation.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed all indentation')