import asyncio
import aiohttp
import json
import csv
import logging
import sqlite3
from datetime import datetime, timedelta
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import pytz
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class LeetCodeScraper:
    def __init__(self, days=7, submission_limit=100, max_concurrent=20):
        """
        Initialize the LeetCode scraper with optimized settings.

        Args:
            days (int): Number of days to scrape (e.g., 7).
            submission_limit (int): Max submissions to fetch per user.
            max_concurrent (int): Max concurrent API requests.
        """
        self.days = days
        self.submission_limit = submission_limit
        self.max_concurrent = max_concurrent
        self.session = None
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124",
            "Referer": "https://leetcode.com/",
            "Origin": "https://leetcode.com"
        }
        self.cache_db = "leetcode_cache.db"
        self.difficulty_cache_file = "./output/difficulty_cache.json"
        self.difficulty_cache = self.load_difficulty_cache()
        self.year_range = "2022-2026"
        self.validation_report = []
        self.init_cache_db()

    def init_cache_db(self):
        """Initialize SQLite cache database."""
        self.conn = sqlite3.connect(self.cache_db)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                username TEXT PRIMARY KEY,
                data TEXT,
                timestamp DATETIME
            )
        """)
        self.conn.commit()

    def load_difficulty_cache(self):
        """Load difficulty cache from disk."""
        try:
            if os.path.exists(self.difficulty_cache_file):
                with open(self.difficulty_cache_file, 'r') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logger.error(f"Error loading difficulty cache: {e}")
            return {}

    def save_difficulty_cache(self):
        """Save difficulty cache to disk."""
        try:
            with open(self.difficulty_cache_file, 'w') as f:
                json.dump(self.difficulty_cache, f)
        except Exception as e:
            logger.error(f"Error saving difficulty cache: {e}")

    async def _init_session(self):
        """Initialize aiohttp session with connection pooling."""
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=10)
            self.session = aiohttp.ClientSession(
                headers=self.headers,
                timeout=timeout,
                connector=aiohttp.TCPConnector(limit=self.max_concurrent)
            )

    async def close_session(self):
        """Close aiohttp session."""
        if self.session:
            await self.session.close()
            self.session = None
        self.conn.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=1, max=5),
        retry=retry_if_exception_type((aiohttp.ClientError, ValueError))
    )
    async def get_user_data(self, username):
        """Fetch user profile and submissions in a single GraphQL query."""
        await self._init_session()
        query = """
        query userData($username: String!, $limit: Int!) {
            matchedUser(username: $username) {
                username
                submitStats {
                    acSubmissionNum {
                        difficulty
                        count
                    }
                }
            }
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

        async with self.semaphore:
            async with self.session.post(url, json=payload) as response:
                if response.status != 200:
                    logger.error(f"Fetch for {username}: HTTP {response.status}")
                    raise ValueError(f"HTTP {response.status}")
                data = await response.json()
                if data.get("data") is None or data["data"].get("matchedUser") is None:
                    logger.warning(f"User '{username}' not found")
                    return None
                return data["data"]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=1, max=5),
        retry=retry_if_exception_type((aiohttp.ClientError, ValueError))
    )
    async def get_problem_difficulty(self, title_slug):
        """Get problem difficulty with caching."""
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

        async with self.semaphore:
            async with self.session.post(url, json=payload) as response:
                if response.status != 200:
                    logger.error(f"Difficulty fetch for {title_slug}: HTTP {response.status}")
                    raise ValueError(f"HTTP {response.status}")
                data = await response.json()
                if data.get("data") is None or data["data"].get("question") is None:
                    logger.warning(f"No difficulty data for {title_slug}")
                    return "Unknown"
                difficulty = data["data"]["question"]["difficulty"]
                self.difficulty_cache[title_slug] = difficulty
                self.save_difficulty_cache()
                return difficulty

    async def get_cached_user_data(self, username):
        """Check cache before fetching user data."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT data, timestamp FROM cache WHERE username = ?", (username,))
        result = cursor.fetchone()
        if result:
            timestamp = datetime.fromisoformat(result[1])
            if timestamp > datetime.now() - timedelta(hours=1):  # Cache valid for 1 hour
                return json.loads(result[0])

        data = await self.get_user_data(username)
        if data:
            cursor.execute(
                "INSERT OR REPLACE INTO cache (username, data, timestamp) VALUES (?, ?, ?)",
                (username, json.dumps(data), datetime.now().isoformat())
            )
            self.conn.commit()
        return data

    async def process_user(self, username):
        """Process a single user's data."""
        data = await self.get_cached_user_data(username)
        if not data:
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

        stats = {"username": username, "problems_solved": {}}
        try:
            submission_stats = data["matchedUser"]["submitStats"]["acSubmissionNum"]
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

        submissions = data.get("recentSubmissionList", [])
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

        unique_submissions = set()
        for submission in submissions:
            try:
                timestamp = int(submission.get("timestamp", 0))
                dt = datetime.fromtimestamp(timestamp, tz=pytz.UTC)
                date_str = dt.strftime("%Y-%m-%d")
                if dt < time_ago or submission.get("statusDisplay") != "Accepted":
                    continue
                submission_id = submission.get("id")
                title_slug = submission["titleSlug"]
                submission_key = f"{date_str}:{title_slug}:{submission_id}"
                if submission_key in unique_submissions:
                    continue
                unique_submissions.add(submission_key)
                difficulty = await self.get_problem_difficulty(title_slug)
                difficulty = difficulty.lower()
                if date_str in daily_activity and difficulty in ["easy", "medium", "hard"]:
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

        stats["daily_activity"] = sorted(
            daily_activity.values(),
            key=lambda x: x["date"],
            reverse=True
        )

        self.validation_report.append({
            "username": username,
            "status": "Success",
            "details": f"Processed {stats['total_solved']} submissions"
        })
        return stats

    async def process_multiple_users(self, usernames):
        """Process multiple users concurrently."""
        await self._init_session()
        tasks = [self.process_user(username) for username in usernames]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {result["username"]: result for result in results if isinstance(result, dict)}

def save_activity_to_csv(results, filename, days):
    """Save activity to CSV file."""
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
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, 'w', newline='') as f:
        dict_writer = csv.DictWriter(f, keys)
        dict_writer.writeheader()
        dict_writer.writerows(rows)
    logger.info(f"Activity for past {days} days saved to {filename}")

def save_validation_report(report, filename="./output/validation_report.json"):
    """Save validation report to JSON."""
    try:
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)
        logger.info(f"Validation report saved to {filename}")
    except Exception as e:
        logger.error(f"Error saving validation report: {e}")

async def main(usernames, days=7, output_file="./output/leetcode_daily_activity.csv"):
    """Main function to handle async execution."""
    scraper = LeetCodeScraper(days=days, submission_limit=100, max_concurrent=20)
    try:
        start_time = datetime.now()
        results = await scraper.process_multiple_users(usernames)
        save_activity_to_csv(results, output_file, days)
        save_validation_report(scraper.validation_report)
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Scraping completed in {elapsed:.2f} seconds")
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
    finally:
        await scraper.close_session()

if __name__ == "__main__":
    def load_usernames(filename="usernames.txt"):
        try:
            with open(filename, 'r') as file:
                return [line.strip() for line in file if line.strip()]
        except FileNotFoundError:
            logger.error("usernames.txt not found. Using default usernames.")
            return ["user1", "user2", "user3"]  # Replace with real usernames

    usernames = load_usernames()
    asyncio.run(main(usernames, days=7))
