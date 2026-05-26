"""
Trade AI v12 - Data Pipeline Validator
Tests all stages and identifies missing data/API issues
"""

import json
import os
import csv
from pathlib import Path

class Validator:
    def __init__(self):
        self.issues = []
        self.warnings = []
        self.passes = []
    
    def add_issue(self, stage, message):
        self.issues.append(f"❌ STAGE {stage}: {message}")
    
    def add_warning(self, stage, message):
        self.warnings.append(f"⚠️  STAGE {stage}: {message}")
    
    def add_pass(self, stage, message):
        self.passes.append(f"✓ STAGE {stage}: {message}")
    
    def report(self):
        print("\n" + "="*70)
        print("TRADE AI v12 VALIDATION REPORT")
        print("="*70)
        
        if self.passes:
            print(f"\n✓ PASSING ({len(self.passes)}):")
            for p in self.passes:
                print(f"  {p}")
        
        if self.warnings:
            print(f"\n⚠️  WARNINGS ({len(self.warnings)}):")
            for w in self.warnings:
                print(f"  {w}")
        
        if self.issues:
            print(f"\n❌ ISSUES ({len(self.issues)}):")
            for i in self.issues:
                print(f"  {i}")
        
        print("\n" + "="*70)
        return len(self.issues) == 0

def validate_finviz_csv(csv_path, validator):
    """Validate Finviz CSV structure and data"""
    stage = "2: Finviz Ingestion"
    
    if not os.path.exists(csv_path):
        validator.add_issue(stage, f"CSV not found: {csv_path}")
        return None
    
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            
            required_fields = [
                "Ticker", "Company", "Sector", "Industry", "Country",
                "Market Cap", "Shares Float", "Volume", "Price", "Change"
            ]
            
            # Check for required columns
            missing = [f for f in required_fields if f not in fieldnames]
            if missing:
                validator.add_issue(stage, f"Missing columns: {missing}")
                return None
            
            validator.add_pass(stage, f"All required columns present: {len(fieldnames)} total")
            
            # Read first row
            rows = list(reader)
            if not rows:
                validator.add_issue(stage, "CSV is empty (no data rows)")
                return None
            
            first = rows[0]
            validator.add_pass(stage, f"CSV contains {len(rows)} ticker(s)")
            
            # Validate data types in first row
            ticker_sym = first.get("Ticker", "").strip().strip('"')
            price = first.get("Price", "").strip().strip('"')
            gap = first.get("Change", "").strip().strip('"')
            float_shares = first.get("Shares Float", "").strip().strip('"')
            volume = first.get("Volume", "").strip().strip('"')
            country = first.get("Country", "").strip().strip('"')
            
            # Check if values are present
            if not ticker_sym:
                validator.add_issue(stage, "Ticker field is empty")
            if not price:
                validator.add_warning(stage, "Price is empty (may be OK pre-market)")
            if not gap:
                validator.add_warning(stage, "Gap% is empty (may be OK pre-market)")
            if not float_shares:
                validator.add_issue(stage, "Shares Float is empty (critical for screening)")
            if not volume:
                validator.add_warning(stage, "Volume is empty (may be OK pre-market)")
            if not country:
                validator.add_warning(stage, "Country is empty")
            
            # Sample first row
            print(f"\n📋 Sample Row (1st Ticker):")
            print(f"   Ticker: {ticker_sym}")
            print(f"   Price: {price}")
            print(f"   Gap%: {gap}")
            print(f"   Float: {float_shares}M")
            print(f"   Volume: {volume}")
            print(f"   Country: {country}")
            
            return {
                "symbol": ticker_sym,
                "price": price,
                "gap": gap,
                "float": float_shares,
                "volume": volume,
                "country": country,
                "rows": len(rows)
            }
    
    except Exception as e:
        validator.add_issue(stage, f"CSV parse error: {e}")
        return None

