import httpx
from datetime import datetime
from typing import Optional, Dict, Any, List

class PrometheusService:
    @staticmethod
    async def execute_and_evaluate(
        ds_url: str,
        promql: str,
        start_time: datetime,
        end_time: datetime,
        step: str = "60s",
        min_val: Optional[float] = None,
        max_val: Optional[float] = None,
    ) -> Dict[str, Any]:
        url = f"{ds_url.rstrip('/')}/api/v1/query_range"
        params = {
            "query": promql,
            "start": start_time.timestamp(),
            "end": end_time.timestamp(),
            "step": step,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as e:
            return {"status": "error", "message": f"HTTP error: {e}", "violations": [], "raw_data": []}
        except Exception as e:
            return {"status": "error", "message": str(e), "violations": [], "raw_data": []}

        if data.get("status") != "success":
            return {"status": "error", "message": data.get("error", "Unknown"), "violations": [], "raw_data": []}

        result_matrix = data["data"]["result"]
        violations: List[Dict[str, Any]] = []
        is_success = True

        for series in result_matrix:
            metric_labels = series["metric"]
            for ts, value_str in series["values"]:
                try:
                    value = float(value_str)
                except (ValueError, TypeError):
                    continue

                failed = False
                reason = ""
                if min_val is not None and value < min_val:
                    failed = True
                    reason = f"Value {value:.4f} < min {min_val}"
                if max_val is not None and value > max_val:
                    failed = True
                    reason = f"Value {value:.4f} > max {max_val}"

                if failed:
                    is_success = False
                    violations.append({
                        "labels": metric_labels,
                        "timestamp": ts,
                        "value": value,
                        "reason": reason,
                    })

        return {
            "status": "success" if is_success else "failed",
            "raw_data": result_matrix,
            "violations": violations,
            "total_points": sum(len(s["values"]) for s in result_matrix),
        }

    @staticmethod
    async def check_connection(ds_url: str) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{ds_url.rstrip('/')}/api/v1/status/buildinfo")
                r.raise_for_status()
                data = r.json()
                return {"ok": True, "info": data.get("data", {})}
        except Exception as e:
            return {"ok": False, "error": str(e)}