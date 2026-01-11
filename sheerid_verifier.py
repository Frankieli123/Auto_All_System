import requests
import re
import json
import time
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "https://batch.1key.me"
DEFAULT_API_KEY = "0c5cba479e6aa914d66a287d88b15bea"

class SheerIDVerifier:
    def __init__(self, api_key=DEFAULT_API_KEY):
        self.session = requests.Session()
        self.api_key = api_key
        self.csrf_token = None
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/"
        }

    def _get_csrf_token(self):
        """Fetch homepage and extract CSRF token"""
        try:
            logger.info("Fetching CSRF token...")
            resp = self.session.get(BASE_URL, headers=self.headers, timeout=10)
            resp.raise_for_status()
            
            # Regex to find window.CSRF_TOKEN = "..."
            match = re.search(r'window\.CSRF_TOKEN\s*=\s*["\']([^"\']+)["\']', resp.text)
            if match:
                self.csrf_token = match.group(1)
                self.headers["X-CSRF-Token"] = self.csrf_token
                logger.info(f"CSRF Token obtained: {self.csrf_token[:10]}...")
                return True
            else:
                logger.error("CSRF Token pattern not found in page.")
                return False
        except Exception as e:
            logger.error(f"Failed to get CSRF token: {e}")
            return False

    def verify_batch(self, verification_ids, callback=None):
        """
        Verify a batch of IDs (list of strings).
        Returns a dict {verification_id: status_result}
        """
        if not self.csrf_token:
            if not self._get_csrf_token():
                return {vid: {"status": "error", "message": "Failed to get CSRF token"} for vid in verification_ids}

        results = {}
        # Max 5 IDs per batch if API key is present
        # API requires hCaptchaToken to be the API Key for bypass
        
        payload = {
            "verificationIds": verification_ids,
            "hCaptchaToken": self.api_key, 
            "useLucky": False,
            "programId": ""
        }
        
        headers = self.headers.copy()
        headers["Content-Type"] = "application/json"

        try:
            logger.info(f"Submitting batch verification for {len(verification_ids)} IDs...")
            resp = self.session.post(
                f"{BASE_URL}/api/batch", 
                headers=headers, 
                json=payload,
                stream=True,
                timeout=30
            )
            
            # 简单处理：如果返回 403/401 可能是 CSRF 过期，重试一次
            if resp.status_code in [403, 401]:
                logger.warning("Token expired, refreshing...")
                if self._get_csrf_token():
                    headers["X-CSRF-Token"] = self.csrf_token
                    resp = self.session.post(
                        f"{BASE_URL}/api/batch", 
                        headers=headers, 
                        json=payload,
                        stream=True,
                        timeout=30
                    )
                else:
                    return {vid: {"status": "error", "message": "Token expired"} for vid in verification_ids}

            # Parse SSE Stream
            # The API returns "data: {...json...}" lines
            for line in resp.iter_lines():
                if not line: continue
                decoded_line = line.decode('utf-8')
                if decoded_line.startswith("data:"):
                    json_str = decoded_line[5:].strip()
                    try:
                        data = json.loads(json_str)
                        self._handle_api_response(data, results, callback)
                    except json.JSONDecodeError:
                        pass
                        
        except Exception as e:
            logger.error(f"Batch verify request failed: {e}")
            for vid in verification_ids:
                if vid not in results:
                    results[vid] = {"status": "error", "message": str(e)}

        return results

    def _handle_api_response(self, data, results, callback=None):
        """Handle individual data chunks from SSE or poll response"""
        vid = data.get("verificationId")
        if not vid: return

        status = data.get("currentStep")
        message = data.get("message", "")
        
        if callback:
            callback(vid, f"Step: {status} | Msg: {message}")

        if status == "pending" and "checkToken" in data:
            # Need to poll
            check_token = data["checkToken"]
            final_res = self._poll_status(check_token, vid, callback)
            results[vid] = final_res
        elif status == "success" or status == "error":
            # Done
            results[vid] = data

    def _poll_status(self, check_token, vid, callback=None):
        """Poll /api/check-status until success or error"""
        url = f"{BASE_URL}/api/check-status"
        headers = self.headers.copy()
        headers["Content-Type"] = "application/json"
        
        # Poll max 60 times (approx 120s)
        for i in range(60):
            try:
                time.sleep(2) # Wait 2s between polls
                payload = {"checkToken": check_token}
                resp = self.session.post(url, headers=headers, json=payload, timeout=10)
                json_data = resp.json()
                
                status = json_data.get("currentStep")
                message = json_data.get("message", "")
                
                if callback:
                    callback(vid, f"Polling: {status} ({i+1}/60) | Msg: {message}")

                if status == "success" or status == "error":
                    return json_data
                
                # If pending, update checkToken if provided
                if "checkToken" in json_data:
                    check_token = json_data["checkToken"]
                    
            except Exception as e:
                logger.error(f"Polling failed: {e}")
                return {"status": "error", "message": f"Polling exception: {str(e)}"}
        
        return {"status": "error", "message": "Polling timeout (120s)"}

    def cancel_verification(self, verification_id):
        """Cancel a verification process"""
        if not self.csrf_token:
            if not self._get_csrf_token():
                return {"status": "error", "message": "No CSRF Token"}
        
        url = f"{BASE_URL}/api/cancel"
        headers = self.headers.copy()
        headers["X-CSRF-Token"] = self.csrf_token
        headers["Content-Type"] = "application/json"
        
        try:
            resp = self.session.post(url, headers=headers, json={"verificationId": verification_id}, timeout=10)
            try:
                return resp.json()
            except:
                return {"status": "error", "message": f"Invalid JSON: {resp.text}"}
        except Exception as e:
            logger.error(f"Cancel failed: {e}")
            return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    pass
