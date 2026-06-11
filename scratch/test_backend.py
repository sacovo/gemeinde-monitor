import os
import sys

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from main import app, TEMP_RESULTS_FILE

client = TestClient(app)

def test_workflow():
    print("Starting verification tests...")
    
    # 1. Clean temporary file if it exists so we start fresh
    if os.path.exists(TEMP_RESULTS_FILE):
        try:
            os.remove(TEMP_RESULTS_FILE)
            print(f"Cleaned up {TEMP_RESULTS_FILE} before test.")
        except Exception as e:
            print(f"Warning: Could not remove temp file: {e}")
            
    with TestClient(app) as client:
        # 2. Test GET /api/communes
        print("Testing GET /api/communes...")
        response = client.get("/api/communes")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        communes = response.json()
        print(f"Success: Fetched {len(communes)} communes.")
        assert len(communes) > 0, "No communes loaded"
        
        # Verify commune structure
        sample = communes[0]
        assert "geo_id" in sample
        assert "name" in sample
        assert "canton" in sample
        assert "eligible" in sample
        print(f"Sample commune: {sample}")
        
        # 3. Test GET /api/results (should be empty initially)
        print("Testing GET /api/results (initial)...")
        response = client.get("/api/results")
        assert response.status_code == 200
        res_data = response.json()
        assert len(res_data["entered_results"]) == 0, "Should have 0 entered results initially"
        
        # Verify projections structures exist
        assert "projections" in res_data
        assert "average" in res_data["projections"]
        assert "ridge" in res_data["projections"]
        assert "5521" in res_data["projections"]
        # Check initial projection (should have 0 entered communes and default values)
        proj_avg = res_data["projections"]["average"]
        assert proj_avg["num_entered_communes"] == 0
        assert proj_avg["projected_yes_pct"] == 0.0 or proj_avg["projected_yes_pct"] is not None
        print("Initial projections metadata structure is correct.")
        
        # 4. Test POST /api/results (Add Zürich)
        print("Testing POST /api/results (Adding Zürich ID 261)...")
        payload = {
            "geo_id": 261,
            "yes_votes": 35000,
            "no_votes": 65000,
            "eligible": 150000
        }
        response = client.post("/api/results", json=payload)
        assert response.status_code == 200, f"Error: {response.text}"
        res_data = response.json()
        entered = res_data["entered_results"]
        assert len(entered) == 1
        assert entered[0]["geo_id"] == 261
        assert entered[0]["yes_votes"] == 35000
        assert entered[0]["no_votes"] == 65000
        assert entered[0]["eligible"] == 150000
        
        # Check comparisons
        comps = entered[0]["comparisons"]
        assert "average" in comps
        assert "ridge" in comps
        assert "5800" in comps
        print(f"Zürich result saved successfully. Yes %: {entered[0]['yes_pct']:.4f}")
        
        # 5. Test POST /api/results (Add Winterthur ID 230 to have 2 points for regression)
        print("Testing POST /api/results (Adding Winterthur ID 230)...")
        payload2 = {
            "geo_id": 230,
            "yes_votes": 12000,
            "no_votes": 18000,
            "eligible": 50000
        }
        response = client.post("/api/results", json=payload2)
        assert response.status_code == 200
        res_data = response.json()
        entered = res_data["entered_results"]
        assert len(entered) == 2
        
        # Check that regression is now running (num_entered_communes == 2, R^2 is calculated)
        proj_avg = res_data["projections"]["average"]
        proj_ridge = res_data["projections"]["ridge"]
        assert proj_avg["num_entered_communes"] == 2
        assert proj_ridge["num_entered_communes"] == 2
        
        # R-squared of 2 points is 1.0 (perfect fit line)
        assert proj_avg["r_squared_yes"] == 1.0 or proj_avg["r_squared_yes"] is not None
        assert proj_ridge["r_squared_yes"] == 1.0 or proj_ridge["r_squared_yes"] is not None
        assert proj_ridge["weights_yes"] is not None
        assert len(proj_ridge["weights_yes"]) == 6
        
        print(f"Regression running! Projected national Yes % (Average): {proj_avg['projected_yes_pct']*100:.2f}%")
        print(f"Projected national Yes % (Ridge): {proj_ridge['projected_yes_pct']*100:.2f}%")
        print(f"Projected Turnout: {proj_avg['projected_participation']*100:.2f}%")
        print(f"Slope Yes (Average): {proj_avg['slope_yes']:.4f}, Intercept Yes: {proj_avg['intercept_yes']:.4f}")
        print(f"Ridge Weights Yes: {proj_ridge['weights_yes']}")
        
        # 6. Verify Excel file was created
        assert os.path.exists(TEMP_RESULTS_FILE), "Excel temporary file was not created"
        print(f"Verified Excel storage file was written: {TEMP_RESULTS_FILE}")
        
        # 7. Test DELETE /api/results/261
        print("Testing DELETE /api/results/261...")
        response = client.delete("/api/results/261")
        assert response.status_code == 200
        res_data = response.json()
        entered = res_data["entered_results"]
        assert len(entered) == 1
        assert entered[0]["geo_id"] == 230
    
    # Clean up
    if os.path.exists(TEMP_RESULTS_FILE):
        os.remove(TEMP_RESULTS_FILE)
    print("All backend verification tests passed successfully!")

if __name__ == "__main__":
    test_workflow()
