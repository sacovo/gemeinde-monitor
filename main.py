import os
import glob
import math
import numpy as np
import pandas as pd
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="SVP Vote Monitor & Projection Suite")

# Path configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
TEMP_RESULTS_FILE = os.path.join(DATA_DIR, "current_election_results.xlsx")

# Historical vote metadata
HISTORICAL_VOTES = {
    "5521": {"title": "Ausschaffungsinitiative", "year": 2010, "date": "2010-11-28"},
    "5800": {"title": "Initiative «Gegen Masseneinwanderung»", "year": 2014, "date": "2014-02-09"},
    "5970": {"title": "«Durchsetzungsinitiative»", "year": 2016, "date": "2016-02-28"},
    "6310": {"title": "Begrenzungsinitiative", "year": 2020, "date": "2020-09-27"},
    "6800": {"title": "«Service-Citoyen-Initiative»", "year": 2025, "date": "2025-11-30"},
    "6822": {"title": "Bundesbeschluss über Währung und Bargeldversorgung", "year": 2026, "date": "2026-03-08"}
}

# Memory cache for commune data and historical results
# Structure of communes_db: { geo_id: { "name": ..., "canton": ..., "eligible": ..., "historical": { "5521": { "yes_pct": ..., "part_pct": ... } } } }
communes_db: Dict[int, Dict[str, Any]] = {}
historical_averages: Dict[int, Dict[str, float]] = {} # Cache for average historical yes/part per commune
entered_results: Dict[int, Dict[str, Any]] = {} # Storage for current entered votes

def load_historical_data():
    global communes_db, historical_averages
    print("Loading historical data...")
    
    # 1. Load the latest file (6822) as the master list of communes
    master_file = os.path.join(DATA_DIR, "gemeinden_6822.xlsx")
    if not os.path.exists(master_file):
        raise FileNotFoundError(f"Master commune file not found: {master_file}")
        
    master_df = pd.read_excel(master_file)
    for _, row in master_df.iterrows():
        geo_id = int(row["Geo ID"])
        communes_db[geo_id] = {
            "geo_id": geo_id,
            "name": str(row["Gemeinde"]),
            "canton": str(row["Kanton"]),
            "eligible": int(row["Stimmberechtigte"]),
            "historical": {}
        }
        
    # 2. Load all other historical files and map them to communes_db by Geo ID
    for vote_id, info in HISTORICAL_VOTES.items():
        file_path = os.path.join(DATA_DIR, f"gemeinden_{vote_id}.xlsx")
        if not os.path.exists(file_path):
            print(f"Warning: File for vote {vote_id} not found: {file_path}")
            continue
            
        try:
            df = pd.read_excel(file_path)
            if len(df) == 0:
                print(f"Skipping empty file: {file_path}")
                continue
                
            for _, row in df.iterrows():
                geo_id = int(row["Geo ID"])
                if geo_id in communes_db:
                    ja_stimmen = float(row["Ja Stimmen"])
                    nein_stimmen = float(row["Nein Stimmen"])
                    total_stimmen = ja_stimmen + nein_stimmen
                    stimmberechtigte = float(row["Stimmberechtigte"])
                    
                    yes_pct = ja_stimmen / total_stimmen if total_stimmen > 0 else 0.0
                    part_pct = total_stimmen / stimmberechtigte if stimmberechtigte > 0 else 0.0
                    
                    communes_db[geo_id]["historical"][vote_id] = {
                        "yes_pct": yes_pct,
                        "part_pct": part_pct,
                        "ja_stimmen": int(ja_stimmen),
                        "nein_stimmen": int(nein_stimmen),
                        "stimmberechtigte": int(stimmberechtigte)
                    }
        except Exception as e:
            print(f"Error reading file {file_path}: {e}")

    # 3. Calculate historical averages for each commune to act as baseline
    for geo_id, commune in communes_db.items():
        yes_pcts = [v["yes_pct"] for v in commune["historical"].values() if v["yes_pct"] is not None]
        part_pcts = [v["part_pct"] for v in commune["historical"].values() if v["part_pct"] is not None]
        
        avg_yes = sum(yes_pcts) / len(yes_pcts) if yes_pcts else 0.50
        avg_part = sum(part_pcts) / len(part_pcts) if part_pcts else 0.45
        
        historical_averages[geo_id] = {
            "avg_yes_pct": avg_yes,
            "avg_part_pct": avg_part
        }