def validate_api_keys(env_file, validator):
    """Check if API keys are configured"""
    stage = "3-7: APIs"
    
    if not os.path.exists(env_file):
        validator.add_warning(stage, f".env file not found at {env_file}")
        return
    
    try:
        with open(env_file, 'r') as f:
            env_content = f.read()
        
        required_keys = [
            "ANTHROPIC_API_KEY",
            "POLYGON_API_KEY",
            "FMP_API_KEY",
            "FINNHUB_API_KEY",
            "NEWSAPI_KEY",
        ]
        
        missing_keys = []
        for key in required_keys:
            if key not in env_content or f"{key}=" not in env_content:
                missing_keys.append(key)
        
        if missing_keys:
            validator.add_issue(stage, f"Missing API keys: {missing_keys}")
        else:
            validator.add_pass(stage, f"All {len(required_keys)} required API keys configured")
    
    except Exception as e:
        validator.add_issue(stage, f"Error reading .env: {e}")

def validate_output_structure(reports_dir, validator):
    """Check if reports directory is properly structured"""
    stage = "Output"
    
    if not os.path.exists(reports_dir):
        validator.add_warning(stage, f"Reports directory does not exist: {reports_dir}")
        return
    
    # Check for run subdirectories
    subdirs = [d for d in os.listdir(reports_dir) if os.path.isdir(os.path.join(reports_dir, d))]
    if subdirs:
        validator.add_pass(stage, f"Found {len(subdirs)} run date folders")
        
        # Check latest run
        latest = sorted(subdirs)[-1]
        latest_path = os.path.join(reports_dir, latest)
        run_labels = [d for d in os.listdir(latest_path) if os.path.isdir(os.path.join(latest_path, d))]
        
        if run_labels:
            validator.add_pass(stage, f"Latest date ({latest}) has {len(run_labels)} run(s)")
            
            # Check for required output files
            latest_run = sorted(run_labels)[-1]
            latest_run_path = os.path.join(latest_path, latest_run)
            
            required_outputs = [
                "run_summary.json",
                f"dashboard_{latest}_{latest_run}.html",
            ]
            
            missing_outputs = []
            for output in required_outputs:
                if not os.path.exists(os.path.join(latest_run_path, output)):
                    missing_outputs.append(output)
            
            if missing_outputs:
                validator.add_warning(stage, f"Missing outputs in latest run: {missing_outputs}")
            else:
                validator.add_pass(stage, f"All required outputs present in {latest_run}")
        else:
            validator.add_warning(stage, f"No run folders found in {latest}")

def validate_continuous_runner(launcher_path, validator):
    """Check if continuous runner is configured"""
    stage = "Continuous Runner"
    
    if not os.path.exists(launcher_path):
        validator.add_warning(stage, f"Launcher not found: {launcher_path}")
        return
    
    try:
        with open(launcher_path, 'r') as f:
            launcher_content = f.read()
        
        if "continuous_runner.py" in launcher_content:
            validator.add_pass(stage, "Launcher configured for continuous runner")
        else:
            validator.add_warning(stage, "Launcher may not be calling continuous_runner.py")
    
    except Exception as e:
        validator.add_warning(stage, f"Error reading launcher: {e}")

def main():
    print("\n🔍 Trade AI v12 Pipeline Validator\n")
    
    validator = Validator()
    
    # Test paths (adjust to your actual structure)
    csv_path = "finviz.csv"  # Your upload
    env_file = "assets/.env"
    reports_dir = "reports"
    launcher_path = "launchers/run_continuous.bat"
    
    # Run validations
    print("Checking Finviz CSV...")
    csv_data = validate_finviz_csv(csv_path, validator)
    
    print("\nChecking API Keys...")
    validate_api_keys(env_file, validator)
    
    print("\nChecking Output Structure...")
    validate_output_structure(reports_dir, validator)
    
    print("\nChecking Continuous Runner...")
    validate_continuous_runner(launcher_path, validator)
    
    # Final report
    success = validator.report()
    
    if success:
        print("\n✅ All validations passed!")
    else:
        print("\n⚠️  Some issues found. Review above and fix before running.")
    
    # Recommendations
    print("\n📋 NEXT STEPS:")
    print("  1. If Finviz CSV has all required columns → Data ingestion should work")
    print("  2. If API keys are missing → add them to assets/.env")
    print("  3. Copy the corrected stage_2_finviz_ingestion.py to your scripts/ folder")
    print("  4. Copy the dashboard_generator_v2.py to your scripts/ folder")
    print("  5. Update orchestrator to call: dashboard_generator_v2.py with --output reports/dashboard_live.html")
    print("  6. Test with: python scripts/trade_ai_orchestrator.py --run-label test_0700 --skip-market-check --no-alerts --no-llm")

if __name__ == "__main__":
    main()
