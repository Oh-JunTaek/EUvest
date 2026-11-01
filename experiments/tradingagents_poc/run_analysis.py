#!/usr/bin/env python
"""
TradingAgents POC - Single Analysis Runner
Runs analysis for a given ticker using configured LLM provider.
Saves results as JSON for comparison.
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

# Load .env file FIRST before importing tradingagents
from dotenv import load_dotenv
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

# Add the tradingagents source to path
sys.path.insert(0, str(Path(__file__).parent / ".venv" / "src" / "tradingagents"))

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.config import set_config


def run_analysis(ticker: str, trade_date: str = None, provider_name: str = "ollama"):
    """Run TradingAgents analysis for a ticker."""
    
    # Use today's date if not provided
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")
    
    print(f"\n{'='*60}")
    print(f"Running TradingAgents Analysis")
    print(f"Ticker: {ticker}")
    print(f"Date: {trade_date}")
    print(f"Provider: {provider_name}")
    print(f"{'='*60}\n")
    
    # Load config (already has env vars applied via DEFAULT_CONFIG)
    config = DEFAULT_CONFIG.copy()
    
    # Override results dir for this run
    results_dir = Path("./results") / provider_name / ticker / trade_date
    results_dir.mkdir(parents=True, exist_ok=True)
    config["results_dir"] = str(results_dir)
    
    # Apply config
    set_config(config)
    
    # Create graph with selected analysts
    # Using market, news, fundamentals for comprehensive analysis
    graph = TradingAgentsGraph(
        selected_analysts=["market", "news", "fundamentals"],
        debug=True,
        config=config,
    )
    
    # Run analysis
    print(f"Starting analysis for {ticker} on {trade_date}...")
    
    try:
        # Use propagate method which runs the full graph and returns final state
        final_state, signal = graph.propagate(ticker, trade_date)
        
        if final_state is None:
            raise RuntimeError("No final state returned from graph")
        
        # Extract key results
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
        }
        
        # Save full result
        output_file = results_dir / "analysis_result.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"\n✓ Analysis completed successfully!")
        print(f"  Results saved to: {output_file}")
        
        # Print summary
        print(f"\n--- Final Decision ---")
        print(result["final_trade_decision"][:500] + "..." if len(result["final_trade_decision"]) > 500 else result["final_trade_decision"])
        
        return result
        
    except Exception as e:
        print(f"\n✗ Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        
        # Save error result
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


def main():
    parser = argparse.ArgumentParser(description="Run TradingAgents analysis")
    parser.add_argument("ticker", help="Stock ticker (e.g., AAPL, 005930.KS)")
    parser.add_argument("--date", help="Trade date (YYYY-MM-DD), default: today")
    parser.add_argument("--provider", default="ollama", choices=["ollama", "nvidia"], 
                        help="LLM provider to use")
    
    args = parser.parse_args()
    
    # Run analysis
    run_analysis(args.ticker, args.date, args.provider)


if __name__ == "__main__":
    main()