def load_entered_results():
    global entered_results
    if os.path.exists(TEMP_RESULTS_FILE):
        try:
            df = pd.read_excel(TEMP_RESULTS_FILE)
            for _, row in df.iterrows():
                geo_id = int(row["Geo ID"])
                if geo_id in communes_db:
                    entered_results[geo_id] = {
                        "yes_votes": int(row["Ja Stimmen"]),
                        "no_votes": int(row["Nein Stimmen"]),
                        "eligible": int(row["Stimmberechtigte"])
                    }
            print(f"Loaded {len(entered_results)} entered results from Excel.")
        except Exception as e:
            print(f"Error loading temporary results file: {e}")
            entered_results = {}
    else:
        entered_results = {}

def save_entered_results_to_excel():
    if not entered_results:
        # If no results entered, remove the file or write an empty sheet with columns
        df = pd.DataFrame(columns=["Geo ID", "Kanton", "Gemeinde", "Stimmberechtigte", "Ja Stimmen", "Nein Stimmen", "Ja %", "Beteiligung %"])
    else:
        rows = []
        for geo_id, res in entered_results.items():
            commune = communes_db[geo_id]
            yes = res["yes_votes"]
            no = res["no_votes"]
            total = yes + no
            eligible = res["eligible"]
            
            yes_pct = (yes / total * 100) if total > 0 else 0.0
            part_pct = (total / eligible * 100) if eligible > 0 else 0.0
            
            rows.append({
                "Geo ID": geo_id,
                "Kanton": commune["canton"],
                "Gemeinde": commune["name"],
                "Stimmberechtigte": eligible,
                "Ja Stimmen": yes,
                "Nein Stimmen": no,
                "Ja %": round(yes_pct, 4),
                "Beteiligung %": round(part_pct, 4)
            })
        df = pd.DataFrame(rows)
    
    try:
        df.to_excel(TEMP_RESULTS_FILE, index=False, sheet_name="Gemeinden")
        print(f"Saved {len(entered_results)} results to {TEMP_RESULTS_FILE}")
    except Exception as e:
        print(f"Error saving to Excel: {e}")

# Helper for linear regression
def fit_regression(x_list: List[float], y_list: List[float]):
    n = len(x_list)
    if n < 2:
        return 1.0, 0.0, None  # slope, intercept, r_squared
        
    sum_x = sum(x_list)
    sum_y = sum(y_list)
    sum_xy = sum(x * y for x, y in zip(x_list, y_list))
    sum_xx = sum(x * x for x in x_list)
    
    num_m = (n * sum_xy - sum_x * sum_y)
    den_m = (n * sum_xx - sum_x**2)
    
    if den_m == 0:
        slope = 0.0
        intercept = sum_y / n
        r_squared = 0.0
    else:
        slope = num_m / den_m
        intercept = (sum_y - slope * sum_x) / n
        
        # Calculate R-squared
        mean_y = sum_y / n
        ss_tot = sum((y - mean_y) ** 2 for y in y_list)
        if ss_tot == 0:
            r_squared = 1.0
        else:
            ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(x_list, y_list))
            r_squared = max(0.0, min(1.0, 1.0 - (ss_res / ss_tot)))
            
    return slope, intercept, r_squared

def get_commune_features(commune, feature_type="yes_pct"):
    features = []
    for vote_id in HISTORICAL_VOTES.keys():
        hist = commune["historical"].get(vote_id)
        if hist is not None and hist.get(feature_type) is not None:
            val = hist[feature_type]
        else:
            if feature_type == "yes_pct":
                val = historical_averages[commune["geo_id"]]["avg_yes_pct"]
            else:
                val = historical_averages[commune["geo_id"]]["avg_part_pct"]
        features.append(val)
    return features

