#!/usr/bin/env python
"""
TradingAgents POC - Model Comparison Runner
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent / ".venv" / "src" / "tradingagents"))

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG, build_default_config
from tradingagents.dataflows.config import set_config


def run_analysis(ticker, trade_date, provider_name, config_overrides=None):
    print(f"\n{'='*60}")
    print(f"Running TradingAgents Analysis")
    print(f"Ticker: {ticker}")
    print(f"Date: {trade_date}")
    print(f"Provider: {provider_name}")
    print(f"{'='*60}\n")
    
    global DEFAULT_CONFIG
    DEFAULT_CONFIG = build_default_config()
    config = DEFAULT_CONFIG.copy()
    
    if config_overrides:
        config.update(config_overrides)
    
    results_dir = Path("./results") / provider_name / ticker / trade_date
    results_dir.mkdir(parents=True, exist_ok=True)
    config["results_dir"] = str(results_dir)
    
    set_config(config)
    
    graph = TradingAgentsGraph(
        selected_analysts=["market", "news", "fundamentals"],
        debug=True,
        config=config,
    )
    
    print(f"Starting analysis for {ticker} on {trade_date} with {provider_name}...")
    
    try:
        final_state, signal = graph.propagate(ticker, trade_date)
        if final_state is None:
            raise RuntimeError("No final state returned from graph")
        
        result = {
            "ticker": ticker,
            "trade_date": trade_date,
            "provider": provider_name,
            "timestamp": datetime.now().isoformat(),
            "company_of_interest": final_state.get("company_of_interest"),
            "market_report": final_state.get("market_report", ""),
            "sentiment_report": final_state.get("sentiment_report", ""),
            "news_report": final_state.get("news_report", ""),
            "fundamentals_report": final_state.get("fundamentals_report", ""),
            "investment_debate_state": final_state.get("investment_debate_state", {}),
            "trader_investment_plan": final_state.get("trader_investment_plan", ""),
            "risk_debate_state": final_state.get("risk_debate_state", {}),
            "investment_plan": final_state.get("investment_plan", ""),
            "final_trade_decision": final_state.get("final_trade_decision", ""),
            "run_settings": graph.run_settings(),
            "signal": signal,
        }
        
        output_file = results_dir / "analysis_result.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"\n✓ Analysis completed successfully!")
        print(f"  Results saved to: {output_file}")
        return result
        
    except Exception as e:
        print(f"\n✗ Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        error_result = {
            "ticker": ticker,
            "trade_date": trade_date,
            "provider": provider_name,
            "timestamp": datetime.now().isoformat(),
            "error": str(e),
            "error_type": type(e).__name__,
        }
        output_file = results_dir / "analysis_error.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(error_result, f, ensure_ascii=False, indent=2)
        return error_result


def compare_models(ticker, trade_date):
    providers = {
        "ollama": {
            "TRADINGAGENTS_LLM_PROVIDER": "ollama",
            "TRADINGAGENTS_DEEP_THINK_LLM": "qwen3.5:9b",
            "TRADINGAGENTS_QUICK_THINK_LLM": "qwen3.5:9b",
            "TRADINGAGENTS_DEEP_THINK_PROVIDER": "ollama",
            "TRADINGAGENTS_QUICK_THINK_PROVIDER": "ollama",
            "TRADINGAGENTS_DEEP_THINK_BACKEND_URL": "http://localhost:11434/v1",
            "TRADINGAGENTS_QUICK_THINK_BACKEND_URL": "http://localhost:11434/v1",
            "TRADINGAGENTS_LLM_BACKEND_URL": "http://localhost:11434/v1",
        },
    }
    
    results = {}
    for provider_name, config_overrides in providers.items():
        print(f"\n{'#'*80}")
        print(f"Testing provider: {provider_name}")
        print(f"{'#'*80}")
        
        for key, value in config_overrides.items():
            os.environ[key] = value
        
        result = run_analysis(ticker, trade_date, provider_name, config_overrides)
        results[provider_name] = result
    
    comparison_file = Path("./results") / f"comparison_{ticker}_{trade_date}.json"
    with open(comparison_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*60}")
    print(f"Comparison saved to: {comparison_file}")
    print(f"{'='*60}")
    
    for provider_name, result in results.items():
        if "error" in result:
            print(f"\n{provider_name}: ERROR - {result['error']}")
        else:
            decision = result.get("final_trade_decision", "")[:200]
            print(f"\n{provider_name}: {decision}...")
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Compare TradingAgents providers")
    parser.add_argument("ticker", help="Stock ticker (e.g., AAPL, 005930.KS)")
    parser.add_argument("--date", help="Trade date (YYYY-MM-DD), default: today")
    
    args = parser.parse_args()
    
    if args.date is None:
        args.date = datetime.now().strftime("%Y-%m-%d")
    
    compare_models(args.ticker, args.date)


if __name__ == "__main__":
    main()