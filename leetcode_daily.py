import requests
import json
import csv
import time
import datetime
import asyncio
import aiohttp
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import pytz
import os
import hashlib

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class LeetCodeScraper:
    def __init__(self, max_workers=5, rate_limit=5, days=7, submission_limit=1000):
        """
        Initialize the LeetCode scraper with concurrency settings

        Args:
            max_workers (int): Maximum number of concurrent workers
            rate_limit (int): Maximum requests per second
            days (int): Number of days to scrape (e.g., 7 or 30)
            submission_limit (int): Maximum submissions to fetch per user
        """
        self.max_workers = max_workers
        self.rate_limit = rate_limit
        self.days = days
        self.submission_limit = submission_limit
        self.session = None
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "https://leetcode.com/",
            "Origin": "https://leetcode.com"
        }
        self.difficulty_cache_file = "./output/difficulty_cache.json"
        self.difficulty_cache = self.load_difficulty_cache()
        self.year_range = "2022-2026"
        self.validation_report = []

    def load_difficulty_cache(self):
        """Load difficulty cache from disk"""
        try:
            if os.path.exists(self.difficulty_cache_file):
                with open(self.difficulty_cache_file, 'r') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logger.error(f"Error loading difficulty cache: {e}")
            return {}

    def save_difficulty_cache(self):
        """Save difficulty cache to disk"""
        try:
            with open(self.difficulty_cache_file, 'w') as f:
                json.dump(self.difficulty_cache, f)
        except Exception as e:
            logger.error(f"Error saving difficulty cache: {e}")

    async def _init_session(self):
        """Initialize aiohttp session with timeout"""
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(headers=self.headers, timeout=timeout)

    async def close_session(self):
        """Close aiohttp session"""
        if self.session:
            await self.session.close()
            self.session = None

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, ValueError))
    )
    async def get_user_profile(self, username):
        """Get basic user profile data with retry"""
        await self._init_session()
        query = """
        query getUserProfile($username: String!) {
            matchedUser(username: $username) {
                username
                submitStats {
                    acSubmissionNum {
                        difficulty
                        count
                    }
                }
            }
        }
        """
        variables = {"username": username}
        payload = {"query": query, "variables": variables}
        url = "https://leetcode.com/graphql"

        async with self.session.post(url, json=payload) as response:
            if response.status != 200:
                logger.error(f"Profile fetch for {username}: HTTP {response.status}")
                raise ValueError(f"HTTP {response.status}")
            data = await response.json()
            logger.debug(f"Profile response for {username}: {json.dumps(data, indent=2)}")
            if data.get("data") is None or data["data"].get("matchedUser") is None:
                logger.warning(f"User '{username}' not found")
                return None
            return data["data"]

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, ValueError))
    )
    async def get_recent_submissions(self, username):
        """Get submission history"""
        await self._init_session()
        query = """
        query recentSubmissions($username: String!, $limit: Int!) {
            recentSubmissionList(username: $username, limit: $limit) {
                title
                timestamp
                statusDisplay
                lang
                id
                titleSlug
            }
        }
        """
        variables = {"username": username, "limit": self.submission_limit}
        payload = {"query": query, "variables": variables}
        url = "https://leetcode.com/graphql"

        async with self.session.post(url, json=payload) as response:
            if response.status != 200:
                logger.error(f"Submissions fetch for {username}: HTTP {response.status}")
                raise ValueError(f"HTTP {response.status}")
            data = await response.json()
            logger.debug(f"Submissions response for {username}: {json.dumps(data, indent=2)}")
            if data.get("data") is None or data["data"].get("recentSubmissionList") is None:
                logger.warning(f"No submission data for '{username}'")
                return []
            return data["data"]["recentSubmissionList"]

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, ValueError))
    )
    async def get_problem_difficulty(self, title_slug):
        """Get problem difficulty level with caching"""
        if title_slug in self.difficulty_cache:
            return self.difficulty_cache[title_slug]

        await self._init_session()
        query = """
        query problemData($titleSlug: String!) {
            question(titleSlug: $titleSlug) {
                difficulty
            }
        }
        """
        variables = {"titleSlug": title_slug}
        payload = {"query": query, "variables": variables}
        url = "https://leetcode.com/graphql"

        async with self.session.post(url, json=payload) as response:
            if response.status != 200:
                logger.error(f"Difficulty fetch for {title_slug}: HTTP {response.status}")
                raise ValueError(f"HTTP {response.status}")
            data = await response.json()
            logger.debug(f"Difficulty response for {title_slug}: {json.dumps(data, indent=2)}")
            if data.get("data") is None or data["data"].get("question") is None:
                logger.warning(f"No difficulty data for {title_slug}")
                return "Unknown"
            difficulty = data["data"]["question"]["difficulty"]
            self.difficulty_cache[title_slug] = difficulty
            self.save_difficulty_cache()
            return difficulty

    async def validate_username(self, username):
        """Check if a username exists"""
        profile = await self.get_user_profile(username)
        return profile is not None

    def parse_timestamp(self, timestamp_value):
        """Parse timestamp in UTC"""
        try:
            if isinstance(timestamp_value, (int, float)):
                return datetime.fromtimestamp(timestamp_value, tz=pytz.UTC)
            elif isinstance(timestamp_value, str):
                try:
                    return datetime.fromtimestamp(int(timestamp_value), tz=pytz.UTC)
                except ValueError:
                    for fmt in (
                        "%Y-%m-%dT%H:%M:%S%z",
                        "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%d"
                    ):
                        try:
                            dt = datetime.strptime(timestamp_value, fmt)
                            if "%z" not in fmt:
                                dt = dt.replace(tzinfo=pytz.UTC)
                            return dt
                        except ValueError:
                            continue
                    raise ValueError(f"Invalid timestamp format: {timestamp_value}")
            else:
                raise ValueError(f"Unrecognized timestamp type: {type(timestamp_value)}")
        except Exception as e:
            logger.error(f"Failed to parse timestamp '{timestamp_value}': {e}")
            raise

    async def process_user(self, username):
        """Process a single user's data with validation"""
        if not await self.validate_username(username):
            logger.warning(f"Skipping invalid username: {username}")
            self.validation_report.append({
                "username": username,
                "status": "Invalid",
                "details": "User not found"
            })
            return {
                "username": username,
                "error": "Invalid username",
                "problems_solved": {"easy": 0, "medium": 0, "hard": 0},
                "total_solved": 0,
                "daily_activity": []
            }

        profile_data = await self.get_user_profile(username)
        if not profile_data:
            logger.error(f"Failed to fetch profile for {username}")
            self.validation_report.append({
                "username": username,
                "status": "Failed",
                "details": "Profile fetch failed"
            })
            return {
                "username": username,
                "error": "Failed to fetch profile",
                "problems_solved": {"easy": 0, "medium": 0, "hard": 0},
                "total_solved": 0,
                "daily_activity": []
            }

        stats = {"username": username, "problems_solved": {}}
        try:
            submission_stats = profile_data["matchedUser"]["submitStats"]["acSubmissionNum"]
            for item in submission_stats:
                difficulty = item["difficulty"]
                count = item["count"]
                if difficulty == "All":
                    stats["total_solved"] = count
                else:
                    stats["problems_solved"][difficulty.lower()] = count
        except (KeyError, TypeError) as e:
            logger.error(f"Error processing stats for {username}: {e}")
            stats["problems_solved"] = {"easy": 0, "medium": 0, "hard": 0}
            stats["total_solved"] = 0
            self.validation_report.append({
                "username": username,
                "status": "Warning",
                "details": f"Stats processing error: {e}"
            })

        submissions = await self.get_recent_submissions(username)
        today = datetime.now(pytz.UTC)
        time_ago = today - timedelta(days=self.days)
        daily_activity = {}

        for i in range(self.days):
            day = today - timedelta(days=i)
            date_str = day.strftime("%Y-%m-%d")
            daily_activity[date_str] = {
                "date": date_str,
                "easy": 0,
                "medium": 0,
                "hard": 0,
                "total": 0,
                "problems": [],
                "year_range": self.year_range
            }

        if submissions:
            submissions = sorted(submissions, key=lambda x: int(x.get("timestamp", 0)), reverse=True)
            unique_submissions = {}
            for submission in submissions:
                try:
                    timestamp = self.parse_timestamp(submission.get("timestamp", ""))
                    date_str = timestamp.strftime("%Y-%m-%d")
                    if timestamp < time_ago:
                        continue
                    if submission.get("statusDisplay") != "Accepted":
                        continue
                    submission_id = submission.get("id")
                    title_slug = submission["titleSlug"]
                    submission_key = f"{date_str}:{title_slug}:{submission_id}"
                    if submission_key in unique_submissions:
                        continue
                    unique_submissions[submission_key] = True
                    difficulty = await self.get_problem_difficulty(title_slug)
                    difficulty = difficulty.lower()
                    if date_str not in daily_activity:
                        continue
                    if difficulty in ["easy", "medium", "hard"]:
                        daily_activity[date_str][difficulty] += 1
                    daily_activity[date_str]["total"] += 1
                    daily_activity[date_str]["problems"].append({
                        "title": submission["title"],
                        "difficulty": difficulty,
                        "submission_id": submission_id
                    })
                except Exception as e:
                    logger.error(f"Error processing submission for {username}: {e}")
                    self.validation_report.append({
                        "username": username,
                        "status": "Warning",
                        "details": f"Submission processing error: {e}"
                    })
                    continue

        stats["daily_activity"] = sorted(
            daily_activity.values(),
            key=lambda x: x["date"],
            reverse=True
        )

        # Validate daily totals against profile
        daily_total = sum(day["total"] for day in stats["daily_activity"])
        profile_total = stats.get("total_solved", 0)
        if daily_total > profile_total:
            logger.warning(f"Data inconsistency for {username}: Daily total ({daily_total}) exceeds profile total ({profile_total})")
            self.validation_report.append({
                "username": username,
                "status": "Error",
                "details": f"Daily total ({daily_total}) exceeds profile total ({profile_total})"
            })

        daily_difficulties = {
            "easy": sum(day["easy"] for day in stats["daily_activity"]),
            "medium": sum(day["medium"] for day in stats["daily_activity"]),
            "hard": sum(day["hard"] for day in stats["daily_activity"])
        }
        for difficulty in ["easy", "medium", "hard"]:
            profile_count = stats["problems_solved"].get(difficulty, 0)
            daily_count = daily_difficulties[difficulty]
            if daily_count > profile_count:
                logger.warning(f"Data inconsistency for {username}: {difficulty} daily count ({daily_count}) exceeds profile count ({profile_count})")
                self.validation_report.append({
                    "username": username,
                    "status": "Error",
                    "details": f"{difficulty} daily count ({daily_count}) exceeds profile count ({profile_count})"
                })

        self.validation_report.append({
            "username": username,
            "status": "Success",
            "details": f"Processed {daily_total} submissions"
        })
        return stats

    async def process_multiple_users(self, usernames):
        """Process multiple users concurrently"""
        await self._init_session()
        valid_usernames = []
        for username in usernames:
            if await self.validate_username(username):
                valid_usernames.append(username)
            else:
                logger.warning(f"Excluding invalid username: {username}")

        tasks = []
        for username in valid_usernames:
            await asyncio.sleep(1.0 / self.rate_limit)
            tasks.append(self.process_user(username))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {result["username"]: result for result in results if isinstance(result, dict)}