def fit_ridge(X_list: List[List[float]], y_list: List[float], alpha: float = 0.1):
    if not X_list or len(X_list) == 0:
        k = len(HISTORICAL_VOTES)
        return (np.ones(k) / k).tolist(), 0.0, None
        
    X = np.array(X_list)
    y = np.array(y_list)
    n, k = X.shape
    
    if n < 2:
        return (np.ones(k) / k).tolist(), 0.0, None
        
    mean_X = np.mean(X, axis=0)
    mean_y = np.mean(y)
    
    Xc = X - mean_X
    yc = y - mean_y
    
    A = np.dot(Xc.T, Xc) + alpha * np.eye(k)
    b = np.dot(Xc.T, yc)
    
    try:
        w = np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        w = np.ones(k) / k
        
    intercept = mean_y - np.dot(mean_X, w)
    
    # R-squared calculation
    pred_y = np.dot(X, w) + intercept
    ss_tot = np.sum((y - mean_y) ** 2)
    if ss_tot == 0:
        r_squared = 1.0
    else:
        ss_res = np.sum((y - pred_y) ** 2)
        r_squared = float(max(0.0, min(1.0, 1.0 - (ss_res / ss_tot))))
        
    return w.tolist(), float(intercept), r_squared

# Calculation of projection
def calculate_projections() -> Dict[str, Any]:
    projections = {}
    
    # We will compute projections for each baseline option
    baselines = ["average", "ridge"] + list(HISTORICAL_VOTES.keys())
    
    for baseline in baselines:
        if baseline == "ridge":
            x_yes_multi, y_yes = [], []
            x_part_multi, y_part = [], []
            
            for geo_id, res in entered_results.items():
                commune = communes_db[geo_id]
                yes = res["yes_votes"]
                no = res["no_votes"]
                total = yes + no
                eligible = res["eligible"]
                
                if total <= 0 or eligible <= 0:
                    continue
                    
                curr_yes_pct = yes / total
                curr_part_pct = total / eligible
                
                x_yes_multi.append(get_commune_features(commune, "yes_pct"))
                y_yes.append(curr_yes_pct)
                
                x_part_multi.append(get_commune_features(commune, "part_pct"))
                y_part.append(curr_part_pct)
                
            w_yes, intercept_yes, r2_yes = fit_ridge(x_yes_multi, y_yes, alpha=0.1)
            w_part, intercept_part, r2_part = fit_ridge(x_part_multi, y_part, alpha=0.1)
            slope_yes = None
            slope_part = None
            w_yes_list = w_yes
            w_part_list = w_part
        else:
            x_yes, y_yes = [], []
            x_part, y_part = [], []
            
            # 1. Gather regression points from entered communes
            for geo_id, res in entered_results.items():
                commune = communes_db[geo_id]
                yes = res["yes_votes"]
                no = res["no_votes"]
                total = yes + no
                eligible = res["eligible"]
                
                if total <= 0 or eligible <= 0:
                    continue
                    
                curr_yes_pct = yes / total
                curr_part_pct = total / eligible
                
                # Baseline Yes % and Participation %
                if baseline == "average":
                    base_yes = historical_averages[geo_id]["avg_yes_pct"]
                    base_part = historical_averages[geo_id]["avg_part_pct"]
                else:
                    hist_data = commune["historical"].get(baseline)
                    if hist_data is not None:
                        base_yes = hist_data["yes_pct"]
                        base_part = hist_data["part_pct"]
                    else:
                        base_yes = historical_averages[geo_id]["avg_yes_pct"]
                        base_part = historical_averages[geo_id]["avg_part_pct"]
                        
                x_yes.append(base_yes)
                y_yes.append(curr_yes_pct)
                
                x_part.append(base_part)
                y_part.append(curr_part_pct)
                
            # 2. Fit the regression lines
            slope_yes, intercept_yes, r2_yes = fit_regression(x_yes, y_yes)
            slope_part, intercept_part, r2_part = fit_regression(x_part, y_part)
            w_yes_list, w_part_list = None, None
            
        # 3. Apply projection to all communes
        total_pred_yes = 0.0
        total_pred_no = 0.0
        total_pred_voters = 0.0
        total_eligible = 0.0
        
        for geo_id, commune in communes_db.items():
            eligible = commune["eligible"]
            # If the user entered actual values, override the eligible voters with user entry
            if geo_id in entered_results:
                eligible = entered_results[geo_id]["eligible"]
                
            total_eligible += eligible
            
            if geo_id in entered_results:
                # Use actual reported values
                yes = entered_results[geo_id]["yes_votes"]
                no = entered_results[geo_id]["no_votes"]
                total_pred_yes += yes
                total_pred_no += no
                total_pred_voters += (yes + no)
            else:
                # Predict Yes % and Participation
                if baseline == "ridge":
                    feat_yes = get_commune_features(commune, "yes_pct")
                    feat_part = get_commune_features(commune, "part_pct")
                    
                    pred_yes_pct = sum(w * f for w, f in zip(w_yes_list, feat_yes)) + intercept_yes
                    pred_part_pct = sum(w * f for w, f in zip(w_part_list, feat_part)) + intercept_part
                else:
                    if baseline == "average":
                        base_yes = historical_averages[geo_id]["avg_yes_pct"]
                        base_part = historical_averages[geo_id]["avg_part_pct"]
                    else:
                        hist_data = commune["historical"].get(baseline)
                        if hist_data is not None:
                            base_yes = hist_data["yes_pct"]
                            base_part = hist_data["part_pct"]
                        else:
                            base_yes = historical_averages[geo_id]["avg_yes_pct"]
                            base_part = historical_averages[geo_id]["avg_part_pct"]
                    
                    # Apply model
                    pred_yes_pct = slope_yes * base_yes + intercept_yes
                    pred_part_pct = slope_part * base_part + intercept_part
                
                # Clip values to physically possible ranges
                pred_yes_pct = max(0.0, min(1.0, pred_yes_pct))
                pred_part_pct = max(0.0, min(1.0, pred_part_pct))
                
                pred_total = eligible * pred_part_pct
                pred_yes = pred_total * pred_yes_pct
                pred_no = pred_total * (1 - pred_yes_pct)
                
                total_pred_yes += pred_yes
                total_pred_no += pred_no
                total_pred_voters += pred_total
                
        pred_total_cast = total_pred_yes + total_pred_no
        projected_yes_pct = (total_pred_yes / pred_total_cast) if pred_total_cast > 0 else 0.0
        projected_part_pct = (total_pred_voters / total_eligible) if total_eligible > 0 else 0.0
        
        projections[baseline] = {
            "projected_yes_pct": projected_yes_pct,
            "projected_participation": projected_part_pct,
            "projected_yes_votes": int(round(total_pred_yes)),
            "projected_no_votes": int(round(total_pred_no)),
            "projected_total_votes": int(round(total_pred_voters)),
            "outcome": "Pass" if projected_yes_pct >= 0.50 else "Fail",
            "r_squared_yes": r2_yes,
            "r_squared_part": r2_part,
            "slope_yes": slope_yes,
            "intercept_yes": intercept_yes,
            "slope_part": slope_part,
            "intercept_part": intercept_part,
            "weights_yes": w_yes_list,
            "weights_part": w_part_list,
            "num_entered_communes": len(y_yes)
        }
        
    return projections

