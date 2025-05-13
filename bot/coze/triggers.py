from typing import Any, Dict, List
from config import conf
import requests


class Trigger:
    def __init__(self):
        self.triggers: Dict[str, List] = conf().get("triggers")
        self._base_url = conf().get("coze_api_base")

    def apply(self, matches: List[str]):
        for trigger_name in matches:
            trigger: List[str] or None = self.triggers[trigger_name]
            if trigger:
                hook_token = trigger[0]
                hook_id = trigger[1]
                self._request(hook_token, hook_id)

    def _request(self, h_token: str, h_id: str):
        url = f"{self._base_url}/api/trigger/v1/webhook/biz_id/bot_platform/hook/{h_id}"
        headers: Dict[str, Any] = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {h_token}",
        }
        response = requests.post(url, {}, {}, headers=headers)
        return response