def save_activity_to_csv(results, filename, days):
    """Save activity to CSV file"""
    rows = []
    for username, data in results.items():
        if "error" in data:
            continue
        for day in data["daily_activity"]:
            rows.append({
                "username": username,
                "date": day["date"],
                "easy": day["easy"],
                "medium": day["medium"],
                "hard": day["hard"],
                "total": day["total"],
                "year_range": day["year_range"]
            })

    if not rows:
        rows = [{"username": "", "date": "", "easy": 0, "medium": 0, "hard": 0, "total": 0, "year_range": "2022-2026"}]

    keys = rows[0].keys()
    with open(filename, 'w', newline='') as f:
        dict_writer = csv.DictWriter(f, keys)
        dict_writer.writeheader()
        dict_writer.writerows(rows)
    logger.info(f"Activity for past {days} days saved to {filename}")

def save_validation_report(report, filename="./output/validation_report.json"):
    """Save validation report to JSON"""
    try:
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)
        logger.info(f"Validation report saved to {filename}")
    except Exception as e:
        logger.error(f"Error saving validation report: {e}")

async def main(usernames, days=7, output_file="./output/leetcode_daily_activity.csv"):
    """Main function to handle async execution"""
    scraper = LeetCodeScraper(max_workers=5, rate_limit=5, days=days, submission_limit=1000)
    try:
        results = await scraper.process_multiple_users(usernames)
        save_activity_to_csv(results, output_file, days)
        save_validation_report(scraper.validation_report)
        logger.info("\n--- Summary ---")
        for username, stats in results.items():
            logger.info(f"\n{username} Statistics:")
            if "error" in stats:
                logger.warning(f"Error: {stats['error']}")
                continue
            logger.info(f"Total Problems Solved: {stats.get('total_solved', 'N/A')}")
            problems = stats.get('problems_solved', {})
            logger.info(f"Easy: {problems.get('easy', 'N/A')}")
            logger.info(f"Medium: {problems.get('medium', 'N/A')}")
            logger.info(f"Hard: {problems.get('hard', 'N/A')}")
            logger.info("\nRecent Activity (last 5 days shown):")
            for day in stats["daily_activity"][:5]:
                logger.info(f"  {day['date']}: {day['total']} problems (E:{day['easy']} M:{day['medium']} H:{day['hard']})")
    finally:
        await scraper.close_session()