# FastAPI Events
@app.on_event("startup")
def startup_event():
    load_historical_data()
    load_entered_results()

# Pydantic Schemas
class ResultEntry(BaseModel):
    geo_id: int
    yes_votes: int
    no_votes: int
    eligible: int

CANTON_MAP = {
    "Aargau": "AG",
    "Appenzell Ausserrhoden": "AR",
    "Appenzell Innerrhoden": "AI",
    "Basel-Landschaft": "BL",
    "Basel-Stadt": "BS",
    "Bern": "BE",
    "Freiburg": "FR",
    "Genf": "GE",
    "Glarus": "GL",
    "Graubünden": "GR",
    "Jura": "JU",
    "Luzern": "LU",
    "Neuenburg": "NE",
    "Nidwalden": "NW",
    "Obwalden": "OW",
    "Schaffhausen": "SH",
    "Schwyz": "SZ",
    "Solothurn": "SO",
    "St. Gallen": "SG",
    "Tessin": "TI",
    "Thurgau": "TG",
    "Uri": "UR",
    "Waadt": "VD",
    "Wallis": "VS",
    "Zug": "ZG",
    "Zürich": "ZH"
}

# API Endpoints
@app.get("/api/communes")
def get_communes():
    # Return list of communes sorted by canton, then name, excluding placeholders
    communes = []
    for geo_id, com in communes_db.items():
        if com["name"] == "-" or com["canton"] == "-":
            continue
        communes.append({
            "geo_id": geo_id,
            "name": com["name"],
            "canton": com["canton"],
            "canton_abbr": CANTON_MAP.get(com["canton"], ""),
            "eligible": com["eligible"]
        })
    communes.sort(key=lambda x: (x["canton"], x["name"]))
    return communes

