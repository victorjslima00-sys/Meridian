import os
import pandas as pd
import json
from datetime import datetime, date, timedelta

def main():
    mock_dir = "/Users/mac/.gemini/antigravity/scratch/meridian/tests/e2e/mock_data/"
    os.makedirs(mock_dir, exist_ok=True)
    
    start_date = date(2019, 1, 1)
    end_date = date(2024, 7, 1)
    dates = []
    curr = start_date
    while curr <= end_date:
        # Weekdays only
        if curr.weekday() < 5:
            dates.append(curr)
        curr += timedelta(days=1)
        
    n_days = len(dates)
    
    # PETR4 mock yfinance
    petr4_prices = [20.0 + (i * 0.02) for i in range(n_days)]
    petr4_df = pd.DataFrame({
        "Open": petr4_prices,
        "High": [p + 0.5 for p in petr4_prices],
        "Low": [p - 0.5 for p in petr4_prices],
        "Close": [p + 0.1 for p in petr4_prices],
        "Volume": [10000000] * n_days
    }, index=pd.to_datetime(dates))
    petr4_df.index.name = "Date"
    petr4_df.to_csv(os.path.join(mock_dir, "yf_PETR4.csv"))
    
    # ^BVSP mock yfinance
    bvsp_prices = [90000.0 + (i * 20.0) for i in range(n_days)]
    bvsp_df = pd.DataFrame({
        "Open": bvsp_prices,
        "High": [p + 200.0 for p in bvsp_prices],
        "Low": [p - 200.0 for p in bvsp_prices],
        "Close": [p + 50.0 for p in bvsp_prices],
        "Volume": [5000000] * n_days
    }, index=pd.to_datetime(dates))
    bvsp_df.index.name = "Date"
    bvsp_df.to_csv(os.path.join(mock_dir, "yf_BVSP.csv"))
    
    # Brapi PETR4 JSON
    brapi_payload = {
        "results": [
            {
                "symbol": "PETR4",
                "regularMarketOpen": 35.0,
                "regularMarketDayHigh": 36.0,
                "regularMarketDayLow": 34.5,
                "regularMarketPrice": 35.5,
                "regularMarketVolume": 10000000,
                "historicalDataPrice": [
                    {
                        "date": int(datetime(2024, 6, 30).timestamp()),
                        "open": 35.0,
                        "high": 36.0,
                        "low": 34.5,
                        "close": 35.5,
                        "volume": 10000000,
                        "adjustedClose": 35.5
                    }
                ]
            }
        ]
    }
    with open(os.path.join(mock_dir, "brapi_PETR4.json"), "w") as f:
        json.dump(brapi_payload, f, indent=2)
        
    print("Mock data generated successfully.")

if __name__ == "__main__":
    main()