def debug_leetcode_api(username):
    """Debug function to check recent submissions format"""
    url = "https://leetcode.com/graphql"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    query = """
    query recentSubmissions($username: String!) {
        recentSubmissionList(username: $username, limit: 5) {
            title
            timestamp
            statusDisplay
            lang
            id
            titleSlug
        }
    }
    """
    variables = {"username": username}
    payload = {"query": query, "variables": variables}
    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"Status code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        if "data" in data and "recentSubmissionList" in data["data"]:
            submissions = data["data"]["recentSubmissionList"]
            if submissions:
                logger.info(f"Sample submission timestamp: {submissions[0].get('timestamp')}")
                logger.info(f"Sample timestamp type: {type(submissions[0].get('timestamp'))}")
                logger.info(f"First few submissions: {json.dumps(submissions[:2], indent=2)}")
            else:
                logger.info("No submissions found")
        else:
            logger.warning("Unexpected response format")
            logger.warning(f"Response: {json.dumps(data, indent=2)}")
    else:
        logger.error(f"Error response: {response.text}")
    return response.json() if response.status_code == 200 else None

if __name__ == "__main__":
    def load_usernames(filename="usernames.txt"):
        with open(filename, 'r') as file:
            return [line.strip() for line in file if line.strip()]
    usernames = load_usernames()
    asyncio.run(main(usernames, days=7))