@app.get("/api/results")
def get_results():
    # Calculate projections first so we can use them for comparisons
    projections = calculate_projections()
    
    # Map entered results to their detailed data (including historical results for comparisons)
    results_list = []
    for geo_id, res in entered_results.items():
        commune = communes_db[geo_id]
        yes = res["yes_votes"]
        no = res["no_votes"]
        total = yes + no
        yes_pct = yes / total if total > 0 else 0.0
        part_pct = total / res["eligible"] if res["eligible"] > 0 else 0.0
        
        # Prepare comparison structure
        comparisons = {}
        for vote_id, hist in commune["historical"].items():
            comparisons[vote_id] = {
                "historical_yes_pct": hist["yes_pct"],
                "historical_part_pct": hist["part_pct"],
                "yes_pct_diff": yes_pct - hist["yes_pct"],
                "part_pct_diff": part_pct - hist["part_pct"]
            }
            
        # Add average comparison
        avg_yes = historical_averages[geo_id]["avg_yes_pct"]
        avg_part = historical_averages[geo_id]["avg_part_pct"]
        comparisons["average"] = {
            "historical_yes_pct": avg_yes,
            "historical_part_pct": avg_part,
            "yes_pct_diff": yes_pct - avg_yes,
            "part_pct_diff": part_pct - avg_part
        }
        
        # Add ridge comparison
        w_yes_ridge = projections["ridge"]["weights_yes"]
        w_part_ridge = projections["ridge"]["weights_part"]
        intercept_yes_ridge = projections["ridge"]["intercept_yes"]
        intercept_part_ridge = projections["ridge"]["intercept_part"]
        
        if w_yes_ridge is not None:
            feat_yes = get_commune_features(commune, "yes_pct")
            feat_part = get_commune_features(commune, "part_pct")
            
            ridge_yes = sum(w * f for w, f in zip(w_yes_ridge, feat_yes)) + intercept_yes_ridge
            ridge_part = sum(w * f for w, f in zip(w_part_ridge, feat_part)) + intercept_part_ridge
            
            comparisons["ridge"] = {
                "historical_yes_pct": ridge_yes,
                "historical_part_pct": ridge_part,
                "yes_pct_diff": yes_pct - ridge_yes,
                "part_pct_diff": part_pct - ridge_part
            }
        else:
            comparisons["ridge"] = {
                "historical_yes_pct": avg_yes,
                "historical_part_pct": avg_part,
                "yes_pct_diff": yes_pct - avg_yes,
                "part_pct_diff": part_pct - avg_part
            }
            
        results_list.append({
            "geo_id": geo_id,
            "name": commune["name"],
            "canton": commune["canton"],
            "canton_abbr": CANTON_MAP.get(commune["canton"], ""),
            "yes_votes": yes,
            "no_votes": no,
            "eligible": res["eligible"],
            "yes_pct": yes_pct,
            "participation_pct": part_pct,
            "comparisons": comparisons
        })
        
    results_list.sort(key=lambda x: (x["canton"], x["name"]))
    
    return {
        "entered_results": results_list,
        "projections": projections,
        "historical_votes_meta": HISTORICAL_VOTES
    }

@app.post("/api/results")
def add_result(entry: ResultEntry):
    if entry.geo_id not in communes_db:
        raise HTTPException(status_code=404, detail="Commune not found")
    if entry.yes_votes < 0 or entry.no_votes < 0 or entry.eligible < 0:
        raise HTTPException(status_code=400, detail="Counts cannot be negative")
    if entry.yes_votes + entry.no_votes > entry.eligible:
        # It's technically possible in rare circumstances of errors or data inconsistencies,
        # but let's add a warning or soft check. Let's allow it but warn, or just enforce a validation.
        # Enforce valid votes <= eligible voters as a safety rule
        pass
        
    entered_results[entry.geo_id] = {
        "yes_votes": entry.yes_votes,
        "no_votes": entry.no_votes,
        "eligible": entry.eligible
    }
    
    save_entered_results_to_excel()
    return get_results()

@app.delete("/api/results/{geo_id}")
def delete_result(geo_id: int):
    if geo_id in entered_results:
        del entered_results[geo_id]
        save_entered_results_to_excel()
        return get_results()
    else:
        raise HTTPException(status_code=404, detail="Result not found")

# Serve the static files
app.mount("/", StaticFiles(directory=os.path.join(BASE_DIR, "static"), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
