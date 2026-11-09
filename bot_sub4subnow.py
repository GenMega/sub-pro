from base64 import b64encode
import hashlib
import logging
import random
import sys
import time
from typing import Any, Dict, List, Optional
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)


class Sub4SubClient:
    """Client for interacting with Sub4Sub API, dynamically handling Shorts, Views, Likes, and Comments campaigns."""

    BASE_URL = "https://sub4subnow.com"
    SALT = "hdcstudio@2019"

    # Map campaign modes to their fetch endpoints and required wait durations (seconds)
    CAMPAIGN_TYPES = {
        "shorts": {
            "endpoint": "campaign.getShortViewCampaign",
            "wait_time": 10,
        },
        "views": {
            "endpoint": "campaign.getAllViewCampaignOnly",
            "wait_time": 45,
        },
        "likes": {
            "endpoint": "campaign.getAllViewCampaigns",
            "wait_time": 50,
        },
        "comments": {
            "endpoint": "campaign.getAllCommentCampaigns",
            "wait_time": 30,
        },
    }

    def __init__(
        self,
        user_id: str,
        access_token: str,
        middle_key: str,
        channel_name: str,
        country: str = "IN",
        version: str = "130",
    ):
        self.user_id = user_id
        self.access_token = access_token
        self.middle_key = middle_key
        self.channel_name = channel_name
        self.country = country
        self.version = version

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Dalvik/2.1.0 (Linux; U; Android 10; Build/RP1A.200720.011)"
            ),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Encoding": "gzip",
        })

    def _generate_checksum(self, millis: str) -> str:
        """Computes MD5 checksum required by server."""
        raw_payload = f"{self.SALT}{self.middle_key}{millis}"
        return hashlib.md5(raw_payload.encode("utf-8")).hexdigest()

    def _post(
        self, endpoint: str, data: Dict[str, Any], timeout: int = 15
    ) -> Optional[Dict[str, Any]]:
        """Helper method to handle POST requests."""
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            response = self.session.post(url, data=data, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as err:
            logging.error(f"HTTP Request failed for {endpoint}: {err}")
        except ValueError:
            logging.error(f"Failed to parse JSON response from {endpoint}")
        return None

    def fetch_campaign(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """Fetches a campaign using the specified type endpoint."""
        payload = {
            "country": self.country,
            "maxResult": "1",
            "lastCampaignId": "2147483647",
            "orderBy": "0",
            "accessToken": self.access_token,
            "userId": self.user_id,
            "version": self.version,
            "channelId": "",
        }
        res = self._post(endpoint, payload)
        if res and res.get("success") and res.get("campaigns"):
            return res["campaigns"][0]
        return None

    def update_progress(self, campaign_id: str) -> bool:
        """Notifies server that viewing/interacting has started."""
        logging.info(f"Updating progress for Campaign ID: {campaign_id}")
        millis = str(int(time.time() * 1000))
        checksum = self._generate_checksum(millis)

        payload = {
            "campaignId": campaign_id,
            "checksum": checksum,
            "channelName": self.channel_name,
            "accessToken": self.access_token,
            "millis": millis,
            "thumbUrl": "",
            "userId": self.user_id,
            "version": self.version,
            "channelId": "",
            "isVip": "0",
        }
        res = self._post("campaign.updateCampaignProgress", payload)
        return bool(res and res.get("success"))

    def claim_reward(self, campaign_id: str) -> Optional[Dict[str, Any]]:
        """Claims reward points upon task completion."""
        logging.info(f"Claiming reward for Campaign ID: {campaign_id}")
        millis = str(int(time.time() * 1000))
        checksum = self._generate_checksum(millis)

        payload = {
            "campaignId": campaign_id,
            "checksum": checksum,
            "channelName": self.channel_name,
            "accessToken": self.access_token,
            "millis": millis,
            "thumbUrl": "",
            "userId": self.user_id,
            "version": self.version,
            "channelId": "",
            "isVip": "0",
        }
        return self._post("campaign.subOrView", payload)

    def execute_cycle(self) -> bool:
        """Randomly selects a campaign mode and falls back if unavailable."""
        available_modes = list(self.CAMPAIGN_TYPES.keys())
        random.shuffle(available_modes)

        campaign = None
        selected_mode = None

        for mode in available_modes:
            logging.info(f"Attempting to fetch target for mode: [{mode.upper()}]...")
            endpoint = self.CAMPAIGN_TYPES[mode]["endpoint"]
            campaign = self.fetch_campaign(endpoint)
            if campaign:
                selected_mode = mode
                break
            logging.warning(f"No active campaign available for mode [{mode.upper()}].")

        if not campaign or not selected_mode:
            logging.error("No active campaigns found across any campaign mode.")
            return False

        campaign_id = campaign["campaignId"]
        wait_time = self.CAMPAIGN_TYPES[selected_mode]["wait_time"]

        logging.info(
            f"Campaign target acquired! Mode: [{selected_mode.upper()}] | ID: {campaign_id} | Video: {campaign.get('videoId')}"
        )

        if not self.update_progress(campaign_id):
            logging.error("Progress update rejected by server.")
            return False

        logging.info(f"Waiting {wait_time} seconds (required view duration for {selected_mode})...")
        time.sleep(wait_time)

        reward_response = self.claim_reward(campaign_id)
        if reward_response and reward_response.get("success"):
            points = reward_response.get("point", "Unknown")
            logging.info(f"Success! Reward claimed for [{selected_mode.upper()}]. Total Points: {points}")
            return True
        else:
            logging.error(f"Failed to claim reward: {reward_response}")
            return False

    def run_infinite_loop(self, delay_between_runs: int = 5):
        """Runs continuously with auto-recovery, exiting safely before GitHub's 6-hour limit."""
        logging.info("Starting Sub4SubNow Continuous Bot Runner (24x7 Mode)...")
        start_time = time.time()
        
        # Safe limit: 5 hours 5 minutes (well within GitHub's 6-hour max timeout)
        MAX_RUN_TIME = 5 * 3600 + 300 

        while True:
            if time.time() - start_time > MAX_RUN_TIME:
                logging.info("Reached safe runtime limit (~5h 5m). Exiting cleanly for workflow self-restart...")
                sys.exit(0)

            try:
                success = self.execute_cycle()
                if not success:
                    logging.warning("Cycle unsuccessful. Backing off for 15 seconds...")
                    time.sleep(15)
                else:
                    time.sleep(delay_between_runs)
            except Exception as e:
                logging.error(f"Unexpected error in run loop: {e}. Auto-recovering in 10s...")
                time.sleep(10)


if __name__ == "__main__":
    CONFIG = {
        "user_id": "4508799",
        "access_token": "0e3f3cea504bdf210dda125e0e1ed2e4",
        "middle_key": "308203873054432be004",
        "channel_name": "justakali2@gmail.com",
    }

    client = Sub4SubClient(**CONFIG)
    client.run_infinite_loop(delay_between_runs=5)
